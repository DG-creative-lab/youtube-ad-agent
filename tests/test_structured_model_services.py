"""Structured use cases keep authority and receipts when models are substituted."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from campaign_agent.agent.run import AgentRuntime
from campaign_agent.bootstrap.planner import create_local_planner
from campaign_agent.creatives import EXAMPLES
from campaign_agent.domain.errors import PackageConflict
from campaign_agent.domain.inference_errors import ReviewInferenceError
from campaign_agent.handoff import package_fingerprint
from campaign_agent.ports.inference import ProviderError

MODEL = 'authored/structured'
CHOICES = {'playback': 'both_in_full', 'focus': 'delivery', 'choice': 'scene_fit'}
KINDS = ('review', 'draft')


class AuthoredStructuredModel:
    models = (MODEL,)
    prompt_version = 'authored-structured-v1'
    web_disabled = False

    def __init__(self):
        self.calls, self.contexts = 0, []
        self.deny = False
        self.failure = None
        self.output = None
        self.usage = {'input_tokens': 20, 'output_tokens': 10, 'cost_usd': 0}
        self.on_call = lambda: None

    def __bool__(self):
        return False

    def settings(self, model):
        if model not in self.models:
            raise ValueError('Unknown authored model')
        return {'mode': 'openrouter', 'model': model, 'prompt_version': self.prompt_version,
                'max_calls': 1, 'max_output_tokens': 512, 'max_cost_usd': 0}

    def require_available(self, settings):
        if self.deny:
            raise ReviewInferenceError('Authored model unavailable')

    def receipt(self, context, settings, field, output):
        self.calls += 1
        self.contexts.append(deepcopy(context))
        self.on_call()
        if self.failure:
            raise self.failure
        return {field: deepcopy(self.output if self.output is not None else output),
                'inference': {**settings, 'evidence_id': package_fingerprint(context),
                              'request_id': 'authored-original-receipt', 'usage': dict(self.usage)}}

    def assess_instruction_test(self, context, settings):
        return self.receipt(context, settings, 'assessment', {'reason_code': 'insufficient_visits'})

    def draft_instructions(self, context, settings):
        return self.receipt(context, settings, 'draft', CHOICES)


class PermissiveWebModel(AuthoredStructuredModel):
    # The application gate must work even when a supplied service ignores this flag.
    @property
    def web_disabled(self):
        return False

    @web_disabled.setter
    def web_disabled(self, value):
        pass


class StructuredModelTests(unittest.TestCase):
    def prepare(self, kind):
        if kind == 'review':
            from test_instruction_tests import InstructionTestTests
            case = InstructionTestTests()
            case.setUp()
            self.addCleanup(case.doCleanups)
            case.start()
            path, media = case.path, case.media
            start = lambda runtime: runtime.start_instruction_review(case.test['id'], mode='openrouter',
                model=MODEL, operation_id=uuid4().hex)
        else:
            from test_campaign_performance import CampaignPerformanceTests
            case = CampaignPerformanceTests()
            case.setUp()
            self.addCleanup(case.doCleanups)
            _, review, _ = case.instruction_run()
            path, media = case.drafts.path, case.drafts.media_dir
            start = lambda runtime: runtime.start_next_test(case.campaign, 2, case.fingerprint, review['id'],
                mode='openrouter', model=MODEL, operation_id=uuid4().hex)
        return SimpleNamespace(kind=kind, case=case, path=path, media=media, start=start)

    def runtime(self, fixture, model, **options):
        role = 'instruction_reviewer' if fixture.kind == 'review' else 'instruction_drafter'
        return create_local_planner(fixture.path, media_dir=fixture.media, **{role: model}, **options)

    def inference(self, fixture, run):
        with closing(sqlite3.connect(fixture.path)) as db:
            return db.execute('SELECT state,receipt,error FROM agent_review_inference WHERE run_id=?', (run,)).fetchone()

    def revisions(self, fixture):
        with closing(sqlite3.connect(fixture.path)) as db:
            return db.execute('SELECT revision,snapshot FROM campaign_revisions ORDER BY revision').fetchall()

    def test_both_authored_services_drive_real_commands_without_default_construction(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                fixture, model = self.prepare(kind), AuthoredStructuredModel()
                default = 'OpenRouterReviews' if kind == 'review' else 'OpenRouterInstructions'
                with patch('campaign_agent.agent.run.' + default, side_effect=AssertionError('Default model constructed')):
                    runtime = self.runtime(fixture, model)
                self.assertIs(runtime.openrouter if kind == 'review' else runtime.openrouter_drafts, model)
                def unlocked():
                    with closing(sqlite3.connect(fixture.path, timeout=0)) as db:
                        db.execute('BEGIN IMMEDIATE')
                        db.rollback()
                model.on_call = unlocked
                run = fixture.start(runtime)
                result = runtime.resume(run)
                self.assertEqual(result['status'], 'ready_for_review')
                self.assertEqual(len(result['steps']), 4)
                self.assertEqual(model.calls, 1)
                state, raw, _ = self.inference(fixture, run)
                self.assertEqual(state, 'received')
                metadata = json.loads(raw)['inference']
                self.assertEqual(metadata['evidence_id'], package_fingerprint(model.contexts[0]))
                self.assertEqual(metadata['run_id'], run)
                if kind == 'review':
                    self.assertEqual(fixture.case.read()['review']['assessment']['title'], 'Insufficient evidence')
                else:
                    draft = runtime.drafts.read()
                    self.assertEqual(draft['revision'], 3)
                    self.assertEqual(draft['instruction_test']['inference']['wording_choices'], CHOICES)
                    self.assertIsNone(runtime.drafts.review_package('tts-sample', 3)['approval'])
                before = self.revisions(fixture)
                self.assertEqual(runtime.resume(run), result)
                self.assertEqual(self.revisions(fixture), before)
                self.assertEqual(model.calls, 1)

    def test_received_receipt_recovers_with_denied_service_even_in_web_mode(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                fixture, model = self.prepare(kind), AuthoredStructuredModel()
                runtime = self.runtime(fixture, model)
                run = fixture.start(runtime)
                runtime.resume(run, max_steps=1)
                target = runtime.instruction_tests if kind == 'review' else runtime.drafts
                method = 'validate_assessment' if kind == 'review' else 'validate_instruction'
                with patch.object(target, method, side_effect=sqlite3.OperationalError('Interrupted local validation')):
                    with self.assertRaises(sqlite3.OperationalError):
                        runtime.resume(run, max_steps=1)
                before = self.inference(fixture, run)
                self.assertEqual(before[0], 'received')
                replacement = AuthoredStructuredModel()
                replacement.deny = True
                replacement.failure = AssertionError('No inference on received evidence')
                reopened = self.runtime(fixture, replacement, web=True)
                self.assertEqual(reopened.resume(run)['status'], 'ready_for_review')
                self.assertEqual(self.inference(fixture, run), before)
                self.assertEqual(model.calls, 1)
                self.assertEqual(replacement.calls, 0)

    def test_preflight_denial_keeps_pending_allowance_and_can_recover(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                fixture, model = self.prepare(kind), AuthoredStructuredModel()
                runtime = self.runtime(fixture, model)
                run = fixture.start(runtime)
                runtime.resume(run, max_steps=1)
                model.deny = True
                with self.assertRaises(ReviewInferenceError):
                    runtime.resume(run, max_steps=1)
                self.assertEqual(self.inference(fixture, run)[0], 'pending')
                self.assertEqual(model.calls, 0)
                model.deny = False
                self.assertEqual(runtime.resume(run)['status'], 'ready_for_review')
                self.assertEqual(model.calls, 1)

    def test_web_and_foreground_cannot_be_enabled_by_a_permissive_supplied_service(self):
        from time import time
        from campaign_agent.foreground_inference import ForegroundInference
        from campaign_agent.provider_sessions import ProviderContext
        for kind in KINDS:
            with self.subTest(kind=kind):
                fixture, model = self.prepare(kind), PermissiveWebModel()
                runtime = self.runtime(fixture, model, web=True)
                before = self.revisions(fixture)
                with self.assertRaises(ReviewInferenceError):
                    fixture.start(runtime)
                self.assertEqual(self.revisions(fixture), before)
                self.assertEqual(model.calls, 0)
                runtime = self.runtime(fixture, model)
                run = fixture.start(runtime)
                runtime.resume(run, max_steps=1)
                reopened = self.runtime(fixture, model, web=True)
                with self.assertRaises(ReviewInferenceError):
                    reopened.resume(run, max_steps=1)
                self.assertEqual(self.inference(fixture, run)[0], 'pending')
                context = ProviderContext(runtime.operator.id, runtime.drafts.context, runtime.drafts.campaign_id,
                    'authored-session', time()+3600, {}, lambda: None)
                providers = SimpleNamespace(path=fixture.path, clock=time)
                foreground = ForegroundInference(providers, context, runtime.drafts.access, [])
                foreground.policy.refresh = Mock()
                model.foreground_compatible = True
                with self.assertRaises(ProviderError) as caught:
                    foreground.attach(runtime)
                self.assertEqual(caught.exception.code, 'route_unqualified')
                self.assertIsNone(runtime.foreground)
                foreground.policy.refresh.assert_not_called()
                self.assertEqual(model.calls, 0)

    def test_unexpected_service_failure_is_sanitized_and_never_retried(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                fixture, model = self.prepare(kind), AuthoredStructuredModel()
                model.failure = TimeoutError('private-provider-sentinel')
                runtime = self.runtime(fixture, model)
                run = fixture.start(runtime)
                runtime.resume(run, max_steps=1)
                for _ in range(2):
                    with self.assertRaises(ReviewInferenceError) as caught:
                        runtime.resume(run, max_steps=1)
                    self.assertNotIn('private-provider-sentinel', str(caught.exception))
                state, _, error = self.inference(fixture, run)
                self.assertEqual(state, 'failed')
                self.assertNotIn('private-provider-sentinel', error)
                self.assertEqual(model.calls, 1)

    def test_invalid_business_output_or_excess_usage_retains_receipt_without_acceptance(self):
        for kind in KINDS:
            for invalid in ('output', 'cost', 'tokens', 'metadata'):
                with self.subTest(kind=kind, invalid=invalid):
                    fixture, model = self.prepare(kind), AuthoredStructuredModel()
                    if invalid == 'output': model.output = {'unsupported': 'untrusted model data'}
                    elif invalid == 'cost': model.usage['cost_usd'] = 1
                    elif invalid == 'metadata': model.usage['cost_usd'] = float('nan')
                    else: model.usage['output_tokens'] = 513
                    runtime = self.runtime(fixture, model)
                    run = fixture.start(runtime)
                    runtime.resume(run, max_steps=1)
                    before = self.revisions(fixture)
                    for _ in range(2):
                        with self.assertRaises(ReviewInferenceError):
                            runtime.resume(run, max_steps=1)
                    self.assertEqual(self.inference(fixture, run)[0], 'failed' if invalid == 'metadata' else 'received')
                    self.assertEqual(self.revisions(fixture), before)
                    self.assertEqual(model.calls, 1)

    def test_changed_source_after_inference_keeps_receipt_but_cannot_commit(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                fixture, model = self.prepare(kind), AuthoredStructuredModel()
                runtime = self.runtime(fixture, model)
                run = fixture.start(runtime)
                runtime.resume(run, max_steps=1)
                before = self.revisions(fixture)
                def change_correction():
                    for _ in range(3): fixture.case.open('revised')
                    review = fixture.case.runtime.performance.review(
                        fixture.case.campaign, 3, fixture.case.fingerprint, 'balanced')
                    fixture.case.runtime.performance.save_correction(fixture.case.campaign, 3,
                        fixture.case.fingerprint, review['id'], 'keep_comparison', '', uuid4().hex)
                model.on_call = change_correction if kind == 'review' else (
                    lambda: (Path(fixture.media) / EXAMPLES[0].preview).write_bytes(b'Changed after dispatch'))
                with self.assertRaises(PackageConflict):
                    runtime.resume(run, max_steps=1)
                self.assertEqual(self.inference(fixture, run)[0], 'received')
                self.assertEqual(self.revisions(fixture), before)
                with self.assertRaises(PackageConflict):
                    runtime.resume(run, max_steps=1)
                self.assertEqual(model.calls, 1)

    def test_failed_receipt_write_stays_requested_without_repeating_the_service(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                fixture, model = self.prepare(kind), AuthoredStructuredModel()
                runtime = self.runtime(fixture, model)
                run = fixture.start(runtime)
                runtime.resume(run, max_steps=1)
                with closing(sqlite3.connect(fixture.path)) as db, db:
                    db.execute("CREATE TRIGGER authored_receipt_failure BEFORE UPDATE OF receipt ON agent_review_inference "
                               "WHEN NEW.receipt IS NOT NULL BEGIN SELECT RAISE(ABORT,'authored fault'); END")
                with self.assertRaises(sqlite3.IntegrityError):
                    runtime.resume(run, max_steps=1)
                self.assertEqual(self.inference(fixture, run)[0], 'requested')
                with self.assertRaises(ReviewInferenceError):
                    runtime.resume(run, max_steps=1)
                self.assertEqual(model.calls, 1)

    def test_a_different_actor_cannot_dispatch_a_saved_run(self):
        from campaign_agent.access import LOCAL_BRAND, Operator
        for kind in KINDS:
            with self.subTest(kind=kind):
                fixture, model = self.prepare(kind), AuthoredStructuredModel()
                runtime = self.runtime(fixture, model)
                run = fixture.start(runtime)
                runtime.resume(run, max_steps=1)
                role = 'instruction_reviewer' if kind == 'review' else 'instruction_drafter'
                intruder = AgentRuntime(fixture.path, media_dir=fixture.media,
                    operator=Operator('another-actor', frozenset({LOCAL_BRAND})), **{role: model})
                with self.assertRaises(PermissionError):
                    intruder.resume(run)
                self.assertEqual(self.inference(fixture, run)[0], 'pending')
                self.assertEqual(model.calls, 0)

    def test_supplied_settings_cannot_expand_the_application_budget_or_request_profile(self):
        changes = [
            {'max_output_tokens': 9999}, {'max_output_tokens': 0}, {'max_output_tokens': '512'},
            {'max_output_tokens': True}, {'max_calls': 2}, {'max_cost_usd': 1},
            {'max_cost_usd': -1}, {'max_cost_usd': float('nan')}, {'max_cost_usd': '0'},
            {'foreground': True}, {'mode': 'offline'}, {'model': 'unrelated-model'},
            {'prompt_version': 'unrelated-prompt'},
        ]
        for kind in KINDS:
            fixture = self.prepare(kind)
            for change in changes:
                with self.subTest(kind=kind, change=change):
                    model = AuthoredStructuredModel()
                    original = model.settings
                    model.settings = lambda selected, change=change: {**original(selected), **change}
                    runtime = self.runtime(fixture, model)
                    with closing(sqlite3.connect(fixture.path)) as db:
                        before = [db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                                  for table in ('agent_runs', 'agent_test_sources', 'agent_review_inference')]
                    with self.assertRaises(ReviewInferenceError):
                        fixture.start(runtime)
                    with closing(sqlite3.connect(fixture.path)) as db:
                        after = [db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                                 for table in ('agent_runs', 'agent_test_sources', 'agent_review_inference')]
                    self.assertEqual(after, before)
                    self.assertEqual(model.calls, 0)

    def test_receipt_provenance_is_bound_even_when_reopened_without_the_supplied_service(self):
        changes = {'mode': 'offline', 'model': 'unrelated-model', 'prompt_version': 'unrelated-prompt',
                   'evidence_id': 'unrelated-evidence', 'max_calls': 2, 'max_output_tokens': 9999,
                   'max_cost_usd': 1}
        for kind in KINDS:
            for field, value in changes.items():
                with self.subTest(kind=kind, field=field):
                    fixture, model = self.prepare(kind), AuthoredStructuredModel()
                    original = model.receipt
                    def forged(context, settings, output_field, output):
                        receipt = original(context, settings, output_field, output)
                        receipt['inference'][field] = value
                        return receipt
                    model.receipt = forged
                    runtime = self.runtime(fixture, model)
                    run = fixture.start(runtime)
                    runtime.resume(run, max_steps=1)
                    before = self.revisions(fixture)
                    with self.assertRaises(ReviewInferenceError):
                        runtime.resume(run, max_steps=1)
                    received = self.inference(fixture, run)
                    self.assertEqual(received[0], 'received')
                    self.assertEqual(json.loads(received[1])['inference'][field], value)
                    reopened = create_local_planner(fixture.path, media_dir=fixture.media)
                    with self.assertRaises(ReviewInferenceError):
                        reopened.resume(run, max_steps=1)
                    self.assertEqual(self.inference(fixture, run), received)
                    self.assertEqual(self.revisions(fixture), before)
                    self.assertEqual(len(reopened.read(run)['steps']), 1)
                    self.assertEqual(model.calls, 1)

    def test_service_cannot_mutate_the_accepted_context_or_budget_during_dispatch(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                fixture, model = self.prepare(kind), AuthoredStructuredModel()
                original = model.receipt
                def mutate(context, settings, field, output):
                    context.clear()
                    settings['max_output_tokens'] = 9999
                    return original(context, settings, field, output)
                model.receipt = mutate
                runtime = self.runtime(fixture, model)
                run = fixture.start(runtime)
                runtime.resume(run, max_steps=1)
                source = runtime.read(run)['steps'][0]['result']
                with self.assertRaises(ReviewInferenceError):
                    runtime.resume(run, max_steps=1)
                self.assertEqual(runtime.read(run)['steps'][0]['result'], source)
                with closing(sqlite3.connect(fixture.path)) as db:
                    settings = json.loads(db.execute('SELECT settings FROM agent_review_inference WHERE run_id=?', (run,)).fetchone()[0])
                self.assertEqual(settings['max_output_tokens'], 512)
                self.assertEqual(self.inference(fixture, run)[0], 'received')
                self.assertEqual(model.calls, 1)

    def test_persisted_expanded_budget_cannot_dispatch_or_be_accepted_on_recovery(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                fixture, model = self.prepare(kind), AuthoredStructuredModel()
                runtime = self.runtime(fixture, model)
                run = fixture.start(runtime)
                runtime.resume(run, max_steps=1)
                settings = {**model.settings(MODEL), 'max_output_tokens': 9999}
                with closing(sqlite3.connect(fixture.path)) as db, db:
                    db.execute('UPDATE agent_review_inference SET settings=? WHERE run_id=?', (json.dumps(settings), run))
                with self.assertRaises(ReviewInferenceError):
                    runtime.resume(run, max_steps=1)
                self.assertEqual(model.calls, 0)
                self.assertEqual(self.inference(fixture, run)[0], 'pending')
                # Authored received history from a pre-fix implementation must also fail closed.
                context = runtime.read(run)['steps'][0]['result']
                output_field = 'assessment' if kind == 'review' else 'draft'
                output = {'reason_code': 'insufficient_visits'} if kind == 'review' else CHOICES
                receipt = model.receipt(context, settings, output_field, output)
                receipt['inference']['run_id'] = run
                with closing(sqlite3.connect(fixture.path)) as db, db:
                    db.execute("UPDATE agent_review_inference SET state='received',receipt=? WHERE run_id=?",
                               (json.dumps(receipt), run))
                before = self.inference(fixture, run)
                reopened = create_local_planner(fixture.path, media_dir=fixture.media)
                with self.assertRaises(ReviewInferenceError):
                    reopened.resume(run, max_steps=1)
                self.assertEqual(self.inference(fixture, run), before)
                self.assertEqual(len(reopened.read(run)['steps']), 1)
