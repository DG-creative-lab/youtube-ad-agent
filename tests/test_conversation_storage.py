"""Shared transaction and atomic legacy transcript adoption evidence."""
import json
import sqlite3
import unittest
from unittest.mock import patch

from campaign_agent.adapters.sqlite_planner import SQLitePlannerStore
from campaign_agent.adapters.sqlite_conversations import SQLiteConversationStore
import test_placement_planner as fixtures


class ConversationStorageTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.PlacementPlannerTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_supersession_and_terminal_message_share_callers_rollback(self):
        runtime = self.case.runtime
        run = self.case.start()
        before = self.case.persisted(run)
        outcome = {'revision': 1, 'ambiguous': [], 'message': 'Authored supersession.'}
        with self.assertRaisesRegex(RuntimeError, 'interrupt'):
            with runtime.drafts.write_unit() as db:
                store = SQLitePlannerStore(db).conversations
                self.assertIn(run, store.running_runs(self.case.session))
                store.supersede(run, json.dumps(outcome))
                runtime.planner.conversations.finish(store, run, outcome, 'superseded')
                self.assertEqual(db.execute('SELECT status FROM agent_runs WHERE id=?', (run,)).fetchone()[0], 'superseded')
                self.assertEqual(db.execute("SELECT COUNT(*) FROM planner_messages WHERE run_id=? AND role='assistant'", (run,)).fetchone()[0], 1)
                # A second reader must still see the previously committed state.
                self.assertEqual(self.case.persisted(run), before)
                raise RuntimeError('interrupt')
        self.assertEqual(self.case.persisted(run), before)
        result = self.case.finish(run)
        self.assertEqual(result['status'], 'ready_for_review')
        self.assertEqual([m['role'] for m in runtime.planner.conversations.read(self.case.session)['messages']],
                         ['user', 'assistant'])

    def test_failed_legacy_adoption_rolls_back_schema_and_retries_without_rewriting_jobs(self):
        run = self.case.start()
        self.case.finish(run)
        expected = self.case.runtime.planner.conversations.read(self.case.session)
        before = self.case.persisted(run)
        with sqlite3.connect(self.case.path) as db:
            db.execute('DROP TABLE planner_messages')
            db.execute('ALTER TABLE planner_sessions DROP COLUMN campaign_id')
        append = SQLiteConversationStore.append_message

        def interrupt_assistant(store, session, run_id, role, *args):
            if role == 'assistant':
                raise RuntimeError('interrupt adoption')
            return append(store, session, run_id, role, *args)

        with patch.object(SQLiteConversationStore, 'append_message', interrupt_assistant):
            with self.assertRaisesRegex(RuntimeError, 'interrupt adoption'):
                self.case.reopen()
        with sqlite3.connect(self.case.path) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='planner_messages'").fetchone())
            self.assertNotIn('campaign_id', [row[1] for row in db.execute('PRAGMA table_info(planner_sessions)')])
        reopened = self.case.reopen()
        after = self.case.persisted(run)
        for key in ('revisions', 'steps', 'turns', 'status', 'job'):
            self.assertEqual(after[key], before[key], key)
        migrated = reopened.planner.conversations.read(self.case.session)
        for message, original in zip(migrated['messages'], expected['messages']):
            self.assertEqual({k: v for k, v in message.items() if k != 'created_at'},
                             {k: v for k, v in original.items() if k != 'created_at'})
        self.assertEqual(len(migrated['messages']), len(expected['messages']))
        self.case.reopen()
        self.assertEqual(self.case.persisted(run), after)
