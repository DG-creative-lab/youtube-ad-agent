"""Native common run/step records preserve raw data and caller transactions."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from campaign_agent.adapters.sqlite_runs import SQLiteRunStore
from campaign_agent.bootstrap.runtime import create_runtime as AgentRuntime
from campaign_agent.creatives import EXAMPLES


class SQLiteRunStoreTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.path, media = directory / 'runs.sqlite', directory / 'media'
        media.mkdir()
        for example in EXAMPLES:
            for name in {example.preview, *(take[2] for take in example.takes)}:
                (media / name).write_bytes(name.encode())
        # The normal runtime owns the schema; the adapter has no initializer.
        AgentRuntime(self.path, media_dir=media)
        self.db = self.enterContext(closing(sqlite3.connect(self.path)))
        self.store = SQLiteRunStore(self.db)
        self.scope = ('Client\0語', 'Brand', 'Actor', 'Campaign')
        self.raw = ' \n{ "text": "語" }\0 raw tail '

    def create(self, run_id='Run', request=None, status='running'):
        self.store.create_run(run_id, *self.scope[:3], self.raw if request is None else request, status, self.scope[3])

    def test_fully_scoped_raw_pair_missing_and_status_only_update(self):
        self.assertIsNone(self.store.scoped_run_row('Run', *self.scope))
        self.create(status=' original\0語 ')
        self.create('sibling', status='sibling status')
        for index in range(4):
            foreign = list(self.scope)
            foreign[index] += '-foreign'
            self.assertIsNone(self.store.scoped_run_row('Run', *foreign))
        self.assertIsNone(self.store.scoped_run_row('run', *self.scope))
        self.assertIsNone(self.store.scoped_run_row('Run', 'client\0語', *self.scope[1:]))
        self.assertEqual(self.store.scoped_run_row('Run', *self.scope), (self.raw, ' original\0語 '))
        self.store.append_step('Run', 1, 'tool', self.raw)
        before = self.db.execute('SELECT * FROM agent_runs WHERE id=?', ('Run',)).fetchone()
        self.store.update_status('Run', ' superseded\0語 ')
        self.store.update_status('missing', 'ignored')
        expected = (*before[:5], ' superseded\0語 ', before[6])
        self.assertEqual(self.db.execute('SELECT * FROM agent_runs WHERE id=?', ('Run',)).fetchone(), expected)
        self.assertEqual(self.store.scoped_run_row('sibling', *self.scope), (self.raw, 'sibling status'))
        self.assertEqual(self.store.step_rows('Run'), [('tool', self.raw)])
        self.db.commit()
        with closing(sqlite3.connect(self.path)) as reopened:
            self.assertEqual(SQLiteRunStore(reopened).scoped_run_row('Run', *self.scope), (self.raw, ' superseded\0語 '))

    def test_three_run_insert_conflict_forms_preserve_native_distinctions(self):
        self.create()
        original = self.db.execute('SELECT * FROM agent_runs').fetchall()
        values = ('Run', *self.scope[:3], 'replacement', 'replacement', self.scope[3])
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_run(*values)
        self.store.create_run_if_id_absent(*values)
        self.store.create_run_if_no_conflict(*values)
        self.assertEqual(self.db.execute('SELECT * FROM agent_runs').fetchall(), original)
        # Reachable authored extension of the real schema: a second unique key
        # distinguishes targeted id-ignore from untargeted conflict-ignore.
        self.db.execute('CREATE UNIQUE INDEX authored_unique_run_request ON agent_runs(request)')
        other = ('Other', *self.scope[:3], self.raw, 'other', self.scope[3])
        for insert in (self.store.create_run, self.store.create_run_if_id_absent):
            with self.assertRaises(sqlite3.IntegrityError):
                insert(*other)
        self.store.create_run_if_no_conflict(*other)
        self.assertIsNone(self.store.scoped_run_row('Other', *self.scope))
        for insert in (self.store.create_run, self.store.create_run_if_id_absent, self.store.create_run_if_no_conflict):
            with self.subTest(insert=insert.__name__):
                invalid = ('Invalid', *self.scope[:3], None, 'running', self.scope[3])
                with self.assertRaises(sqlite3.IntegrityError):
                    insert(*invalid)
                valid = (insert.__name__, *self.scope[:3], insert.__name__, 'running', self.scope[3])
                insert(*valid)
                self.assertEqual(self.store.scoped_run_row(valid[0], *self.scope), (valid[4], 'running'))
        self.assertEqual(self.db.execute('SELECT * FROM agent_runs WHERE id=?', ('Run',)).fetchall(), original)

    def test_step_numeric_order_raw_values_count_existence_and_native_errors(self):
        self.assertEqual(self.store.step_rows('Run'), [])
        self.assertEqual(self.store.step_count('Run'), 0)
        self.assertIsNone(self.store.step_exists_row('Run', 1))
        for position, tool in ((10, 'ten'), (2, 'two'), (-1, ' first\0語 ')):
            self.store.append_step('Run', position, tool, self.raw)
        self.store.append_step('Sibling', 2, 'sibling', 'unchanged')
        self.assertEqual(self.store.step_rows('Run'), [(' first\0語 ', self.raw), ('two', self.raw), ('ten', self.raw)])
        self.assertEqual(self.store.step_count('Run'), 3)
        self.assertEqual(self.store.step_exists_row('Run', 2), (1,))
        self.assertIsNone(self.store.step_exists_row('run', 2))
        self.assertIsNone(self.store.step_exists_row('Run', 1))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.append_step('Run', 2, 'replacement', 'replacement')
        for position, tool, result in ((None, 'tool', 'result'), (3, None, 'result'), (3, 'tool', None)):
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.append_step('Run', position, tool, result)
        self.db.commit()
        with closing(sqlite3.connect(self.path)) as reopened:
            store = SQLiteRunStore(reopened)
            self.assertEqual(store.step_rows('Run'), [(' first\0語 ', self.raw), ('two', self.raw), ('ten', self.raw)])
            self.assertEqual(store.step_count('Run'), 3)
            self.assertEqual(store.step_rows('Sibling'), [('sibling', 'unchanged')])

    def test_borrowed_visibility_savepoint_sibling_and_full_rollback_reopen(self):
        with closing(sqlite3.connect(self.path)) as observer:
            observed = SQLiteRunStore(observer)
            self.create()
            self.store.append_step('Run', 0, 'accepted', self.raw)
            self.db.commit()
            baseline = (self.db.execute('SELECT * FROM agent_runs ORDER BY id').fetchall(),
                        self.db.execute('SELECT * FROM agent_steps ORDER BY run_id,position').fetchall())
            self.db.execute('BEGIN IMMEDIATE')
            self.create('Sibling')
            self.db.execute('SAVEPOINT tool')
            self.store.update_status('Run', 'changed')
            self.store.append_step('Run', 1, 'tentative', 'tentative')
            self.assertEqual(self.store.step_count('Run'), 2)
            self.assertEqual(observed.step_count('Run'), 1)
            self.assertEqual(observed.scoped_run_row('Run', *self.scope), (self.raw, 'running'))
            self.assertIsNone(observed.scoped_run_row('Sibling', *self.scope))
            self.db.execute('ROLLBACK TO tool')
            self.db.execute('RELEASE tool')
            self.assertTrue(self.db.in_transaction)
            self.assertEqual(self.store.step_count('Run'), 1)
            self.assertEqual(self.store.scoped_run_row('Run', *self.scope), (self.raw, 'running'))
            self.assertEqual(self.store.scoped_run_row('Sibling', *self.scope), (self.raw, 'running'))
            self.db.rollback()
            self.assertFalse(self.db.in_transaction)
            with closing(sqlite3.connect(self.path)) as reopened:
                self.assertEqual((reopened.execute('SELECT * FROM agent_runs ORDER BY id').fetchall(),
                                  reopened.execute('SELECT * FROM agent_steps ORDER BY run_id,position').fetchall()), baseline)
            # The borrower neither closes nor poisons the supplied connection.
            self.create('Committed')
            self.store.append_step('Committed', 0, 'new', 'usable')
            self.db.commit()
            self.assertEqual(observed.step_rows('Committed'), [('new', 'usable')])
            self.assertEqual(observed.scoped_run_row('Committed', *self.scope), (self.raw, 'running'))

    def test_explicit_nullable_legacy_variant_retains_present_null_pair_and_rows(self):
        # Labelled legacy shape only: current constructors require NOT NULL.
        with closing(sqlite3.connect(':memory:')) as legacy:
            legacy.executescript('''CREATE TABLE agent_runs (
                id TEXT PRIMARY KEY, client_id TEXT, brand_id TEXT, actor_id TEXT,
                request TEXT, status TEXT, campaign_id TEXT);
                CREATE TABLE agent_steps (run_id TEXT, position INTEGER, tool TEXT,
                result TEXT, PRIMARY KEY(run_id,position));''')
            store = SQLiteRunStore(legacy)
            store.create_run('Run', *self.scope[:3], None, None, self.scope[3])
            self.assertEqual(store.scoped_run_row('Run', *self.scope), (None, None))
            self.assertIsNone(store.scoped_run_row('missing', *self.scope))
            store.append_step('Run', 1, None, None)
            self.assertEqual(store.step_rows('Run'), [(None, None)])
            store.update_status('Run', self.raw)
            self.assertEqual(store.scoped_run_row('Run', *self.scope), (None, self.raw))

    def test_missing_schema_and_closed_connection_errors_are_native(self):
        with closing(sqlite3.connect(':memory:')) as empty:
            store = SQLiteRunStore(empty)
            with self.assertRaises(sqlite3.OperationalError):
                store.scoped_run_row('Run', *self.scope)
            self.assertEqual(empty.execute('SELECT name FROM sqlite_master').fetchall(), [])
        closed = SQLiteRunStore(empty)
        with self.assertRaises(sqlite3.ProgrammingError):
            closed.step_count('Run')


if __name__ == '__main__':
    unittest.main()
