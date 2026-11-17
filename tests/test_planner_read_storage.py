"""A run projection must come from one committed view of scoped native records."""
from dataclasses import replace
import json
import sqlite3
import unittest
from unittest.mock import patch

from campaign_agent.adapters.sqlite_planner import SQLitePlannerStore
from campaign_agent.ports.planner_records import PlannerRunScope
from campaign_agent.access import Operator, LOCAL_BRAND
import test_placement_planner as fixtures


class PlannerReadStorageTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.PlacementPlannerTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_concurrent_commit_cannot_mix_run_status_outcome_and_history(self):
        run = self.case.start()
        with sqlite3.connect(self.case.path) as db:
            db.execute('PRAGMA journal_mode=WAL')
        original = SQLitePlannerStore.job_result_row
        receipt = {'call_id': 'authored-read', 'tool': 'read_campaign', 'arguments': {}, 'inference': {}}

        def commit_after_status(store, run_id):
            with sqlite3.connect(self.case.path) as writer:
                writer.execute("UPDATE agent_runs SET status='answered' WHERE id=?", (run,))
                writer.execute('UPDATE planner_jobs SET outcome=? WHERE run_id=?',
                               (json.dumps({'revision': 1, 'message': 'Authored committed result.'}), run))
                writer.execute("INSERT INTO planner_turns VALUES(?,0,'received',?,NULL)", (run, json.dumps(receipt)))
                writer.execute('INSERT INTO agent_steps VALUES(?,0,?,?)', (run, 'read_campaign', '{}'))
            return original(store, run_id)

        with patch.object(SQLitePlannerStore, 'job_result_row', new=commit_after_status):
            snapshot = self.case.runtime.planner.read(run)
        self.assertEqual(snapshot['status'], 'running')
        self.assertIsNone(snapshot['result'])
        self.assertEqual(snapshot['steps'], [])
        self.assertEqual(snapshot['planner']['turns'], [])
        current = self.case.runtime.planner.read(run)
        self.assertEqual(current['status'], 'answered')
        self.assertIsNotNone(current['result'])
        self.assertEqual(len(current['steps']), 1)
        self.assertEqual(len(current['planner']['turns']), 1)


    def test_scoped_run_lookup_denies_foreign_dimensions_before_loading_details(self):
        run = self.case.start()
        runtime = self.case.runtime
        scope = PlannerRunScope(runtime.scope.client_id, runtime.scope.brand_id,
                                runtime.operator.id, runtime.drafts.campaign_id)
        with runtime.planner.read_storage.read() as reader:
            self.assertIsNotNone(reader.scoped_run_row(run, scope))
            for field in ('client_id', 'brand_id', 'actor_id', 'campaign_id'):
                self.assertIsNone(reader.scoped_run_row(run, replace(scope, **{field: 'foreign'})))
        foreign = self.case.reopen(operator=Operator('foreign', frozenset({LOCAL_BRAND})))
        with patch.object(SQLitePlannerStore, 'job_result_row', side_effect=AssertionError('Private details loaded')):
            with self.assertRaisesRegex(PermissionError, 'unavailable to this operator'):
                foreign.planner.read(run)
            with self.assertRaisesRegex(PermissionError, 'unavailable to this operator'):
                runtime.planner.read('f' * 32)
