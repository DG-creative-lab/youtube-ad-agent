"""Acceptance of the explicit local planner root through the full selected UOW."""
from contextlib import closing, contextmanager
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from campaign_agent.access import LOCAL_CONTEXT, LOCAL_OPERATOR
from campaign_agent.adapters.local_placement_authority import LocalPlacementAuthority
from campaign_agent.agent.planning_models import SimulatedPlanner
from campaign_agent.agent.run import AgentRuntime as Runtime
from campaign_agent.bootstrap.runtime import create_runtime as AgentRuntime
from campaign_agent.bootstrap.planner import create_local_planner
from campaign_agent.creatives import EXAMPLES
from campaign_agent.domain.errors import PackageConflict
from campaign_agent.domain.inference_errors import ReviewInferenceError
from campaign_agent.placement_discovery import SimulatedClassifier
from campaign_agent.ports.access import AccessUnavailable
from campaign_agent.ports.storage_errors import StorageError, StorageClosed
import test_placement_planner as fixtures
from legacy_comparison_examples import LEGACY_EXAMPLES


class PlacementPilotTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.path, self.media = self.directory / 'state.sqlite3', self.directory / 'media'
        self.media.mkdir()
        for example in EXAMPLES:
            for name in {example.preview, *(take[2] for take in example.takes)}:
                (self.media / name).write_bytes(name.encode())
        self.session, self.run = uuid4().hex, uuid4().hex

    def runtime(self, **options):
        return create_local_planner(self.path, media_dir=self.media, **options).planner.placement

    def start(self, runtime, **options):
        catalog = runtime.catalogs.register('Authored catalogue', fixtures.CATALOG)
        return runtime.start('Find placements for the saved campaign.', 'simulated',
                             options.pop('session', self.session), options.pop('run', self.run), catalog,
                             draft_permission=options.pop('draft_permission', 'placements'), **options)

    def records(self):
        with closing(sqlite3.connect(self.path)) as db:
            return {table: db.execute('SELECT * FROM ' + table).fetchall() for table in (
                'campaign_revisions', 'agent_runs', 'agent_steps', 'planner_jobs', 'planner_turns',
                'planner_sessions', 'planner_defaults', 'planner_messages')}

    def unlocked(self):
        with closing(sqlite3.connect(self.path, timeout=0)) as db:
            db.execute('BEGIN IMMEDIATE')
            db.rollback()

    def test_complete_journey_uses_adapter_connections_and_calls_models_outside_locks(self):
        connect = sqlite3.connect
        checks = []
        authority = LocalPlacementAuthority(self.path, clock=__import__('time').time,
                                             monotonic_clock=__import__('time').monotonic)
        issue = authority.issue

        def acquired(*args):
            self.unlocked()
            checks.append('authority')
            return issue(*args)

        authority.issue = acquired
        model = Mock(wraps=SimulatedPlanner())
        actual_model = model.next_turn.side_effect
        model.next_turn.side_effect = lambda *args: (self.unlocked(), SimulatedPlanner().next_turn(*args))[1]
        classifier = Mock(route='simulated_decision')
        classifier.classify.side_effect = lambda *args: (self.unlocked(), SimulatedClassifier().classify(*args))[1]

        def owned_connection(*args, **kwargs):
            caller = sys._getframe(1).f_code.co_filename.replace('\\', '/')
            if '/campaign_agent/' in caller:
                self.assertTrue('/adapters/' in caller or '/bootstrap/' in caller, caller)
            return connect(*args, **kwargs)

        with patch('sqlite3.connect', side_effect=owned_connection), \
             patch('campaign_agent.access.CommandAccess.decide', side_effect=AssertionError('Secondary authority reader')):
            runtime = self.runtime(authority=authority, simulator=model, classifier=classifier)
            run = self.start(runtime)
            result = runtime.resume(run)
            self.assertEqual(result['status'], 'ready_for_review')
            self.assertEqual(result['result']['revision'], 2)
            self.assertEqual(len(runtime.conversations.read(self.session)['messages']), 2)
        self.assertEqual(model.next_turn.call_count, 3)
        self.assertEqual(classifier.classify.call_count, 1)
        self.assertTrue(checks)

    def test_raw_run_rows_and_seed_fingerprint_match_original_runtime(self):
        native_path = self.directory / 'original.sqlite3'
        old = AgentRuntime(native_path, media_dir=self.media, examples=LEGACY_EXAMPLES)
        current = self.runtime(examples=LEGACY_EXAMPLES)
        for runtime in (old, current):
            catalog = runtime.planner.catalogs.register('Authored catalogue', fixtures.CATALOG)
            runtime.planner.start('Find placements for the saved campaign.', 'simulated', self.session,
                                  self.run, catalog, draft_permission='placements')
            runtime.resume(self.run)
        # This seed fingerprint was calculated from the pre-migration handoff code.
        with closing(sqlite3.connect(self.path)) as db:
            source = json.loads(db.execute('SELECT snapshot FROM planner_jobs').fetchone()[0])
            self.assertEqual(source['fingerprint'], '970f60016d2801f9b5d2b7140868bce8c570b5dd1f16bbd771864042cadc47ee')
        with closing(sqlite3.connect(native_path)) as original:
            for table, rows in self.records().items():
                expected = original.execute('SELECT * FROM ' + table).fetchall()
                if table == 'planner_messages':
                    rows = [row[:-1] for row in rows]
                    expected = [row[:-1] for row in expected]
                self.assertEqual(rows, expected, table)
        # A legacy runtime can still read the adopted run without a history rewrite.
        self.assertEqual(AgentRuntime(self.path, media_dir=self.media, examples=LEGACY_EXAMPLES).read(self.run), current.read(self.run))

    def test_failed_followup_rolls_back_supersession_and_new_message_together(self):
        runtime = self.runtime()
        self.start(runtime)
        runtime.resume(self.run, max_steps=2)
        before = self.records()
        new_run = uuid4().hex
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_followup BEFORE INSERT ON planner_messages "
                       "WHEN NEW.role='user' AND NEW.run_id='" + new_run + "' "
                       "BEGIN SELECT RAISE(ABORT, 'Authored followup failure'); END")
        catalog = runtime.catalogs.list()[0]['id']
        latest = runtime.conversations.read(self.session)['latest_message']
        with self.assertRaises(StorageError) as caught:
            runtime.start('More placements', 'simulated', self.session, new_run, catalog,
                          after_message=latest, draft_permission='placements')
        self.assertEqual(caught.exception.kind, 'conflict')
        self.assertEqual(self.records(), before)
        self.assertEqual(runtime.resume(self.run)['status'], 'ready_for_review')

    def test_failed_final_reply_keeps_received_receipt_and_recovers_without_reinference(self):
        model, classifier = Mock(wraps=SimulatedPlanner()), Mock(route='simulated_decision', wraps=SimulatedClassifier())
        runtime = self.runtime(simulator=model, classifier=classifier)
        self.start(runtime)
        runtime.resume(self.run, max_steps=2)
        before = self.records()
        finish = runtime.conversations.finish

        def interrupted(*args):
            finish(*args)
            raise StorageError('invalid', 'Authored interrupted terminal message')

        with patch.object(runtime.conversations, 'finish', side_effect=interrupted):
            with self.assertRaises(StorageError):
                runtime.resume(self.run, max_steps=1)
        failed = self.records()
        for table in before:
            if table != 'planner_turns':
                self.assertEqual(failed[table], before[table], table)
        self.assertEqual(failed['planner_turns'][-1][2], 'received')
        self.assertEqual(model.next_turn.call_count, 3)
        self.assertEqual(classifier.classify.call_count, 1)
        reopened = self.runtime(simulator=Mock(next_turn=Mock(side_effect=AssertionError('No model retry'))),
                                classifier=Mock(classify=Mock(side_effect=AssertionError('No classifier retry'))))
        result = reopened.resume(self.run)
        self.assertEqual(result['result']['revision'], 2)
        committed = self.records()
        self.assertEqual(reopened.resume(self.run), result)
        self.assertEqual(self.records(), committed)

    def test_native_receipt_write_failure_remains_requested_and_does_not_repeat(self):
        model = Mock(wraps=SimulatedPlanner())
        runtime = self.runtime(simulator=model)
        self.start(runtime)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_receipt BEFORE UPDATE OF receipt ON planner_turns "
                       "WHEN NEW.receipt IS NOT NULL BEGIN SELECT RAISE(ABORT,'private SQL detail'); END")
        with self.assertRaises(StorageError) as caught:
            runtime.resume(self.run, max_steps=1)
        self.assertNotIn('private SQL detail', str(caught.exception))
        self.assertEqual(self.records()['planner_turns'][0][2:], ('requested', None, None))
        with self.assertRaises(ReviewInferenceError):
            self.runtime(simulator=model).resume(self.run, max_steps=1)
        self.assertEqual(model.next_turn.call_count, 1)

    def test_native_classifier_receipt_failure_does_not_repeat_classification(self):
        classifier = Mock(route='simulated_decision', wraps=SimulatedClassifier())
        runtime = self.runtime(classifier=classifier)
        self.start(runtime)
        runtime.resume(self.run, max_steps=1)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_classification BEFORE UPDATE OF classification ON planner_jobs "
                       "WHEN NEW.classification IS NOT NULL BEGIN SELECT RAISE(ABORT,'Authored failure'); END")
        with self.assertRaises(StorageError):
            runtime.resume(self.run, max_steps=1)
        with self.assertRaises(ReviewInferenceError):
            runtime.resume(self.run, max_steps=1)
        self.assertEqual(classifier.classify.call_count, 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT classification_state FROM planner_jobs').fetchone(), ('requested',))

    def test_expired_original_permit_rolls_back_postimage_and_later_new_decision_recovers(self):
        clock = {'wall': 1000., 'mono': 100.}
        runtime = self.runtime(clock=lambda: clock['wall'], monotonic_clock=lambda: clock['mono'])
        self.start(runtime)
        runtime.resume(self.run, max_steps=2)
        before = self.records()
        finish = runtime.conversations.finish

        def expires(*args):
            finish(*args)
            clock['wall'] += 6
            clock['mono'] += 6

        with patch.object(runtime.conversations, 'finish', side_effect=expires):
            with self.assertRaises(AccessUnavailable):
                runtime.resume(self.run, max_steps=1)
        after = self.records()
        for table in before:
            if table != 'planner_turns':
                self.assertEqual(after[table], before[table], table)
        self.assertEqual(runtime.resume(self.run)['result']['revision'], 2)

    def test_busy_invalid_and_closed_units_expose_only_core_storage_errors(self):
        runtime = self.runtime()
        with runtime.storage.read() as unit:
            reader = unit.drafts
            self.assertFalse(hasattr(reader, 'connection'))
            self.assertFalse(hasattr(reader, 'execute'))
        with self.assertRaises(StorageClosed):
            reader.owner_row('tts-sample')
        connect = sqlite3.connect
        with closing(connect(self.path)) as blocked:
            blocked.execute('BEGIN IMMEDIATE')
            with patch('sqlite3.connect', side_effect=lambda *args, **kw: connect(*args, **{**kw, 'timeout': 0})):
                with self.assertRaises(StorageError) as caught:
                    with runtime.storage.write():
                        pass
            self.assertEqual(caught.exception.kind, 'busy')
            blocked.rollback()
        with closing(connect(self.path)) as db, db:
            db.execute("UPDATE campaign_revisions SET snapshot='{broken JSON'")
        with self.assertRaises(StorageError) as caught:
            runtime.drafts.read()
        self.assertEqual(caught.exception.kind, 'invalid')

    def test_original_owner_and_command_binding_fences_use_typed_native_preimage(self):
        runtime = self.runtime()
        runtime.access.refresh({'command': 'authored-boundary'})
        with runtime.storage.read() as unit:
            original = unit.drafts.owner_row('tts-sample')
            for index in range(4):
                wrong = list(original)
                wrong[index] = 'foreign'
                with patch.object(unit.drafts, 'owner_row', return_value=tuple(wrong)):
                    with runtime.access.bind(unit.drafts):
                        with self.assertRaises(PermissionError):
                            runtime.require('youtube:campaign.read')
            runtime.access.command = {'command': 'tampered'}
            with runtime.access.bind(unit.drafts):
                with self.assertRaises(PermissionError):
                    runtime.require('youtube:campaign.read')

    def test_existing_runtime_public_commands_and_typed_draft_read(self):
        runtime = create_local_planner(self.path, media_dir=self.media)
        self.assertIsInstance(runtime, Runtime)
        with patch('campaign_agent.agent.planner.PlacementAgent.start', side_effect=AssertionError('Legacy placement start')), \
             patch('campaign_agent.agent.planner.PlacementAgent.resume', side_effect=AssertionError('Legacy placement resume')):
            catalog = runtime.planner.catalogs.register('Authored catalogue', fixtures.CATALOG)
            runtime.planner.start('Find placements for the saved campaign.', 'simulated', self.session,
                                  self.run, catalog, draft_permission='placements')
            result = runtime.resume(self.run)
            self.assertEqual(result['status'], 'ready_for_review')
            self.assertEqual(runtime.drafts.read()['revision'], 2)
            self.assertEqual(runtime.read(self.run), result)

    def test_media_change_between_capture_and_unit_rolls_back_start(self):
        runtime = self.runtime()
        catalog = runtime.catalogs.register('Authored catalogue', fixtures.CATALOG)
        write = runtime.storage.write

        @contextmanager
        def changed_media():
            (self.media / EXAMPLES[0].preview).write_bytes(b'changed after capture')
            with write() as unit:
                yield unit
        with patch.object(runtime.storage, 'write', side_effect=changed_media):
            with self.assertRaises(PackageConflict):
                runtime.start('Find placements', 'simulated', self.session, self.run, catalog)
        self.assertEqual(self.records()['agent_runs'], [])
        self.assertEqual(self.records()['planner_messages'], [])

    def test_new_local_commands_remain_available_after_an_hour(self):
        clock = {'wall': 1000., 'mono': 100.}
        runtime = self.runtime(clock=lambda: clock['wall'], monotonic_clock=lambda: clock['mono'])
        self.assertEqual(runtime.drafts.read()['revision'], 1)
        clock['wall'] += 3601
        clock['mono'] += 3601
        self.assertEqual(runtime.drafts.read()['revision'], 1)
        runtime.access.expires_at = clock['wall'] - 1
        with self.assertRaises(PermissionError):
            runtime.drafts.read()

    def test_concurrent_commands_keep_distinct_permits_and_units(self):
        runtime = self.runtime()
        barrier = Barrier(2)
        read = runtime.storage.read

        @contextmanager
        def overlap():
            with read() as unit:
                barrier.wait(timeout=5)
                yield unit
        with patch.object(runtime.storage, 'read', side_effect=overlap):
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(lambda revision: runtime.drafts.read(revision), [1, None]))
        self.assertEqual([result['revision'] for result in outcomes], [1, 1])

    def test_safe_unit_visibility_savepoint_and_default_rollback(self):
        runtime = self.runtime()
        with runtime.storage.write() as unit:
            original = unit.drafts.read_snapshot('tts-sample')
            with self.assertRaises(ValueError):
                with unit.tool_attempt():
                    unit.drafts.append_snapshot('tts-sample', 2, original)
                    self.assertEqual(unit.drafts.latest_revision_row('tts-sample')[0], 2)
                    raise ValueError('invalid tool after partial write')
            self.assertEqual(unit.drafts.latest_revision_row('tts-sample')[0], 1)
            unit.drafts.append_snapshot('tts-sample', 2, original)
            with runtime.storage.read() as sibling:
                self.assertEqual(sibling.drafts.latest_revision_row('tts-sample')[0], 1)
        self.assertEqual(self.records()['campaign_revisions'][0][1], 1)
        self.assertEqual(len(self.records()['campaign_revisions']), 1)

    def test_lost_commit_ack_reopens_committed_result_without_duplicate_effects(self):
        from campaign_agent.adapters.sqlite_planner import _PlacementCommitUnit
        runtime = self.runtime()
        self.start(runtime)
        runtime.resume(self.run, max_steps=2)
        original = _PlacementCommitUnit.commit

        def late_ack(unit):
            terminal = unit.drafts.latest_revision_row('tts-sample')[0] == 2
            original(unit)
            if terminal:
                raise sqlite3.OperationalError('Authored lost acknowledgement')
        with patch.object(_PlacementCommitUnit, 'commit', new=late_ack):
            with self.assertRaises(StorageError) as caught:
                runtime.resume(self.run, max_steps=1)
        self.assertEqual(caught.exception.kind, 'commit_unknown')
        before = self.records()
        reopened = self.runtime(simulator=Mock(next_turn=Mock(side_effect=AssertionError('No reinference'))))
        result = reopened.read(self.run)
        self.assertEqual(result['result']['revision'], 2)
        self.assertEqual(reopened.resume(self.run), result)
        self.assertEqual(self.records(), before)

    def test_read_and_catalogue_do_not_require_agent_run_grant(self):
        authority = LocalPlacementAuthority(self.path, clock=__import__('time').time,
                                             monotonic_clock=__import__('time').monotonic)
        issue = authority.issue
        def grant(request, *args):
            if request.capability == 'youtube:agent.run':
                raise PermissionError('Agent execution denied')
            return issue(request, *args)
        authority.issue = grant
        runtime = self.runtime(authority=authority)
        self.assertEqual(runtime.drafts.read()['revision'], 1)
        catalog = runtime.catalogs.register('Authored catalogue', fixtures.CATALOG)
        self.assertEqual(len(runtime.catalogs.list()), 1)
        with self.assertRaises(PermissionError):
            runtime.start('Find placements', 'simulated', self.session, self.run, catalog)
        self.assertEqual(self.records()['agent_runs'], [])

    def test_public_cli_runs_the_selected_bootstrap(self):
        catalog = self.directory / 'catalog.json'
        catalog.write_text(json.dumps(fixtures.CATALOG))
        result = subprocess.run([sys.executable, '-B', '-m', 'campaign_agent.bootstrap.planner',
                                 '--store', str(self.path), '--media-dir', str(self.media), 'demo',
                                 '--catalog', str(catalog), '--run-id', self.run, '--session-id', self.session],
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'ready_for_review')
        self.assertNotIn('Traceback', result.stderr)


