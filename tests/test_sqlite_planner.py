"""Native planner rows and caller-owned transaction conformance."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from campaign_agent.adapters.sqlite_planner import SQLitePlannerStore
from campaign_agent.agent.run import AgentRuntime
from campaign_agent.creatives import EXAMPLES


class SQLitePlannerStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.path, media = self.directory / 'planner.sqlite', self.directory / 'media'
        media.mkdir()
        for example in EXAMPLES:
            for name in {example.preview, *(take[2] for take in example.takes)}:
                (media / name).write_bytes(name.encode())
        # Exercise the actual application constructors' schema, not a copied DDL.
        self.runtime = AgentRuntime(self.path, media_dir=media)
        self.db = self.enterContext(closing(sqlite3.connect(self.path)))
        self.store = SQLitePlannerStore(self.db)

    def test_defaults_keep_original_three_field_scope_raw_values_and_native_conflicts(self):
        scope = ('Client\0語', 'Brand', 'Actor')
        self.assertIsNone(self.store.default_row(*scope))
        self.store.upsert_default(*scope, '  model\0語\n')
        for index in range(3):
            other = list(scope)
            other[index] += '-other'
            self.store.upsert_default(*other, f'other-{index}')
            self.assertEqual(self.store.default_row(*other), (f'other-{index}',))
        self.assertIsNone(self.store.default_row('client\0語', *scope[1:]))
        self.assertEqual(self.store.default_row(*scope), ('  model\0語\n',))
        self.store.upsert_default(*scope, 'replacement')
        self.assertEqual(self.store.default_row(*scope), ('replacement',))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM planner_defaults').fetchone(), (4,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.upsert_default(*scope, None)
        # The native nullable composite key admits separate NULL-owner rows.
        self.store.upsert_default(None, 'Brand', 'Actor', 'first')
        self.store.upsert_default(None, 'Brand', 'Actor', 'second')
        self.assertIsNone(self.store.default_row(None, 'Brand', 'Actor'))
        self.assertEqual(self.db.execute('SELECT model FROM planner_defaults WHERE client_id IS NULL ORDER BY rowid').fetchall(),
                         [('first',), ('second',)])
        self.db.rollback()
        local = (self.runtime.scope.client_id, self.runtime.scope.brand_id, self.runtime.operator.id)
        for saved, expected in [('simulated-inspect', 'simulated-inspect'), ('unavailable\0語', 'simulated')]:
            self.store.upsert_default(*local, saved)
            self.db.commit()
            self.assertEqual(self.runtime.planner.options()['default'], expected)

    def test_job_shapes_defaults_errors_and_raw_outcome_survive_reopen(self):
        raw = ' \n{ "text": "語" }\0 raw tail '
        self.assertIsNone(self.store.job_exists_row('Run\0語'))
        self.assertIsNone(self.store.job_snapshot_row('Run\0語'))
        self.assertIsNone(self.store.job_result_row('Run\0語'))
        self.assertIsNone(self.store.classification_row('Run\0語'))
        self.store.create_job('Run\0語', 'Session\0語', raw)
        self.assertEqual(self.store.job_exists_row('Run\0語'), (1,))
        self.assertIsNone(self.store.job_exists_row('run\0語'))
        self.assertEqual(self.store.job_snapshot_row('Run\0語'), (raw,))
        self.assertEqual(self.store.job_result_row('Run\0語'), (raw, None))
        self.assertEqual(self.store.classification_row('Run\0語'), ('pending', None))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_job('Run\0語', 'replacement', 'replacement')
        for session, snapshot in [(None, raw), ('session', None)]:
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.create_job('invalid', session, snapshot)
        self.assertIsNone(self.store.job_exists_row('invalid'))
        self.store.update_outcome('missing', raw)
        self.assertIsNone(self.store.job_result_row('missing'))
        self.store.update_outcome('Run\0語', raw)
        self.db.commit()
        with closing(sqlite3.connect(self.path)) as reopened:
            store = SQLitePlannerStore(reopened)
            self.assertEqual(store.job_result_row('Run\0語'), (raw, raw))
            self.assertEqual(reopened.execute('SELECT session_id FROM planner_jobs').fetchone(), ('Session\0語',))

    def test_fixed_classification_and_turn_updates_preserve_untouched_columns(self):
        raw, error = ' \nraw receipt 語\0 ', ' prior error\0語 '
        self.store.create_job('Run', 'Session', ' original snapshot ')
        self.store.update_outcome('Run', ' prior outcome ')
        self.store.receive_classification('Run', raw)
        for update, state in [(self.store.request_classification, 'requested'),
                              (self.store.fail_classification, 'failed')]:
            update('Run')
            self.assertEqual(self.store.classification_row('Run'), (state, raw))
        self.store.receive_classification('Run', None)
        self.assertEqual(self.store.classification_row('Run'), ('received', None))
        self.assertEqual(self.store.job_result_row('Run'), (' original snapshot ', ' prior outcome '))
        self.assertIsNone(self.store.turn_row('Run', 7))
        self.store.request_turn('Run', 7)
        self.assertEqual(self.store.turn_row('Run', 7), ('requested', None, None))
        self.store.receive_turn('Run', 7, raw)
        self.store.fail_turn('Run', 7, error)
        self.assertEqual(self.store.turn_row('Run', 7), ('failed', raw, error))
        self.store.request_turn('Run', 7)
        self.assertEqual(self.store.turn_row('Run', 7), ('failed', raw, error))
        self.store.receive_turn('Run', 7, ' replacement\0 ')
        self.assertEqual(self.store.turn_row('Run', 7), ('received', ' replacement\0 ', error))
        self.store.receive_turn('Run', 7, None)
        self.store.fail_turn('Run', 7, None)
        self.assertEqual(self.store.turn_row('Run', 7), ('failed', None, None))
        for update in (self.store.request_classification, self.store.fail_classification):
            update('missing')
        self.store.receive_classification('missing', raw)
        self.store.receive_turn('missing', 7, raw)
        self.store.fail_turn('missing', 7, error)
        self.assertIsNone(self.store.classification_row('missing'))
        self.assertIsNone(self.store.turn_row('missing', 7))

    def test_history_join_and_turn_order_preserve_raw_values_and_absent_sides(self):
        raw = ' \n{ "value": "語" }\0 '
        # Neither history nor turns require a job/authority record to return facts.
        for run, position, tool, result in [('Run', 9, 'tool\0語', raw), ('Run', 2, 'earlier', '{malformed'),
                                             ('Run', 4, 'step-only', 'orphan'), ('run', 2, 'foreign', 'private')]:
            self.db.execute('INSERT INTO agent_steps VALUES(?,?,?,?)', (run, position, tool, result))
        for run, position, receipt in [('Run', 9, raw), ('Run', 2, None), ('Run', 1, 'turn-only'), ('run', 2, 'private')]:
            self.store.request_turn(run, position)
            self.store.receive_turn(run, position, receipt)
        self.assertEqual(self.store.history_rows('Run'), [('earlier', '{malformed', None), ('tool\0語', raw, raw)])
        self.assertEqual(self.store.turn_rows('Run'), [(1, 'received', 'turn-only'), (2, 'received', None), (9, 'received', raw)])
        self.assertEqual(self.store.history_rows('run'), [('foreign', 'private', 'private')])
        self.assertEqual(self.store.history_rows('missing'), [])
        self.assertEqual(self.store.turn_rows('missing'), [])
        with self.assertRaises(json.JSONDecodeError):
            self.runtime.planner._history(self.db, 'Run')
        self.db.execute("UPDATE agent_steps SET result='{}' WHERE run_id='Run' AND position=2")
        with self.assertRaises(TypeError):
            self.runtime.planner._history(self.db, 'Run')

    def test_borrowed_uncommitted_visibility_savepoint_sibling_rollback_and_reopen(self):
        self.assertIs(self.store.connection, self.db)
        with closing(sqlite3.connect(self.path)) as observer:
            other = SQLitePlannerStore(observer)
            self.db.execute('BEGIN')
            self.store.upsert_default('C', 'B', 'A', 'outer')
            self.store.create_job('Run', 'Session', ' outer snapshot ')
            self.store.request_turn('Run', 3)
            self.db.execute('INSERT INTO agent_steps VALUES(?,?,?,?)', ('Run', 3, 'sibling', ' outer result '))
            self.assertEqual(self.store.turn_row('Run', 3), ('requested', None, None))
            self.assertIsNone(other.job_exists_row('Run'))
            self.assertIsNone(other.default_row('C', 'B', 'A'))
            self.assertEqual(other.history_rows('Run'), [])
            self.db.execute('SAVEPOINT sibling')
            self.store.receive_turn('Run', 3, ' sibling receipt ')
            self.store.receive_classification('Run', ' sibling classification ')
            self.store.update_outcome('Run', ' sibling outcome ')
            self.store.upsert_default('C', 'B', 'A', 'sibling')
            self.db.execute("UPDATE agent_steps SET result=' sibling result ' WHERE run_id='Run'")
            self.assertEqual(self.store.history_rows('Run'), [('sibling', ' sibling result ', ' sibling receipt ')])
            self.db.execute('ROLLBACK TO sibling')
            self.db.execute('RELEASE sibling')
            self.assertTrue(self.db.in_transaction)
            self.assertEqual(self.store.history_rows('Run'), [('sibling', ' outer result ', None)])
            self.assertEqual(self.store.classification_row('Run'), ('pending', None))
            self.assertEqual(self.store.job_result_row('Run'), (' outer snapshot ', None))
            self.assertEqual(self.store.default_row('C', 'B', 'A'), ('outer',))
            self.db.commit()
            self.assertEqual(other.history_rows('Run'), [('sibling', ' outer result ', None)])
            self.db.execute('BEGIN')
            self.store.fail_turn('Run', 3, ' rolled back error ')
            self.store.receive_classification('Run', ' rolled back classification ')
            self.store.update_outcome('Run', ' rolled back outcome ')
            self.store.create_job('rolled-back', 'Session', 'never committed')
            self.db.execute("UPDATE agent_steps SET result=' rolled back sibling ' WHERE run_id='Run'")
            self.db.rollback()
            self.assertEqual(self.db.execute('SELECT 1').fetchone(), (1,))
        with closing(sqlite3.connect(self.path)) as reopened:
            store = SQLitePlannerStore(reopened)
            self.assertEqual(store.turn_row('Run', 3), ('requested', None, None))
            self.assertEqual(store.history_rows('Run'), [('sibling', ' outer result ', None)])
            self.assertEqual(store.classification_row('Run'), ('pending', None))
            self.assertEqual(store.job_result_row('Run'), (' outer snapshot ', None))
            self.assertIsNone(store.job_exists_row('rolled-back'))

    def test_authored_nullable_legacy_rows_retain_present_null_and_app_errors(self):
        catalog = self.runtime.planner.catalogs.register('Authored', [
            {'video_id': 'SAMPLE00001', 'source': 'synthetic', 'description': 'Editing voiceover'}])
        run_id = self.runtime.planner.start('Explain campaign', 'simulated', uuid4().hex, uuid4().hex, catalog)
        # Explicit authored legacy schema: nullable snapshot/model is not today's DDL.
        self.db.executescript('''
            ALTER TABLE planner_jobs RENAME TO old_jobs;
            CREATE TABLE planner_jobs (run_id TEXT PRIMARY KEY, session_id TEXT, snapshot TEXT,
                classification_state TEXT DEFAULT 'pending', classification TEXT, outcome TEXT);
            INSERT INTO planner_jobs SELECT * FROM old_jobs;
            DROP TABLE old_jobs;
            ALTER TABLE planner_defaults RENAME TO old_defaults;
            CREATE TABLE planner_defaults (client_id TEXT, brand_id TEXT, actor_id TEXT, model TEXT,
                PRIMARY KEY(client_id,brand_id,actor_id));
            INSERT INTO planner_defaults SELECT * FROM old_defaults;
            DROP TABLE old_defaults;
        ''')
        for raw, error in [(None, TypeError), ('{bad json', json.JSONDecodeError)]:
            with self.subTest(raw=raw):
                self.db.execute('UPDATE planner_jobs SET snapshot=?,classification_state=NULL WHERE run_id=?', (raw, run_id))
                self.db.commit()
                self.assertEqual(self.store.job_snapshot_row(run_id), (raw,))
                self.assertEqual(self.store.job_result_row(run_id), (raw, None))
                self.assertEqual(self.store.classification_row(run_id), (None, None))
                with self.assertRaises(error):
                    self.runtime.read(run_id)
                with self.assertRaises(error):
                    self.runtime.planner._context(self.db, run_id)
        self.db.execute('DELETE FROM planner_jobs WHERE run_id=?', (run_id,))
        self.db.commit()
        with self.assertRaises(TypeError):
            self.runtime.planner.read(run_id)
        with self.assertRaises(TypeError):
            self.runtime.planner._context(self.db, run_id)
        scope = (self.runtime.scope.client_id, self.runtime.scope.brand_id, self.runtime.operator.id)
        self.store.upsert_default(*scope, None)
        self.db.commit()
        self.assertEqual(self.store.default_row(*scope), (None,))
        self.assertEqual(self.runtime.planner.options()['default'], 'simulated')


if __name__ == '__main__':
    unittest.main()
