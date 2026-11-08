from contextlib import closing
import json
import os
import sqlite3
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import test_placement_planner as fixtures
from campaign_agent.agent.planning_models import SimulatedPlanner
from campaign_agent.creatives import EXAMPLES, render_instruction_choices
from campaign_agent.handoff import package_fingerprint
from scripts.campaign_drafts import PackageConflict


CHOICES = {'playback': 'both_in_full', 'focus': 'delivery', 'choice': 'scene_fit'}
REQUEST = 'Review this campaign performance and prepare the next instruction test if the evidence supports it.'


class ChatCampaignReviewTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.PlacementPlannerTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.runtime = self.case.runtime
        self.case.finish(self.case.start())
        self.package = self.runtime.drafts.review_package('tts-sample', 2)
        self.fingerprint = self.package['fingerprint']

    def approve(self):
        self.runtime.drafts.approve_package('tts-sample', 2, self.fingerprint)

    def arrive(self):
        group = self.package['package']['groups'][0]
        return self.runtime.performance.viewer.open_example(group['creative_version'],
            content_fingerprint=package_fingerprint(group['content']))

    def ready(self, kind='keep_takes'):
        self.approve()
        for _ in range(3):
            self.arrive()
        review = self.runtime.performance.review('tts-sample', 2, self.fingerprint, 'balanced')
        if kind:
            return self.runtime.performance.save_correction('tts-sample', 2, self.fingerprint,
                review['id'], kind, 'Preserve the approved recordings.', uuid4().hex)
        return review

    def start(self, text=REQUEST, runtime=None, run_id=None, after=None, draft_permission='instruction_test'):
        runtime = runtime or self.runtime
        return runtime.planner.start(text, 'simulated', self.case.session, run_id or uuid4().hex,
                                     self.case.catalog, after_message=after, draft_permission=draft_permission)

    def finish(self, run_id, runtime=None):
        return self.case.finish(run_id, runtime or self.runtime)

    def test_chat_prepares_one_unapproved_instruction_test_and_retains_evidence_and_correction(self):
        correction = self.ready()
        before = self.runtime.drafts.read()
        after = self.runtime.planner.conversations.read(self.case.session)['latest_message']
        run_id = self.start(after=after)
        result = self.finish(run_id)
        self.assertEqual([step['tool'] for step in result['steps']],
                         ['read_campaign', 'review_performance', 'prepare_next_test'])
        self.assertEqual(result['status'], 'ready_for_review')
        self.assertEqual(result['result']['revision'], 3)
        evidence = result['result']['performance_review']
        self.assertEqual(evidence['proposal']['correction'], correction)
        self.assertEqual(evidence['local_viewer_activity']['rows'][0]['arrivals'], 3)
        self.assertEqual(evidence['local_viewer_activity']['rows'][0]['completions'], 0)
        self.assertEqual(evidence['sample_delivery']['source'], 'Authored fictional delivery')
        draft = self.runtime.drafts.read()
        self.assertEqual(draft['placements'], before['placements'])
        self.assertEqual(draft['instruction_test']['before'], self.package['package']['groups'][0]['content']['instruction'])
        self.assertEqual(draft['instruction_test']['after'], render_instruction_choices(CHOICES))
        self.assertEqual(draft['instruction_test']['review_id'], evidence['id'])
        self.assertEqual(draft['instruction_test']['correction'], correction)
        self.assertEqual(draft['instruction_test']['inference']['usage'], {'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0})
        self.assertEqual(draft['instruction_test']['inference']['prompt_version'], 'campaign-planner-simulated-v1')
        self.assertEqual(self.runtime.drafts.read(2), before)
        self.assertIsNone(self.runtime.drafts.review_package('tts-sample', 3)['approval'])
        reopened = self.case.reopen()
        self.assertEqual(self.start(run_id=run_id, after=after, runtime=reopened), run_id)
        self.assertEqual(reopened.resume(run_id), result)
        message = reopened.planner.conversations.read(self.case.session)['messages'][-1]
        self.assertEqual(message['review']['id'], evidence['id'])
        self.assertEqual(message['revision'], 3)
        self.assertIsNone(reopened.drafts.read(4))
        followup = self.start('What have we saved?')
        with closing(sqlite3.connect(self.case.path)) as db:
            source = json.loads(db.execute('SELECT snapshot FROM planner_jobs WHERE run_id=?', (followup,)).fetchone()[0])
        self.assertEqual(source['conversation'][-1]['review_id'], evidence['id'])
        self.assertTrue(all('review' not in item for item in source['conversation']))
        self.assertEqual(self.finish(followup)['result']['revision'], 3)

    def test_review_only_request_cannot_be_turned_into_a_draft_by_the_provider(self):
        self.ready()
        calls = [('read_campaign', {}), ('review_performance', {}), ('prepare_next_test', CHOICES)]
        requests = []
        def transport(request, **kwargs):
            requests.append(json.loads(request.data))
            return self.case.reply(*calls.pop(0))
        runtime = self.case.reopen(main_models=[fixtures.MODEL], main_transport=transport)
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'authored-key'}):
            run_id = runtime.planner.start('Review campaign performance only; do not create a draft.',
                fixtures.MODEL, uuid4().hex, uuid4().hex, self.case.catalog)
            with patch.object(runtime.performance, 'save_instruction_test', wraps=runtime.performance.save_instruction_test) as save:
                result = self.finish(run_id, runtime)
                save.assert_not_called()
        self.assertEqual(result['status'], 'needs_input')
        self.assertEqual(result['result']['reply_code'], 'instruction_draft_not_authorized')
        self.assertEqual(runtime.drafts.read()['revision'], 2)
        self.assertNotIn('prepare_next_test', [item['function']['name'] for item in requests[-1]['tools']])

    def test_draft_authority_is_pinned_to_one_request_and_cannot_escalate_on_retry(self):
        self.ready()
        run_id = self.start(draft_permission='none')
        with self.assertRaisesRegex(ValueError, 'different draft authority'):
            self.start(run_id=run_id, draft_permission='instruction_test')
        self.assertEqual(self.start(run_id=run_id, draft_permission='none'), run_id)
        self.assertEqual(self.finish(run_id)['result']['reply_code'], 'instruction_draft_not_authorized')
        allowed = self.start('Review campaign performance.', draft_permission='instruction_test')
        self.assertEqual(self.finish(allowed)['status'], 'answered')
        followup = self.runtime.planner.start('Prepare it.', 'simulated', self.case.session,
                                              uuid4().hex, self.case.catalog)
        denied = self.finish(followup)
        self.assertEqual(denied['planner']['draft_permission'], 'none')
        self.assertEqual(denied['result']['reply_code'], 'instruction_draft_not_authorized')
        self.assertEqual(self.runtime.drafts.read()['revision'], 2)
        for invalid in (True, None, [], 'all'):
            with self.subTest(permission=invalid), self.assertRaisesRegex(ValueError, 'valid draft permission'):
                self.start(draft_permission=invalid)

    def test_legacy_received_preparation_cannot_resume_without_saved_authority(self):
        self.ready()
        run_id = self.start()
        self.runtime.resume(run_id, max_steps=2)
        # A model receipt survived an interrupted tool commit before authority was stored.
        receipt = {'call_id': 'cached-prepare', 'tool': 'prepare_next_test', 'arguments': CHOICES}
        with closing(sqlite3.connect(self.case.path)) as db, db:
            source = json.loads(db.execute('SELECT snapshot FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone()[0])
            del source['draft_permission']
            db.execute('UPDATE planner_jobs SET snapshot=? WHERE run_id=?', (json.dumps(source), run_id))
            db.execute("INSERT INTO planner_turns VALUES(?,2,'received',?,NULL)", (run_id, json.dumps(receipt)))
        simulator = Mock()
        simulator.next_turn.side_effect = AssertionError('Must reuse the saved receipt')
        reopened = self.case.reopen(planner_simulator=simulator)
        with patch.object(reopened.performance, 'save_instruction_test') as save:
            result = reopened.resume(run_id)
            save.assert_not_called()
        simulator.next_turn.assert_not_called()
        self.assertEqual(result['result']['reply_code'], 'instruction_draft_not_authorized')
        self.assertEqual(reopened.drafts.read()['revision'], 2)

    def test_review_and_instruction_permissions_cannot_save_placement_drafts(self):
        for permission in ('none', 'instruction_test'):
            with self.subTest(permission=permission):
                simulator = Mock()
                simulator.next_turn.return_value = {'call_id': 'wrong-write', 'tool': 'save_placement_draft',
                                                    'arguments': {'contexts': ['audiobook']}}
                runtime = self.case.reopen(planner_simulator=simulator)
                run_id = self.start(runtime=runtime, draft_permission=permission)
                with patch.object(runtime.planner.catalogs, 'save') as save:
                    result = runtime.resume(run_id)
                    save.assert_not_called()
                self.assertEqual(result['result']['reply_code'], 'placement_draft_not_authorized')
                self.assertEqual(runtime.drafts.read()['revision'], 2)

    def test_review_only_and_missing_or_fixed_correction_never_draft(self):
        review = self.ready(kind=None)
        missing = self.finish(self.start())
        self.assertEqual(missing['status'], 'needs_input')
        self.assertEqual(missing['result']['reply_code'], 'correction_required')
        self.runtime.performance.save_correction('tts-sample', 2, self.fingerprint, review['id'],
                                                'keep_comparison', '', uuid4().hex)
        fixed = self.finish(self.start())
        self.assertEqual(fixed['result']['reply_code'], 'comparison_fixed')
        self.runtime.performance.save_correction('tts-sample', 2, self.fingerprint, review['id'],
                                                'keep_takes', '', uuid4().hex)
        read_only = self.finish(self.start('Review campaign performance.', draft_permission='none'))
        self.assertEqual(read_only['status'], 'answered')
        self.assertNotIn('prepare_next_test', [step['tool'] for step in read_only['steps']])
        self.assertEqual(read_only['result']['reply_code'], 'performance_review')
        self.assertEqual(self.runtime.drafts.read()['revision'], 2)
        prepared = self.finish(self.start('Prepare it.'))
        self.assertEqual(prepared['status'], 'ready_for_review')
        self.assertEqual(prepared['result']['revision'], 3)

    def test_missing_approval_blocks_capture_and_insufficient_or_partial_evidence_waits(self):
        with patch.object(self.runtime.performance, 'capture_review', wraps=self.runtime.performance.capture_review) as capture:
            blocked = self.finish(self.start())
            capture.assert_not_called()
        self.assertEqual(blocked['result']['reply_code'], 'approval_required')
        self.approve()
        waiting = self.finish(self.start())
        self.assertEqual(waiting['status'], 'waiting_for_evidence')
        self.assertEqual(waiting['result']['performance_review']['proposal']['kind'], 'collect_activity')
        self.runtime.performance.review('tts-sample', 2, self.fingerprint, 'limited')
        limited = self.finish(self.start())
        self.assertEqual(limited['status'], 'waiting_for_evidence')
        self.assertEqual(limited['result']['performance_review']['sample_delivery']['scenario'], 'limited')
        self.assertEqual(limited['result']['performance_review']['sample_delivery']['coverage'], 'partial')
        self.assertIn('35 impressions', limited['result']['message'])
        self.assertIsNone(self.runtime.drafts.read(3))

    def test_older_pending_run_without_review_context_requires_a_new_request(self):
        self.approve()
        run_id = self.start()
        with closing(sqlite3.connect(self.case.path)) as db, db:
            source = json.loads(db.execute('SELECT snapshot FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone()[0])
            del source['fingerprint']
            del source['reporting_scenario']
            db.execute('UPDATE planner_jobs SET snapshot=? WHERE run_id=?', (json.dumps(source), run_id))
        with self.assertRaisesRegex(PackageConflict, 'Start a new chat request'):
            self.runtime.resume(run_id, max_steps=2)
        self.assertIsNone(self.runtime.drafts.read(3))

    def test_stale_viewer_activity_stops_before_another_inference_and_can_be_reviewed_again(self):
        self.ready()
        run_id = self.start()
        self.runtime.resume(run_id, max_steps=2)
        self.arrive()
        simulator = Mock(wraps=SimulatedPlanner())
        reopened = self.case.reopen(planner_simulator=simulator)
        stale = reopened.resume(run_id)
        simulator.next_turn.assert_not_called()
        self.assertEqual(stale['result']['reply_code'], 'review_refresh_required')
        self.assertEqual(stale['status'], 'needs_input')
        self.assertTrue(reopened.planner.conversations.read(self.case.session)['messages'][-1]['review_needs_refresh'])
        self.assertIsNone(reopened.drafts.read(3))
        fresh = self.finish(self.start())
        self.assertEqual(fresh['result']['performance_review']['local_viewer_activity']['rows'][0]['arrivals'], 4)
        self.assertEqual(fresh['status'], 'ready_for_review')

    def test_started_experiment_requires_its_assigned_arm_review_before_another_draft(self):
        self.ready()
        self.finish(self.start())
        package = self.runtime.drafts.review_package('tts-sample', 3)
        self.runtime.drafts.approve_package('tts-sample', 3, package['fingerprint'])
        experiment = self.runtime.instruction_tests.start('tts-sample', 3, package['fingerprint'])
        result = self.finish(self.start())
        self.assertEqual(result['result']['reply_code'], 'experiment_review_required')
        self.assertEqual(result['result']['performance_review']['instruction_test_id'], experiment['id'])
        self.assertIsNone(self.runtime.drafts.read(4))

    def test_superseded_review_request_cannot_commit_a_late_test(self):
        self.ready()
        simulator = Mock(wraps=SimulatedPlanner())
        runtime = self.case.reopen(planner_simulator=simulator)
        run_id = self.start(runtime=runtime)
        runtime.resume(run_id, max_steps=2)
        replacement = uuid4().hex
        def late(context, history, settings):
            self.start('What have we saved?', run_id=replacement)
            return SimulatedPlanner().next_turn(context, history, settings)
        simulator.next_turn.side_effect = late
        result = runtime.resume(run_id)
        self.assertEqual(result['status'], 'superseded')
        self.assertEqual(self.finish(replacement)['result']['revision'], 2)
        self.assertIsNone(runtime.drafts.read(3))

    def test_late_correction_and_media_changes_keep_receipt_but_cannot_save_a_test(self):
        self.ready()
        for change in ('correction', 'media'):
            with self.subTest(change=change):
                simulator = Mock(wraps=SimulatedPlanner())
                runtime = self.case.reopen(planner_simulator=simulator)
                run_id = self.start(runtime=runtime)
                runtime.resume(run_id, max_steps=2)
                source = runtime.read(run_id)['steps'][-1]['result']
                original = (self.case.media / EXAMPLES[0].takes[1][2]).read_bytes()
                def late(context, history, settings):
                    if change == 'correction':
                        runtime.performance.save_correction('tts-sample', 2, self.fingerprint, source['id'],
                                                            'keep_comparison', '', uuid4().hex)
                    else:
                        (self.case.media / EXAMPLES[0].takes[1][2]).write_bytes(b'Changed content')
                    return SimulatedPlanner().next_turn(context, history, settings)
                simulator.next_turn.side_effect = late
                result = runtime.resume(run_id)
                self.assertEqual(result['result']['reply_code'], 'review_refresh_required')
                self.assertEqual(result['planner']['turns'][-1]['state'], 'received')
                self.assertIsNone(runtime.drafts.read(3))
                (self.case.media / EXAMPLES[0].takes[1][2]).write_bytes(original)
                runtime.performance.save_correction('tts-sample', 2, self.fingerprint, source['id'],
                                                    'keep_takes', '', uuid4().hex)

    def test_test_draft_and_reply_rollback_together_and_resume_reuses_inference(self):
        self.ready()
        simulator = Mock(wraps=SimulatedPlanner())
        runtime = self.case.reopen(planner_simulator=simulator)
        run_id = self.start(runtime=runtime)
        runtime.resume(run_id, max_steps=2)
        finish = runtime.planner.conversations.finish
        def interrupted(*args):
            finish(*args)
            raise sqlite3.OperationalError('Lost commit')
        with patch.object(runtime.planner.conversations, 'finish', side_effect=interrupted):
            with self.assertRaises(sqlite3.OperationalError):
                runtime.resume(run_id)
        self.assertEqual(runtime.drafts.read()['revision'], 2)
        self.assertEqual(runtime.read(run_id)['status'], 'running')
        no_model = Mock()
        no_model.next_turn.side_effect = AssertionError('No new model')
        reopened = self.case.reopen(planner_simulator=no_model)
        result = reopened.resume(run_id)
        self.assertEqual(result['status'], 'ready_for_review')
        self.assertEqual(simulator.next_turn.call_count, 3)
        no_model.next_turn.assert_not_called()
        self.assertIsNone(reopened.drafts.read(4))
        self.assertEqual(reopened.planner.conversations.read(self.case.session)['messages'][-1]['kind'], 'ready_for_review')

    def test_fake_openrouter_uses_real_evidence_and_rejects_invented_review_references(self):
        correction = self.ready()
        calls = [('read_campaign', {}), ('review_performance', {}),
                 ('prepare_next_test', {**CHOICES, 'review_id': 'f' * 64}), ('prepare_next_test', CHOICES)]
        requests = []
        def transport(request, **kwargs):
            requests.append(json.loads(request.data))
            return self.case.reply(*calls.pop(0))
        runtime = self.case.reopen(main_models=[fixtures.MODEL], main_transport=transport)
        session = uuid4().hex
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'authored-key'}):
            run_id = runtime.planner.start(REQUEST, fixtures.MODEL, session, uuid4().hex, self.case.catalog,
                                           after_message=0, draft_permission='instruction_test')
            result = self.finish(run_id, runtime)
        self.assertEqual(len(requests), 4)
        self.assertIn('error', result['steps'][2]['result'])
        self.assertEqual(result['status'], 'ready_for_review')
        observations = [json.loads(message['content']) for message in requests[-1]['messages'] if message['role'] == 'tool']
        reviewed = next(item for item in observations if 'preparation' in item)
        self.assertEqual(reviewed['proposal']['correction'], correction)
        self.assertEqual(reviewed['local_viewer_activity']['rows'][0]['arrivals'], 3)
        self.assertEqual(reviewed['preparation']['instruction_components']['playback']['both_in_full'], 'Play both takes in full.')
        draft = runtime.drafts.read()
        self.assertEqual(draft['instruction_test']['inference']['wording_choices'], CHOICES)
        self.assertEqual(draft['instruction_test']['inference']['mode'], 'openrouter')
        self.assertNotIn('authored-key', json.dumps(draft))
