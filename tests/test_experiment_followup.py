from contextlib import closing
import io
import json
import os
import sqlite3
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from campaign_agent.agent.run import AgentRuntime
from campaign_agent.access import LOCAL_BRAND, Operator
from campaign_agent.handoff import package_fingerprint
from scripts.campaign_drafts import PackageConflict
import test_instruction_tests as fixtures


MODEL = 'example/drafter:free'
CHOICES = {'playback': 'both_in_full', 'focus': 'delivery', 'choice': 'scene_fit'}


class ExperimentFollowupTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.InstructionTestTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.start()
        self.runtime = self.case.runtime
        self.test_id = self.case.test['id']
        self.transport = Mock(side_effect=lambda *_args, **_kwargs: io.BytesIO(json.dumps({
            'id': 'gen-authored-followup', 'model': MODEL,
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(CHOICES)}}],
            'usage': {'prompt_tokens': 200, 'completion_tokens': 30, 'cost': 0},
        }).encode()))

    def reopen(self):
        return AgentRuntime(self.case.path, media_dir=self.case.media,
                            openrouter_draft_models=(MODEL,), draft_transport=self.transport)

    def assess(self):
        self.runtime.resume(self.runtime.start_instruction_review(self.test_id, operation_id=uuid4().hex))
        return self.case.read()['review']

    def eligible(self):
        for arm, completions in (('original', 4), ('revised', 2)):
            for index in range(20):
                visit = self.case.open(arm)
                if index < completions:
                    self.case.complete(visit)
        return self.assess()

    def start(self, review, runtime=None, **options):
        return (runtime or self.runtime).start_experiment_next_test(self.test_id, review['id'], **options)

    def test_insufficient_evidence_waits_durably_without_draft_or_inference(self):
        review = self.assess()
        self.assertEqual(review['assessment']['kind'], 'insufficient_evidence')
        with patch.object(self.runtime.model, 'revise_instructions', side_effect=AssertionError('Must not draft')):
            run_id = self.start(review)
            result = self.runtime.resume(run_id)
        self.assertEqual(result['status'], 'waiting_for_evidence')
        self.assertEqual([step['tool'] for step in result['steps']], ['load_test_context', 'wait_for_evidence'])
        self.assertEqual(result['steps'][-1]['result']['outcome'], 'waiting')
        self.assertIsNone(self.case.drafts.read(4))
        self.assertEqual(self.start(review), run_id)
        self.assertEqual(self.reopen().resume(run_id), result)
        # Selecting a configured provider must still make zero requests, even without a key.
        remote = self.reopen()
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': ''}):
            run = self.start(review, remote, mode='openrouter', model=MODEL, operation_id=uuid4().hex)
            self.assertEqual(remote.resume(run)['status'], 'waiting_for_evidence')
        self.assertEqual(remote.read(run)['inference']['state'], 'pending')
        self.transport.assert_not_called()
        next_review = self.eligible()
        fresh_run = self.start(next_review)
        self.assertNotEqual(fresh_run, run_id)
        self.assertEqual(self.runtime.resume(fresh_run)['status'], 'ready_for_review')
        self.assertEqual(self.reopen().resume(run_id), result)

    def test_followup_pins_baseline_and_preserves_prior_experiment_through_another_cycle(self):
        review = self.eligible()
        participant = uuid4().hex
        prior_visit = self.case.open('original', participant)
        self.case.complete(prior_visit)
        review = self.assess()
        with closing(sqlite3.connect(self.case.path)) as db:
            prior = db.execute('SELECT snapshot FROM instruction_tests WHERE id = ?', (self.test_id,)).fetchone()[0]
            assignments = db.execute('SELECT * FROM instruction_test_assignments WHERE test_id = ?', (self.test_id,)).fetchall()
        run_id = self.start(review)
        other = AgentRuntime(self.case.path, media_dir=self.case.media,
                             operator=Operator('another', frozenset({LOCAL_BRAND})))
        with self.assertRaises(PermissionError):
            other.resume(run_id)
        self.runtime.resume(run_id, max_steps=2)
        competing = self.start(review, operation_id=uuid4().hex)
        self.runtime.resume(competing, max_steps=2)
        reopened = self.reopen()
        save = reopened.drafts.save_instruction_test

        def interrupted(*args, **kwargs):
            save(*args, **kwargs)
            raise sqlite3.OperationalError('Interrupted follow-up commit')

        with patch.object(reopened.drafts, 'save_instruction_test', side_effect=interrupted):
            with self.assertRaises(sqlite3.OperationalError):
                reopened.resume(run_id, max_steps=1)
        self.assertIsNone(self.case.drafts.read(4))
        result = reopened.resume(run_id)
        with self.assertRaises(PackageConflict):
            reopened.resume(competing)
        saved = self.case.drafts.read(4)['instruction_test']
        self.assertEqual((saved['source_revision'], saved['source_test_id'], saved['review_id']),
                         (3, self.test_id, review['id']))
        self.assertEqual(saved['before'], self.case.test['versions'][1]['content']['instruction'])
        self.assertEqual(result['steps'][0]['result']['experiment_review']['evidence'], review['evidence'])
        package = self.case.drafts.review_package(self.case.campaign, 4)
        self.assertIsNone(package['approval'])
        content = package['package']['groups'][0]['content']
        self.assertEqual({**content, 'instruction': saved['before']}, self.case.test['versions'][1]['content'])
        self.assertEqual(self.start(review), run_id)
        self.assertEqual(reopened.resume(run_id), result)
        self.assertIsNone(self.case.drafts.read(5))
        self.case.drafts.approve_package(self.case.campaign, 4, package['fingerprint'])
        next_test = reopened.instruction_tests.start(self.case.campaign, 4, package['fingerprint'])
        self.assertNotEqual(next_test['id'], self.test_id)
        self.assertEqual([version['revision'] for version in next_test['versions']], [3, 4])
        new_visit = reopened.instruction_tests.open(next_test['id'], participant)
        self.assertNotEqual(new_visit['visit_id'], prior_visit['visit_id'])
        self.assertEqual(self.case.open('original', participant)['visit_id'], prior_visit['visit_id'])
        with closing(sqlite3.connect(self.case.path)) as db:
            self.assertEqual(db.execute('SELECT snapshot FROM instruction_tests WHERE id = ?', (self.test_id,)).fetchone()[0], prior)
            self.assertEqual(db.execute('SELECT * FROM instruction_test_assignments WHERE test_id = ?', (self.test_id,)).fetchall(), assignments)
            self.assertEqual(json.loads(db.execute('SELECT snapshot FROM instruction_test_reviews WHERE id = ?',
                                                  (review['id'],)).fetchone()[0])['evidence'], review['evidence'])

    def test_keep_collecting_assessment_waits_even_above_the_visit_threshold(self):
        self.eligible()
        with patch.object(self.runtime.model, 'assess_instruction_test',
                          return_value={'reason_code': 'continue_observation'}):
            review = self.assess()
        run_id = self.start(review)
        self.assertEqual(self.runtime.resume(run_id)['status'], 'waiting_for_evidence')
        self.assertIsNone(self.case.drafts.read(4))
        self.transport.assert_not_called()

    def test_stale_superseded_legacy_and_wrong_review_references_do_not_start(self):
        review = self.eligible()
        self.case.open('revised')
        with self.assertRaises(PackageConflict):
            self.start(review)
        current = self.assess()
        with self.assertRaises(PackageConflict):
            self.start(review)
        with self.assertRaises(PackageConflict):
            self.start({'id': 'f' * 64})
        with closing(sqlite3.connect(self.case.path)) as db, db:
            row = json.loads(db.execute('SELECT snapshot FROM instruction_test_reviews WHERE id = ?',
                                        (current['id'],)).fetchone()[0])
            row['assessment'].pop('reason_code')
            db.execute('UPDATE instruction_test_reviews SET snapshot = ? WHERE id = ?', (json.dumps(row), current['id']))
        with self.assertRaises(PackageConflict):
            self.start(current)
        self.assertIsNone(self.case.drafts.read(4))

    def test_current_correction_is_rechecked_at_save(self):
        review = self.eligible()
        run_id = self.start(review)
        self.runtime.resume(run_id, max_steps=2)
        performance = self.runtime.performance
        campaign_review = performance.review(self.case.campaign, 3, self.case.fingerprint, 'balanced')
        performance.save_correction(self.case.campaign, 3, self.case.fingerprint, campaign_review['id'],
                                    'keep_comparison', '', uuid4().hex)
        with self.assertRaises(PackageConflict):
            self.runtime.resume(run_id)
        self.assertEqual(len(self.runtime.read(run_id)['steps']), 2)
        self.assertIsNone(self.case.drafts.read(4))

    def test_late_viewer_activity_rejects_provider_result_and_keeps_receipt(self):
        review = self.eligible()
        remote = self.reopen()
        self.enterContext(patch.dict(os.environ, {'OPENROUTER_API_KEY': 'authored-followup-key'}))
        reply = self.transport.side_effect

        def late_activity(*args, **kwargs):
            self.case.open('revised')
            return reply(*args, **kwargs)

        self.transport.side_effect = late_activity
        run_id = self.start(review, remote, mode='openrouter', model=MODEL, operation_id=uuid4().hex)
        with self.assertRaises(PackageConflict):
            remote.resume(run_id)
        self.assertEqual(remote.read(run_id)['inference']['state'], 'received')
        with self.assertRaises(PackageConflict):
            remote.resume(run_id)
        self.assertEqual(self.transport.call_count, 1)
        self.assertIsNone(self.case.drafts.read(4))

    def test_provider_uses_experiment_evidence_and_recovers_one_draft(self):
        review = self.eligible()
        remote = self.reopen()
        self.enterContext(patch.dict(os.environ, {'OPENROUTER_API_KEY': 'authored-followup-key'}))
        operation = uuid4().hex
        run_id = self.start(review, remote, mode='openrouter', model=MODEL, operation_id=operation)
        remote.resume(run_id, max_steps=1)
        with patch.object(remote.drafts, 'validate_instruction', side_effect=sqlite3.OperationalError('Interrupted acceptance')):
            with self.assertRaises(sqlite3.OperationalError):
                remote.resume(run_id, max_steps=1)
        reopened = self.reopen()
        result = reopened.resume(run_id)
        saved = self.case.drafts.read(4)['instruction_test']
        self.assertEqual(saved['inference']['evidence_id'], package_fingerprint(result['steps'][0]['result']))
        self.assertEqual(saved['inference']['wording_choices'], CHOICES)
        payload = json.loads(self.transport.call_args.args[0].data)
        evidence = json.loads(payload['messages'][1]['content'])
        self.assertEqual(evidence['experiment_review']['evidence'], review['evidence'])
        self.assertNotIn('sample_delivery', evidence)
        self.assertEqual(evidence['buyer_correction']['kind'], 'keep_takes')
        self.assertEqual(self.start(review, reopened, mode='openrouter', model=MODEL, operation_id=operation), run_id)
        self.assertEqual(reopened.resume(run_id), result)
        self.assertEqual(self.transport.call_count, 1)
        self.assertIsNone(self.case.drafts.read(5))