class MixedReviewJourneyTests(unittest.TestCase):
    def test_existing_review_history_keeps_real_freshness_and_no_reinference(self):
        from test_chat_campaign_review import ChatCampaignReviewTests
        case = ChatCampaignReviewTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.runtime = create_local_planner(case.case.path, media_dir=case.case.media)
        case.ready()
        run = case.start()
        result = case.runtime.resume(run, max_steps=2)
        self.assertEqual([step['tool'] for step in result['steps']], ['read_campaign', 'review_performance'])
        self.assertEqual(result['status'], 'running')
        case.arrive()
        simulator = Mock(next_turn=Mock(side_effect=AssertionError('Stale evidence must stop before inference')))
        reopened = create_local_planner(case.case.path, media_dir=case.case.media, simulator=simulator)
        result = reopened.resume(run)
        self.assertEqual(result['status'], 'needs_input')
        self.assertEqual(result['result']['reply_code'], 'review_refresh_required')
        simulator.next_turn.assert_not_called()

    def test_current_review_and_test_draft_finish_through_same_public_runtime(self):
        from test_chat_campaign_review import ChatCampaignReviewTests
        case = ChatCampaignReviewTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        simulator = Mock(wraps=SimulatedPlanner())
        case.runtime = create_local_planner(case.case.path, media_dir=case.case.media, simulator=simulator)
        correction = case.ready()
        run = case.start()
        result = case.runtime.resume(run, max_steps=3)
        self.assertEqual([step['tool'] for step in result['steps']],
                         ['read_campaign', 'review_performance', 'prepare_next_test'])
        self.assertEqual(result['status'], 'ready_for_review')
        self.assertEqual(result['result']['revision'], 3)
        self.assertEqual(result['result']['performance_review']['proposal']['correction'], correction)
        self.assertEqual(simulator.next_turn.call_count, 3)

    def test_new_placement_after_review_reads_real_correction_and_started_experiment(self):
        from test_chat_experiment_review import ChatExperimentReviewTests
        case = ChatExperimentReviewTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        experiment = case.case.start()
        review_run = case.start('Review campaign performance only.')
        reviewed = case.finish(review_run)
        self.assertEqual(reviewed['status'], 'answered')
        self.assertIn('review_performance', [step['tool'] for step in reviewed['steps']])
        runtime = create_local_planner(case.case.path, media_dir=case.case.media)
        latest = runtime.planner.conversations.read(case.session)['latest_message']
        followup = uuid4().hex
        with patch.object(runtime.planner.legacy, 'start', side_effect=AssertionError('Placement must use typed start')), \
             patch.object(runtime.planner.legacy, 'resume', side_effect=AssertionError('Placement must use typed unit')):
            runtime.planner.start('Find placements for the saved campaign.', 'simulated', case.session,
                                  followup, case.catalog, after_message=latest, draft_permission='placements')
            result = runtime.resume(followup, max_steps=1)
        observed = result['steps'][0]['result']
        self.assertEqual(observed['instruction_test_id'], experiment['id'])
        self.assertEqual(observed['reporting_scenario'], 'balanced')
        self.assertEqual(observed['buyer_corrections'][0]['note'], 'Preserve these readings.')
        with closing(sqlite3.connect(case.case.path)) as db:
            source = json.loads(db.execute('SELECT snapshot FROM planner_jobs WHERE run_id=?', (followup,)).fetchone()[0])
        self.assertEqual(source['fingerprint'], case.case.fingerprint)
        self.assertTrue(any(item.get('review_id') == reviewed['result']['performance_review']['id']
                            for item in source['conversation']))
