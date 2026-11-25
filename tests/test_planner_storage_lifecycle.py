"""Native startup, catalogue borrowing and durable receipt phase boundaries."""
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import Mock

from campaign_agent.adapters.sqlite_runs import SQLiteRunStorage
from campaign_agent.adapters.sqlite_planner import SQLitePlannerStore
from campaign_agent.agent.planning_models import SimulatedPlanner
from campaign_agent.domain.inference_errors import ReviewInferenceError
import test_placement_planner as fixtures


class PlannerStorageLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.PlacementPlannerTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_legacy_backfill_is_local_scoped_atomic_and_idempotent(self):
        path = self.case.directory / 'legacy.sqlite3'
        raw = '  Authored legacy request 語\n  '
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE agent_runs(id TEXT PRIMARY KEY,client_id TEXT,brand_id TEXT,actor_id TEXT,request TEXT,status TEXT)')
            db.executemany('INSERT INTO agent_runs VALUES(?,?,?,?,?,?)', [
                ('a', 'local-client', 'tts-demo', 'actor', raw, 'running'),
                ('b', 'local-client', 'tts-demo', 'actor', raw, 'answered'),
                ('c', 'foreign', 'tts-demo', 'actor', raw, 'running')])
            db.execute("CREATE TRIGGER fail_adoption BEFORE UPDATE ON agent_runs WHEN NEW.id='b' "
                       "BEGIN SELECT RAISE(ABORT, 'Authored adoption failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            SQLiteRunStorage.initialize(path, legacy_client_id='local-client', legacy_brand_id='tts-demo')
        with closing(sqlite3.connect(path)) as db, db:
            self.assertNotIn('campaign_id', [row[1] for row in db.execute('PRAGMA table_info(agent_runs)')])
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='agent_steps'").fetchone())
            self.assertEqual(db.execute('SELECT request FROM agent_runs').fetchall(), [(raw,)] * 3)
            db.execute('DROP TRIGGER fail_adoption')
        SQLiteRunStorage.initialize(path, legacy_client_id='local-client', legacy_brand_id='tts-demo')
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT id,campaign_id,request,status FROM agent_runs ORDER BY id').fetchall(),
                             [('a', 'tts-sample', raw, 'running'), ('b', 'tts-sample', raw, 'answered'),
                              ('c', None, raw, 'running')])
            before = list(db.iterdump())
        SQLiteRunStorage.initialize(path, legacy_client_id='local-client', legacy_brand_id='tts-demo')
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(list(db.iterdump()), before)

    def test_receipt_port_retains_exact_text_and_original_failure_updates(self):
        run = self.case.start()
        runtime = self.case.runtime
        with closing(sqlite3.connect(self.case.path)) as db, db:
            store = SQLitePlannerStore(db)
            store.request_turn(run, 0)
            store.request_turn(run, 1)
            store.request_classification(run)
        receipt = ' { "call_id": "authored", "tool": "read_campaign", "arguments": {}, "note": "語" } \n'
        classification = ' { "assignments": [], "label": "authored 語" } '
        runtime.planner.receipt_storage.receive_turn(run, 0, receipt)
        runtime.planner.receipt_storage.fail_turn(run, 1, 'Authored safe failure')
        runtime.planner.receipt_storage.receive_classification(run, classification)
        with closing(sqlite3.connect(self.case.path)) as db:
            store = SQLitePlannerStore(db)
            self.assertEqual(store.turn_row(run, 0), ('received', receipt, None))
            self.assertEqual(store.turn_row(run, 1), ('failed', None, 'Authored safe failure'))
            self.assertEqual(store.classification_row(run), ('received', classification))
        runtime.planner.receipt_storage.fail_classification(run)
        with closing(sqlite3.connect(self.case.path)) as db:
            self.assertEqual(SQLitePlannerStore(db).classification_row(run), ('failed', classification))

    def test_failed_receipt_write_keeps_requested_state_and_never_repeats_inference(self):
        model = Mock(wraps=SimulatedPlanner())
        runtime = self.case.reopen(planner_simulator=model)
        run = self.case.start(runtime=runtime)
        with closing(sqlite3.connect(self.case.path)) as db, db:
            db.execute("CREATE TRIGGER fail_receipt BEFORE UPDATE OF receipt ON planner_turns "
                       "WHEN NEW.receipt IS NOT NULL BEGIN SELECT RAISE(ABORT, 'Authored receipt failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            runtime.resume(run, max_steps=1)
        self.assertEqual(model.next_turn.call_count, 1)
        self.assertEqual(self.case.persisted(run)['turns'], [(0, 'requested', None, None)])
        self.assertEqual(self.case.persisted(run)['steps'], [])
        with self.assertRaises(ReviewInferenceError):
            runtime.resume(run, max_steps=1)
        self.assertEqual(model.next_turn.call_count, 1)
        self.assertEqual(self.case.runtime.drafts.read()['revision'], 1)

    def test_catalogue_reader_uses_exact_borrowed_transaction(self):
        catalog_id = 'a' * 32
        rows = [{'video_id': 'SAMPLE00001', 'description': 'Uncommitted authored entry',
                 'source': 'synthetic', 'source_reference': 'Authored fixture'}]
        with self.assertRaisesRegex(RuntimeError, 'Rollback'):
            with self.case.runtime.drafts.write_unit() as db:
                db.execute('INSERT INTO placement_catalogs VALUES(?,?,?,?,?,?)',
                           (catalog_id, 'local-client', 'tts-demo', 'tts-sample', 'Authored', json.dumps(rows)))
                self.assertEqual(self.case.runtime.planner.catalogs.read(SQLitePlannerStore(db).catalogs, catalog_id), rows)
                with closing(sqlite3.connect(self.case.path)) as observer:
                    with self.assertRaises(ValueError):
                        self.case.runtime.planner.catalogs.read(SQLitePlannerStore(observer).catalogs, catalog_id)
                raise RuntimeError('Rollback')
        with closing(sqlite3.connect(self.case.path)) as db:
            with self.assertRaises(ValueError):
                self.case.runtime.planner.catalogs.read(SQLitePlannerStore(db).catalogs, catalog_id)
