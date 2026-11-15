"""Native row and borrowed-transaction conformance for conversation records."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from campaign_agent.adapters.sqlite_conversations import SQLiteConversationStore
from campaign_agent.agent.conversations import CampaignConversations


class SQLiteConversationStoreTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / 'conversation.sqlite'
        self.db = self.enterContext(closing(sqlite3.connect(self.path)))
        # Nullable historical settings/snapshots exercise present-invalid rows too.
        self.db.executescript('''
            CREATE TABLE planner_sessions (id TEXT PRIMARY KEY, client_id TEXT, brand_id TEXT,
                actor_id TEXT, settings TEXT, campaign_id TEXT);
            CREATE TABLE planner_jobs (run_id TEXT PRIMARY KEY, session_id TEXT, snapshot TEXT, outcome TEXT);
            CREATE TABLE planner_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL, run_id TEXT NOT NULL, role TEXT NOT NULL,
                content TEXT NOT NULL, revision INTEGER NOT NULL, catalog_id TEXT NOT NULL,
                kind TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE(run_id,role));
        ''')
        self.store = SQLiteConversationStore(self.db)
        scope = SimpleNamespace(client_id='client', brand_id='brand')
        drafts = SimpleNamespace(scope=scope, campaign_id='campaign', require=lambda capability: None)
        self.app = CampaignConversations.__new__(CampaignConversations)
        self.app.planner = SimpleNamespace(drafts=drafts)
        self.app.operator = SimpleNamespace(id='actor')
        self.app.path = self.path

    def job(self, run_id, session_id='session', snapshot=' { "revision": 4, "catalog_id": "Catalog" } ', outcome=None):
        self.db.execute('INSERT INTO planner_jobs VALUES(?,?,?,?)', (run_id, session_id, snapshot, outcome))

    def session(self, session_id='session', settings=' { "model": "simulated" } ', scope=('client', 'brand', 'actor', 'campaign')):
        self.store.create_session(session_id, *scope[:3], settings, scope[3])

    def test_raw_session_and_job_rows_preserve_missing_malformed_and_null(self):
        self.assertIsNone(self.store.session_row('missing'))
        self.assertIsNone(self.store.job_context_row('missing'))
        self.assertIsNone(self.app.session(self.db, 'missing'))
        with self.assertRaises(TypeError):
            self.app.finish(self.db, 'missing', {}, 'answered')
        for index, (raw, error) in enumerate([(' { "model": "simulated", "label": "語" } ', None),
                                               ('{bad json', json.JSONDecodeError), (None, TypeError), ('null', None)]):
            with self.subTest(raw=raw):
                session_id, run_id = f'session-{index}', f'Run-{index}'
                self.session(session_id, raw)
                self.job(run_id, session_id, raw)
                self.assertEqual(self.store.session_row(session_id), ('client', 'brand', 'actor', raw, 'campaign'))
                self.assertEqual(self.store.job_context_row(run_id), (session_id, raw))
                if error:
                    with self.assertRaises(error):
                        self.app.session(self.db, session_id)
                    with self.assertRaises(error):
                        self.app.finish(self.db, run_id, {}, 'answered')
                else:
                    self.assertEqual(self.app.session(self.db, session_id), json.loads(raw))
        self.session(settings='original')
        self.session(settings='replacement', scope=('foreign', 'brand', 'actor', 'campaign'))
        self.assertEqual(self.store.session_row('session'), ('client', 'brand', 'actor', 'original', 'campaign'))
        self.store.update_settings('session', '  [malformed settings]  ')
        self.assertEqual(self.store.session_row('session')[3], '  [malformed settings]  ')
        self.store.update_settings('missing', 'ignored')
        self.assertIsNone(self.store.session_row('missing'))

    def test_message_rows_keep_native_ids_times_raw_text_join_order_and_limits(self):
        outcome = ' { "message": "語", "revision": 7 } \n'
        self.job('Run-A', outcome=outcome)
        self.job('run-a', outcome='{broken outcome')
        self.db.execute('''INSERT INTO planner_messages VALUES(41,?,?,?,?,?,?,?,?)''',
                        ('session', 'Run-A', 'user', '  語\nraw request  ', 4, 'Catalog', 'request', '1999-01-02T03:04:05.006Z'))
        self.store.append_message('session', 'Run-A', 'assistant', 'raw answer', 7, 'Catalog', 'answered')
        generated = self.db.execute("SELECT * FROM planner_messages WHERE role='assistant'").fetchone()
        self.assertEqual(generated[:8], (42, 'session', 'Run-A', 'assistant', 'raw answer', 7, 'Catalog', 'answered'))
        self.assertRegex(generated[8], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$')
        self.store.append_message('session', 'Run-A', 'assistant', 'duplicate ignored', 99, 'different', 'wrong')
        self.assertEqual(self.db.execute('SELECT * FROM planner_messages WHERE id=42').fetchone(), generated)
        self.store.append_message('session', 'run-a', 'user', 'case-sensitive run', 4, 'Catalog', 'request')
        self.store.append_message('session', 'orphan', 'user', 'no joined job', 4, 'Catalog', 'request')
        self.job('elsewhere', session_id='other')
        self.store.append_message('other', 'elsewhere', 'user', 'different session', 4, 'Catalog', 'request')
        rows = self.store.message_rows('session')
        self.assertEqual([row[3] for row in rows], ['run-a', 'Run-A', 'Run-A'])
        self.assertEqual(rows[-1], (41, 'user', '  語\nraw request  ', 'Run-A', 4, 'Catalog', 'request', '1999-01-02T03:04:05.006Z', outcome))
        self.assertEqual(rows[1], (42, 'assistant', 'raw answer', 'Run-A', 7, 'Catalog', 'answered', generated[8], outcome))
        self.assertEqual(rows[0][8], '{broken outcome')
        for limit in (-1, -5, 100):
            self.assertEqual(self.store.message_rows('session', limit), rows)
        self.assertEqual(self.store.message_rows('session', 0), [])
        # Normalization remains in the application.
        for limit in (None, 0, -1, -5, 100):
            self.assertEqual([item['id'] for item in self.app.messages(self.db, 'session', limit)],
                             [row[0] for row in reversed(rows)])
        self.assertEqual([item['id'] for item in self.app.messages(self.db, 'session', 1)], [rows[0][0]])
        self.assertEqual(self.store.message_rows('session', 1), rows[:1])
        self.assertEqual(self.store.message_rows('session', 2), rows[:2])
        self.assertEqual(self.store.message_rows('missing'), [])
        self.assertEqual(self.store.message_count('session'), 4)  # Counts unjoined history too.
        self.assertEqual(self.store.latest_message_id('session'), self.db.execute(
            "SELECT id FROM planner_messages WHERE run_id='orphan'").fetchone()[0])
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.append_message('session', 'new-run', 'user', None, 4, 'Catalog', 'request')
        self.assertEqual(self.store.message_count('missing'), 0)
        self.assertEqual(self.store.latest_message_id('missing'), 0)

    def test_application_preserves_null_and_malformed_outcome_projection(self):
        for index, raw in enumerate((None, '', '{bad json')):
            with self.subTest(raw=raw):
                session_id, run_id = f'session-{index}', f'run-{index}'
                self.job(run_id, session_id, outcome=raw)
                self.store.append_message(session_id, run_id, 'assistant', 'Unverified historical claim', 4, 'Catalog', 'answered')
                self.assertEqual(self.store.message_rows(session_id)[0][8], raw)
                if raw:
                    with self.assertRaises(json.JSONDecodeError):
                        self.app.messages(self.db, session_id)
                else:
                    message, = self.app.messages(self.db, session_id)
                    self.assertEqual(message['kind'], 'needs_verification')
                    self.assertNotIn('Unverified historical claim', message['content'])

    def test_scoped_list_rows_keep_raw_titles_empty_rows_and_latest_order(self):
        self.session('empty')
        self.session('first')
        self.session('second', ' { "model": "simulated-inspect" } ')
        self.job('first-run', 'first')
        self.store.append_message('first', 'first-run', 'user', 'First title', 1, 'C', 'request')
        self.job('second-run', 'second')
        self.store.append_message('second', 'second-run', 'user', '語' * 100, 1, 'C', 'request')
        self.store.append_message('first', 'first-run', 'assistant', 'Latest reply is not the title', 1, 'C', 'ready_for_review')
        self.session('blank')
        self.job('blank-run', 'blank')
        self.store.append_message('blank', 'blank-run', 'user', '', 1, 'C', 'request')
        expected = [('blank', ' { "model": "simulated" } ', ''),
                    ('first', ' { "model": "simulated" } ', 'First title'),
                    ('second', ' { "model": "simulated-inspect" } ', '語' * 100),
                    ('empty', ' { "model": "simulated" } ', None)]
        for index in range(4):
            scope = ['client', 'brand', 'actor', 'campaign']
            scope[index] = 'foreign'
            self.session(f'foreign-{index}', '{private malformed JSON', tuple(scope))
            self.job(f'foreign-run-{index}', f'foreign-{index}')
            self.store.append_message(f'foreign-{index}', f'foreign-run-{index}', 'user', 'Private title', 1, 'C', 'request')
        self.assertEqual(self.store.list_rows('client', 'brand', 'actor', 'campaign'), expected)
        self.db.commit()
        self.assertEqual(self.app.list(), [
            {'id': 'first', 'model': 'simulated', 'title': 'First title'},
            {'id': 'second', 'model': 'simulated-inspect', 'title': '語' * 80}])
        for index in range(4):
            scope = ['client', 'brand', 'actor', 'campaign']
            scope[index] = 'foreign'
            self.assertEqual([row[0] for row in self.store.list_rows(*scope)], [f'foreign-{index}'])

    def test_borrowed_visibility_savepoint_sibling_rollback_and_reopen(self):
        with closing(sqlite3.connect(self.path)) as observer:
            self.db.execute('BEGIN')
            self.session()
            self.job('run')
            self.store.append_message('session', 'run', 'user', 'outer user', 4, 'Catalog', 'request')
            original = self.store.message_rows('session')
            self.assertEqual(self.store.session_row('session')[0], 'client')
            self.assertIsNone(SQLiteConversationStore(observer).session_row('session'))
            self.assertEqual(SQLiteConversationStore(observer).message_rows('session'), [])
            self.db.execute('SAVEPOINT sibling')
            self.store.update_settings('session', 'uncommitted settings')
            self.store.append_message('session', 'run', 'assistant', 'sibling answer', 4, 'Catalog', 'answered')
            self.db.execute("UPDATE planner_jobs SET outcome='sibling outcome' WHERE run_id='run'")
            self.assertEqual(self.store.message_count('session'), 2)
            self.db.execute('ROLLBACK TO sibling')
            self.db.execute('RELEASE sibling')
            self.assertEqual(self.store.message_rows('session'), original)
            self.assertEqual(self.store.session_row('session')[3], ' { "model": "simulated" } ')
            self.db.commit()
            self.assertEqual(SQLiteConversationStore(observer).message_rows('session'), original)
            self.db.execute('BEGIN')
            self.store.update_settings('session', 'rolled back')
            self.store.append_message('session', 'run', 'assistant', 'rolled back', 4, 'Catalog', 'answered')
            self.db.execute("UPDATE planner_jobs SET outcome='rolled back sibling' WHERE run_id='run'")
            self.db.rollback()
            self.assertEqual(self.db.execute('SELECT 1').fetchone(), (1,))
        with closing(sqlite3.connect(self.path)) as reopened:
            self.assertEqual(SQLiteConversationStore(reopened).message_rows('session'), original)
            self.assertEqual(reopened.execute('SELECT outcome FROM planner_jobs').fetchone(), (None,))


if __name__ == '__main__':
    unittest.main()
