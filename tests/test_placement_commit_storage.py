"""Complete placement save effects and already-received recovery stay atomic."""
import json
import sqlite3
import unittest
from unittest.mock import Mock, patch

from campaign_agent.domain.errors import PackageConflict
from campaign_agent.agent.planning_models import SimulatedPlanner
from campaign_agent.placement_discovery import SimulatedClassifier
import test_placement_planner as fixtures


class PlacementCommitTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.PlacementPlannerTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_final_save_uses_unit_not_native_writer_or_catalogue_reader(self):
        runtime = self.case.runtime
        run = self.case.start()
        runtime.resume(run, max_steps=2)
        with patch.object(runtime.planner, '_commit_legacy_turn', side_effect=AssertionError('Legacy commit')), \
             patch.object(runtime.drafts, 'write_unit', side_effect=AssertionError('Native writer')), \
             patch.object(runtime.drafts, '_save', side_effect=AssertionError('Native draft writer')), \
             patch.object(runtime.planner.catalogs, 'read', side_effect=AssertionError('Native catalogue read')):
            result = runtime.resume(run, max_steps=1)
        self.assertEqual(result['status'], 'ready_for_review')
        self.assertEqual(result['result']['revision'], 2)
        stored = self.case.persisted(run)
        self.assertEqual([row[0] for row in stored['steps']], [0, 1, 2])
        self.assertEqual([row[3] for row in stored['messages']], ['user', 'assistant'])
        self.assertIsNone(runtime.drafts.review_package('tts-sample', 2)['approval'])

    def test_failed_commit_rolls_back_all_effects_but_keeps_receipt_for_recovery(self):
        model = Mock(wraps=SimulatedPlanner())
        classifier = Mock(route='simulated_decision', wraps=SimulatedClassifier())
        runtime = self.case.reopen(planner_simulator=model, placement_classifier=classifier)
        run = self.case.start(runtime=runtime)
        runtime.resume(run, max_steps=2)
        before = self.case.persisted(run)
        with patch('campaign_agent.adapters.sqlite_planner._PlacementCommitUnit.commit',
                   side_effect=sqlite3.OperationalError('Authored commit failure')):
            with self.assertRaises(sqlite3.OperationalError):
                runtime.resume(run, max_steps=1)
        failed = self.case.persisted(run)
        for key in ('revisions', 'steps', 'status', 'job', 'messages'):
            self.assertEqual(failed[key], before[key], key)
        self.assertEqual(failed['turns'][-1], (2, 'received', self.case.saved_placement_receipt(), None))
        self.assertEqual(model.next_turn.call_count, 3)
        self.assertEqual(classifier.classify.call_count, 1)
        no_model = Mock(next_turn=Mock(side_effect=AssertionError('No repeated model call')))
        no_classifier = Mock(classify=Mock(side_effect=AssertionError('No repeated classification')))
        reopened = self.case.reopen(planner_simulator=no_model, placement_classifier=no_classifier)
        result = reopened.resume(run, max_steps=1)
        self.assertEqual(result['result']['revision'], 2)
        committed = self.case.persisted(run)
        self.assertEqual(committed['turns'], failed['turns'])
        self.assertEqual([row[1] for row in committed['revisions']], [1, 2])
        self.assertEqual([row[3] for row in committed['messages']], ['user', 'assistant'])
        self.assertEqual(reopened.resume(run), result)
        self.assertEqual(self.case.persisted(run), committed)

    def test_package_conflict_aborts_turn_instead_of_recording_invalid_arguments(self):
        runtime = self.case.runtime
        run = self.case.start()
        runtime.resume(run, max_steps=2)
        before = self.case.persisted(run)
        save = runtime.planner.catalogs.save

        def conflict_after_write(*args, **kwargs):
            save(*args, **kwargs)
            raise PackageConflict('Authored placement conflict')

        with patch.object(runtime.planner.catalogs, 'save', side_effect=conflict_after_write):
            with self.assertRaisesRegex(PackageConflict, 'Authored placement conflict'):
                runtime.resume(run, max_steps=1)
        failed = self.case.persisted(run)
        for key in ('revisions', 'steps', 'status', 'job', 'messages'):
            self.assertEqual(failed[key], before[key], key)
        self.assertEqual(failed['turns'][-1][1], 'received')
        self.assertEqual(runtime.resume(run, max_steps=1)['result']['revision'], 2)

    def test_lost_commit_acknowledgement_replays_committed_result_without_writing_again(self):
        from campaign_agent.adapters.sqlite_planner import _PlacementCommitUnit
        runtime = self.case.runtime
        run = self.case.start()
        runtime.resume(run, max_steps=2)
        commit = _PlacementCommitUnit.commit

        def acknowledged_late(unit):
            commit(unit)
            raise sqlite3.OperationalError('Authored lost commit acknowledgement')

        with patch.object(_PlacementCommitUnit, 'commit', new=acknowledged_late):
            with self.assertRaises(sqlite3.OperationalError):
                runtime.resume(run, max_steps=1)
        committed = self.case.persisted(run)
        self.assertEqual(committed['status'], 'ready_for_review')
        self.assertEqual([row[1] for row in committed['revisions']], [1, 2])
        self.assertEqual(len(committed['steps']), 3)
        self.assertEqual([row[3] for row in committed['messages']], ['user', 'assistant'])
        reopened = self.case.reopen(planner_simulator=Mock(next_turn=Mock(side_effect=AssertionError('No reinference'))))
        with patch.object(reopened.planner.placement_commit_storage, 'write', side_effect=AssertionError('No repeated write')):
            result = reopened.resume(run)
        self.assertEqual(result['result']['revision'], 2)
        self.assertEqual(self.case.persisted(run), committed)

    def test_detached_foreground_origin_receipt_keeps_legacy_commit_route(self):
        runtime = self.case.runtime
        run = self.case.start()
        runtime.resume(run, max_steps=2)
        with patch.object(runtime.planner, '_commit_turn', side_effect=sqlite3.OperationalError('Interrupt before commit')):
            with self.assertRaises(sqlite3.OperationalError):
                runtime.resume(run, max_steps=1)
        # Authored persisted foreground-origin marker; receipt has already been captured.
        with sqlite3.connect(self.case.path) as db:
            source = json.loads(db.execute('SELECT snapshot FROM planner_jobs WHERE run_id=?', (run,)).fetchone()[0])
            source['settings']['foreground'] = True
            db.execute('UPDATE planner_jobs SET snapshot=? WHERE run_id=?', (json.dumps(source), run))
            db.execute('UPDATE planner_sessions SET settings=? WHERE id=?',
                       (json.dumps(source['settings']), self.case.session))
        reopened = self.case.reopen()
        self.assertIsNone(reopened.foreground)
        with patch.object(reopened.planner.placement_commit_storage, 'write', side_effect=AssertionError('Foreground route changed')):
            result = reopened.resume(run, max_steps=1)
        self.assertEqual(result['result']['revision'], 2)
        self.assertEqual(self.case.persisted(run)['turns'][-1][1], 'received')
