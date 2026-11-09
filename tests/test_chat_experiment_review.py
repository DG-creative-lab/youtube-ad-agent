from contextlib import closing
import json
import os
import sqlite3
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from campaign_agent.agent.planning_models import SimulatedPlanner
from campaign_agent.agent.run import AgentRuntime
import test_instruction_tests as experiment_fixtures
import test_placement_planner as planner_fixtures


REQUEST = 'Review the running instruction experiment and prepare the next test if eligible.'
CHOICES = {'playback': 'both_in_full', 'focus': 'delivery', 'choice': 'scene_fit'}


class ChatExperimentReviewTests(unittest.TestCase):
    def setUp(self):
        self.case = experiment_fixtures.InstructionTestTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.runtime = self.case.runtime
        self.session = uuid4().hex
        self.catalog = self.runtime.planner.catalogs.register('Authored catalog', planner_fixtures.CATALOG)

    def reopen(self, **options):
        return AgentRuntime(self.case.path, media_dir=self.case.media, **options)

    def start(self, text=REQUEST, *, permission='none', runtime=None, model='simulated', after=None):
        return (runtime or self.runtime).planner.start(text, model, self.session, uuid4().hex, self.catalog,
                                                       after_message=after, draft_permission=permission)

    def finish(self, run_id, runtime=None):
        return planner_fixtures.PlacementPlannerTests.finish(self, run_id, runtime or self.runtime)

    def observe(self, revised_count=20):
        for arm, arrivals, completions in (('original', 20, 4), ('revised', revised_count, 2)):
            for index in range(arrivals):
                visit = self.case.open(arm)
                if index < completions:
                    self.case.complete(visit)

    def test_campaign_performance_review_while_experiment_is_running(self):
        self.case.start()
        for request in ('Review campaign performance only.',
                        'Review campaign performance while the experiment runs. Do not create a draft.'):
            with self.subTest(request=request):
                result = self.finish(self.start(request))
                self.assertIn('review_performance', [step['tool'] for step in result['steps']])
                self.assertEqual(result['status'], 'answered')
                review = result['result']['performance_review']
                self.assertEqual(review['revision'], 3)
                self.assertEqual(review['sample_delivery']['source'], 'Authored fictional delivery')
                self.assertNotIn('experiment_review', result['result'])
        self.assertIsNone(self.case.read()['review'])
        self.assertIsNone(self.runtime.drafts.read(4))

    def test_chat_waits_then_assesses_and_drafts_from_the_approved_revised_version(self):
        missing = self.finish(self.start('How is the instruction test doing?'))
        self.assertEqual(missing['result']['reply_code'], 'approval_required')
        self.runtime.drafts.approve_package(self.case.campaign, 3, self.case.fingerprint)
        unstarted = self.finish(self.start('How is the instruction test doing?'))
        self.assertEqual(unstarted['result']['reply_code'], 'experiment_unavailable')
        self.assertIsNone(self.case.read())
        test = self.case.start()
        self.observe(revised_count=19)
        # A normal comparison visit must not count toward the missing assigned visit.
        self.case.viewer.open_example(test['creative_version'], content_fingerprint=test['versions'][1]['content_fingerprint'])
        waiting = self.finish(self.start('Review campaign performance and prepare the next test if eligible.',
                                         permission='instruction_test'))
        captured = waiting['result']['experiment_review']
        self.assertEqual(waiting['status'], 'waiting_for_evidence')
        self.assertEqual(captured['assessment']['kind'], 'insufficient_evidence')
        self.assertEqual([row['arrivals'] for row in captured['evidence']['rows']], [20, 19])
        self.assertIsNone(self.runtime.drafts.read(4))

        self.case.open('revised')
        reviewed = self.finish(self.start('How is the instruction test doing?'))
        self.assertEqual(reviewed['status'], 'answered')
        self.assertEqual(reviewed['result']['experiment_review']['id'], self.case.read()['review']['id'])
        self.assertIsNone(self.runtime.drafts.read(4))
        latest = self.runtime.planner.conversations.read(self.session)['latest_message']
        run_id = self.start('Prepare it.', permission='instruction_test', after=latest)
        prepared = self.finish(run_id)
        self.assertEqual(prepared['status'], 'ready_for_review')
        self.assertEqual(prepared['result']['revision'], 4)
        review = prepared['result']['experiment_review']
        self.assertEqual([(row['arrivals'], row['completions']) for row in review['evidence']['rows']], [(20, 4), (20, 2)])
        reopened = self.reopen()
        self.assertEqual(reopened.resume(run_id), prepared)
        draft = reopened.drafts.read()
        instruction = draft['instruction_test']
        self.assertEqual(instruction['source_test_id'], test['id'])
        self.assertEqual(instruction['review_id'], review['id'])
        self.assertEqual(instruction['correction'], review['evidence']['correction'])
        self.assertEqual(instruction['before'], test['versions'][1]['content']['instruction'])
        self.assertNotEqual(instruction['before'], instruction['after'])
        self.assertIsNone(reopened.drafts.review_package(self.case.campaign, 4)['approval'])
        self.assertIsNone(reopened.drafts.read(5))
        chat = reopened.planner.conversations.read(self.session)
        self.assertEqual(chat['messages'][-1]['experiment_review'], review)
        self.assertIn(captured, [message.get('experiment_review') for message in chat['messages']])
        self.assertEqual(self.case.read()['id'], test['id'])
        followup = self.start('Summarize the campaign.', runtime=reopened)
        with closing(sqlite3.connect(self.case.path)) as db:
            source = json.loads(db.execute('SELECT snapshot FROM planner_jobs WHERE run_id=?', (followup,)).fetchone()[0])
        self.assertEqual(source['conversation'][-1]['experiment_review_id'], review['id'])
        self.assertNotIn('experiment_review', source['conversation'][-1])

    def test_fake_model_cannot_supply_assessment_claims_or_draft_without_permission(self):
        self.case.start()
        self.observe()
        replies = planner_fixtures.PlacementPlannerTests()
        calls = iter([
            ('load_experiment_evidence', {'test_id': uuid4().hex}),
            ('load_experiment_evidence', {}),
            ('assess_instruction_experiment', {'reason_code': 'revised_not_higher', 'reason': '500 completions'}),
            ('assess_instruction_experiment', {'reason_code': 'revised_not_higher'}),
            ('prepare_next_test', CHOICES),
        ])
        def transport(request, **kwargs):
            tools = json.loads(request.data)['tools']
            self.assertNotIn('prepare_next_test', [tool['function']['name'] for tool in tools])
            return replies.reply(*next(calls))

        runtime = self.reopen(main_models=(planner_fixtures.MODEL,), main_transport=transport)
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'authored-key'}):
            run_id = self.start('Review only. Do not save a draft.', runtime=runtime, model=planner_fixtures.MODEL)
            result = self.finish(run_id, runtime)
        self.assertIn('error', result['steps'][0]['result'])
        self.assertIn('error', result['steps'][2]['result'])
        self.assertEqual(result['result']['reply_code'], 'instruction_draft_not_authorized')
        review = self.case.read()['review']
        self.assertEqual(review['assessment']['kind'], 'prepare_another_test')
        self.assertNotIn('500 completions', review['assessment']['reason'])
        self.assertIsNone(runtime.drafts.read(4))

    def test_late_viewer_event_blocks_followup_and_retains_captured_assessment(self):
        self.case.start()
        self.observe()
        simulator = Mock(wraps=SimulatedPlanner())
        runtime = self.reopen(planner_simulator=simulator)
        run_id = self.start(permission='instruction_test', runtime=runtime)
        runtime.resume(run_id, max_steps=3)
        review_id = self.case.read()['review']['id']

        def late_event(context, history, settings):
            self.case.open('revised')
            return SimulatedPlanner().next_turn(context, history, settings)

        simulator.next_turn.side_effect = late_event
        result = runtime.resume(run_id)
        self.assertEqual(result['result']['reply_code'], 'experiment_refresh_required')
        self.assertTrue(self.case.read()['needs_review'])
        self.assertIsNone(runtime.drafts.read(4))
        message = runtime.planner.conversations.read(self.session)['messages'][-1]
        self.assertEqual(message['experiment_review']['id'], review_id)
        self.assertTrue(message['review_needs_refresh'])

        report = self.runtime.performance.review(self.case.campaign, 3, self.case.fingerprint, 'balanced')
        correction = self.runtime.performance.save_correction(
            self.case.campaign, 3, self.case.fingerprint, report['id'], 'keep_comparison', '', uuid4().hex,
        )
        waiting = self.finish(self.start(permission='instruction_test'))
        self.assertEqual(waiting['status'], 'waiting_for_evidence')
        self.assertEqual(waiting['result']['experiment_review']['evidence']['correction'], correction)
        self.assertIsNone(self.runtime.drafts.read(4))
