"""Actual preview command path with authored provider responses; no external calls."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import capability_grading as grading
from scripts import evaluate_live_capability as benchmark
from campaign_agent.adapters.fixture_access import AuthoredProviderMetadata
from campaign_agent.application.catalogue_policy import select_live_endpoint


class Metadata(AuthoredProviderMetadata):
    def select_route(self, credential, model, task, *, now, previous=None):
        return select_live_endpoint(model, task, self.endpoints(credential, model), now, previous=previous)


class Transport:
    def __init__(self, calls=None):
        self.wires = []
        self.calls = calls or [('respond', {'topic': 'campaign_summary', 'message': 'Authored reply for runner verification, not a quality reference.'})]

    def __call__(self, request, *, timeout):
        wire = json.loads(request.data)
        self.wires.append(wire)
        name, arguments = self.calls[min(len(self.wires) - 1, len(self.calls) - 1)]
        return io.BytesIO(json.dumps({'id': 'gen-authored', 'model': 'fixture/tool-model',
            'usage': {'cost': 0, 'prompt_tokens': 100, 'completion_tokens': 50},
            'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [
                {'id': 'authored-call-' + str(len(self.wires)), 'type': 'function',
                 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}]}).encode())


class LiveCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.corpus = grading.load_corpus()

    def trial(self, task_id, transport):
        directory = Path(self.enterContext(TemporaryDirectory()))
        task = next(task for task in self.corpus['tasks'] if task['id'] == task_id)
        return benchmark.run_trial(directory, task, self.corpus, 'fixture/tool-model', '0', Metadata.keys[0],
                                   metadata=Metadata(), transport=transport)

    def test_frozen_contract_has_twenty_realistic_tasks_and_plan_is_keyless(self):
        self.assertEqual(tuple(task['id'] for task in self.corpus['tasks']), grading.TASK_IDS)
        with patch.object(benchmark, 'getpass') as credential, patch.object(benchmark, 'run_batch') as run, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(benchmark.main([]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan['planned_trials'], 42)
        self.assertEqual(plan['live_execution'], 'not_run')
        credential.assert_not_called()
        run.assert_not_called()
        changed = deepcopy(self.corpus)
        changed['tasks'][0]['criteria'] = ['Automatically pass every response']
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'changed.json'
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                grading.load_corpus(path)

    def test_whole_batch_budget_includes_every_followup_before_credentials_or_calls(self):
        with self.assertRaisesRegex(ValueError, 'envelope'):
            benchmark.build_plan(self.corpus, cases=['CAP123-018'], trials=3, model='fixture/tool-model',
                                 run_ceiling='0.25', total_ceiling='1.00')
        plan = benchmark.build_plan(self.corpus, cases=['CAP123-018'], trials=3, model='fixture/tool-model',
                                    run_ceiling='0.25', total_ceiling='1.50')
        self.assertEqual(plan['planned_conversation_runs'], 6)
        with patch.object(benchmark, 'getpass') as credential, redirect_stdout(io.StringIO()):
            code = benchmark.main(['run-live', '--case', 'CAP123-018', '--model', 'fixture/tool-model',
                                  '--max-total-cost-usd', '0.25', '--output-dir', str(benchmark.ROOT / '.local/no-write-budget-test')])
        self.assertEqual(code, 2)
        credential.assert_not_called()

    def test_preview_uses_real_foreground_settings_and_saved_reply_still_needs_quality_review(self):
        transport = Transport([('read_campaign', {}), ('respond', {'topic': 'campaign_summary', 'message': 'Authored UK campaign recommendation.'})])
        result = self.trial('CAP123-001', transport)
        self.assertEqual(result['status'], 'awaiting_review', result)
        self.assertEqual(result['automated']['status'], 'pass')
        self.assertEqual(len(transport.wires), 2)
        self.assertEqual(result['settings'][0]['model'], 'fixture/tool-model')
        self.assertTrue(result['settings'][0]['charging_profile'].startswith('preview-text-tools/'))
        self.assertEqual(result['evidence']['runs'][0]['diagnostics']['status'], 'completed')
        self.assertEqual(result['cost_usd'], '0')
        wires = json.dumps(transport.wires)
        self.assertNotIn(self.corpus['tasks'][0]['criteria'][0], wires)
        self.assertNotIn('campaign-quality-v1', wires)
        requests = result['evidence']['completion_requests']
        self.assertEqual(requests[0]['body'], transport.wires[0])
        self.assertEqual(len(requests[0]['request_sha256']), 64)
        self.assertNotIn('Authorization', json.dumps(requests))

    def test_measurement_definitions_reach_first_advice_call_and_campaign_read_without_grading_data(self):
        for calls in ([('respond', {'topic': 'capabilities', 'message': 'Authored advice, not a quality reference.'})],
                      [('read_campaign', {}), ('respond', {'topic': 'campaign_summary', 'message': 'Authored advice.'})]):
            with self.subTest(tools=[name for name, _ in calls]):
                transport = Transport(calls)
                result = self.trial('CAP123-001', transport)
                context = json.loads(transport.wires[0]['messages'][1]['content'])
                facts = context['measurement_capabilities']
                self.assertEqual(facts['kind'], 'instrumentation_definitions_not_results')
                self.assertEqual(facts['metrics']['completion_rate']['numerator'], 'completions')
                self.assertEqual(facts['metrics']['completion_rate']['denominator'], 'arrivals')
                self.assertIsNone(facts['metrics']['completion_rate']['zero_denominator_result'])
                self.assertEqual(set(facts['not_measured_by_viewer']),
                    {'publisher_video_watch_time', 'publisher_video_likes', 'unique_ad_clicks', 'trial_signups'})
                self.assertTrue(facts['completion']['all_takes_finished_before_choice'])
                self.assertEqual(facts['completion']['deduplicate_by'], ['visit_id', 'example_ref'])
                self.assertNotIn('observations', facts)
                self.assertNotIn('campaign-quality-v1', json.dumps(transport.wires))
                for task in self.corpus['tasks']:
                    for criterion in task['criteria']:
                        self.assertNotIn(criterion, json.dumps(transport.wires))
                if calls[0][0] == 'read_campaign':
                    read = next(step['result'] for step in result['evidence']['runs'][0]['steps'] if step['tool'] == 'read_campaign')
                    self.assertEqual(read['measurement_capabilities'], facts)
                self.assertEqual(result['automated']['status'], 'pass')
                self.assertEqual(result['automated']['after_revision'], 1)

    def test_granted_placement_task_saves_exact_sourced_unapproved_draft(self):
        transport = Transport([
            ('inspect_catalog', {}),
            ('classify_catalog', {'assignments': [{'id': 'EVAL0000001', 'context': 'video-editing'}, {'id': 'EVAL0000002', 'context': 'video-editing'}]}),
            ('save_placement_draft', {'video_ids': ['EVAL0000001', 'EVAL0000002']})])
        result = self.trial('CAP123-011', transport)
        self.assertEqual(result['status'], 'awaiting_review', result)
        self.assertEqual(result['automated']['placement_ids'], ['EVAL0000001', 'EVAL0000002'])
        self.assertEqual(result['automated']['after_revision'], 2)
        self.assertEqual(result['automated']['hard_failures'], [])
        self.assertTrue(all(row['source_reference'].startswith('authored:') for row in result['evidence']['after']['placements']))

    def test_live_context_contract_and_correctable_classification_error(self):
        transport = Transport([
            ('inspect_catalog', {}),
            ('classify_catalog', {'assignments': [{'id': 'EVAL0000001', 'context': 'video_editing'}]}),
            ('classify_catalog', {'assignments': [{'id': 'EVAL0000001', 'context': 'video-editing'}]}),
            ('save_placement_draft', {'video_ids': ['EVAL0000001']})])
        result = self.trial('CAP123-011', transport)
        first = transport.wires[0]
        context = json.loads(first['messages'][1]['content'])
        self.assertEqual(set(context['campaign_contexts']), {'video-editing', 'audiobook'})
        tools = {tool['function']['name']: tool['function'] for tool in first['tools']}
        enum = tools['classify_catalog']['parameters']['properties']['assignments']['items']['properties']['context']['enum']
        self.assertEqual(set(enum), {'video-editing', 'audiobook', 'review'})
        error = next(json.loads(message['content']) for message in transport.wires[3]['messages']
                     if message['role'] == 'tool' and 'error' in json.loads(message['content']))
        self.assertEqual(error['code'], 'invalid_classification')
        self.assertEqual(set(error['allowed_contexts']), set(enum))
        self.assertIn('EVAL0000001', error['inspected_video_ids'])
        self.assertNotIn('video_editing', json.dumps(error))
        self.assertEqual(result['automated']['placement_ids'], ['EVAL0000001'])
        self.assertEqual(result['automated']['after_revision'], 2)
        self.assertEqual(result['automated']['hard_failures'], [])

    def test_malformed_or_uninspected_classification_never_authorizes_a_save(self):
        for assignments in ([{'id': 'EVAL0000001', 'context': []}],
                            [{'id': 'FOREIGN0001', 'context': 'video-editing'}]):
            with self.subTest(assignments=assignments):
                transport = Transport([
                    ('classify_catalog', {'assignments': assignments}),
                    ('save_placement_draft', {'video_ids': ['EVAL0000001']}),
                    ('respond', {'topic': 'capabilities', 'message': 'No draft was saved.'})])
                result = self.trial('CAP123-011', transport)
                tool_messages = [json.loads(m['content']) for m in transport.wires[-1]['messages'] if m['role'] == 'tool']
                self.assertEqual(tool_messages[0]['code'], 'invalid_classification')
                self.assertEqual(tool_messages[0]['inspected_video_ids'], [])
                self.assertIn('error', tool_messages[1])
                self.assertEqual(result['evidence']['after']['placements'], [])
                self.assertEqual(result['automated']['after_revision'], 1)

    def test_context_schema_uses_this_campaign_without_mutating_shared_tools(self):
        from campaign_agent.agent.planning_models import planner_request_body
        def context(ids):
            return {'settings': {'charging_profile': 'preview-text-tools/test'},
                    'draft_permission': 'placements', 'campaign_contexts': ids}
        first = planner_request_body(context({'tutorial-voice': 'Tutorial narration'}), [])
        second = planner_request_body(context({'story-voice': 'Story narration'}), [])
        for body, expected, other in ((first, 'tutorial-voice', 'story-voice'), (second, 'story-voice', 'tutorial-voice')):
            tools = {tool['function']['name']: tool['function'] for tool in body['tools']}
            self.assertEqual(tools['classify_catalog']['parameters']['properties']['assignments']['items']['properties']['context']['enum'],
                             [expected, 'review'])
            self.assertEqual(tools['save_placement_draft']['parameters']['properties']['contexts']['items']['enum'], [expected])
            self.assertNotIn(other, json.dumps(body))

    def test_followup_keeps_real_conversation_and_propagates_earlier_dialogue(self):
        transport = Transport()
        result = self.trial('CAP123-018', transport)
        self.assertEqual(result['status'], 'awaiting_review', result)
        self.assertEqual(len(result['evidence']['runs']), 2)
        self.assertEqual(len(transport.wires), 2)
        self.assertIn('independent video editors', json.dumps(transport.wires[1]))

    def test_provider_failure_is_separate_from_quality_and_no_automatic_retry(self):
        calls = []
        def limited(request, *, timeout):
            calls.append(request.full_url)
            return io.BytesIO(json.dumps({'error': {'code': 429, 'message': 'Rate limit ' + Metadata.keys[0]}}).encode())
        result = self.trial('CAP123-001', limited)
        self.assertEqual(result['status'], 'provider_error', result)
        self.assertEqual(result['error_code'], 'provider_rate_limited')
        self.assertEqual(len(calls), 1)
        self.assertNotIn(Metadata.keys[0], json.dumps(result))

    def test_quality_grades_need_bound_complete_human_review_and_critical_failures_win(self):
        packet = {'trial_id': 'CAP123-001-1', 'result': {'answer': 'Authored response'}}
        review = grading.review_template(packet)
        self.assertEqual(grading.quality_grade(packet, review)['status'], 'pending')
        review.update(reviewer='Authored reviewer', notes='Checked task completion against the authored packet.',
                      scores={name: 2 for name in grading.DIMENSIONS}, critical_violations=[])
        self.assertEqual(grading.quality_grade(packet, review)['status'], 'pass')
        review['critical_violations'] = ['fabricated_action']
        self.assertEqual(grading.quality_grade(packet, review)['status'], 'fail')
        review['critical_violations'] = []
        for change in ({'trial_digest': '0' * 64}, {'scores': {name: True for name in grading.DIMENSIONS}}):
            self.assertEqual(grading.quality_grade(packet, {**review, **change})['status'], 'invalid_review')
        changed_packet = {**packet, 'result': {'answer': 'Different answer'}}
        self.assertEqual(grading.quality_grade(changed_packet, review)['status'], 'invalid_review')

    def test_pending_provider_and_notrun_rows_remain_in_the_overall_denominator(self):
        rows = [{'status': status, 'cost_usd': cost, 'duration_ms': 10 if status != 'not_run' else None}
                for status, cost in [('pass', '0.01'), ('awaiting_review', '0.02'), ('provider_error', None), ('not_run', None)]]
        result = grading.summarize(rows, 4)
        self.assertIsNone(result['all_planned_success_rate'])
        self.assertEqual(result['confirmed_success_rate_lower_bound'], 0.25)
        self.assertEqual(result['known_cost_usd'], '0.03')
        self.assertFalse(result['billing_complete'])
        self.assertIsNone(result['cost_per_success_usd'])

    def test_real_batch_packets_are_private_redacted_and_cannot_claim_live_from_authored_transport(self):
        parent = benchmark.ROOT / '.local'
        parent.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=parent) as directory:
            output = Path(directory) / 'batch'
            plan = benchmark.build_plan(self.corpus, cases=['CAP123-001'], trials=1, model='fixture/tool-model', run_ceiling='0', total_ceiling='0')
            report = benchmark.run_batch(plan, self.corpus, output, Metadata.keys[0], metadata_factory=Metadata, transport=Transport())
            self.assertEqual(report['execution_mode'], 'fixture')
            self.assertEqual(report['trials'][0]['status'], 'awaiting_review', report)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            for path in output.rglob('*.json'):
                self.assertNotIn(Metadata.keys[0], path.read_text())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            graded = benchmark.grade_run(output)
            self.assertFalse(graded['full_benchmark_passed'])
            self.assertEqual(graded['status'], 'incomplete')
            with self.assertRaises(ValueError):
                benchmark.run_batch(plan, self.corpus, output, Metadata.keys[0], metadata_factory=Metadata, transport=Transport())

    def test_complete_review_is_bound_to_actual_outcome_and_cannot_hide_task_failure(self):
        parent = benchmark.ROOT / '.local'
        parent.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=parent) as directory:
            output = Path(directory) / 'batch'
            # The model answers instead of saving the explicitly requested draft.
            plan = benchmark.build_plan(self.corpus, cases=['CAP123-011'], trials=1, model='fixture/tool-model', run_ceiling='0', total_ceiling='0')
            result = benchmark.run_batch(plan, self.corpus, output, Metadata.keys[0], metadata_factory=Metadata, transport=Transport())
            self.assertEqual(result['trials'][0]['status'], 'task_failed')
            path = output / 'CAP123-011-1' / 'review.json'
            review = json.loads(path.read_text())
            review.update(reviewer='Authored reviewer', notes='Deliberately generous scores cannot override the actual missing draft.',
                          scores={name: 2 for name in grading.DIMENSIONS}, critical_violations=[])
            path.write_text(json.dumps(review))
            graded = benchmark.grade_run(output)
            self.assertEqual(graded['trials'][0]['quality']['status'], 'pass')
            self.assertEqual(graded['trials'][0]['status'], 'task_failed')
            self.assertEqual(graded['summary']['all_planned_success_rate'], 0)
            packet_path = path.with_name('trial.private.json')
            packet = json.loads(packet_path.read_text())
            packet['result']['evidence']['after']['revision'] = 999
            packet_path.write_text(json.dumps(packet))
            self.assertEqual(benchmark.grade_run(output)['trials'][0]['status'], 'invalid_review')

    def test_interrupted_batch_retains_conservative_checkpoint_and_cannot_be_graded(self):
        parent = benchmark.ROOT / '.local'
        parent.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=parent) as directory:
            output = Path(directory) / 'batch'
            plan = benchmark.build_plan(self.corpus, cases=['CAP123-001'], trials=2, model='fixture/tool-model', run_ceiling='0', total_ceiling='0')
            with patch.object(benchmark, 'run_trial', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                benchmark.run_batch(plan, self.corpus, output, Metadata.keys[0], metadata_factory=Metadata, transport=Transport())
            saved = json.loads((output / 'report.json').read_text())
            self.assertEqual(saved['trials'][0]['status'], 'execution_error')
            self.assertIsNone(saved['trials'][0]['cost_usd'])
            self.assertEqual(saved['trials'][1]['status'], 'not_run')
            self.assertFalse(saved['source_stable'])
            with self.assertRaises(ValueError):
                benchmark.grade_run(output)

    def test_recorded_execution_error_stops_remaining_trials_even_when_billing_is_known(self):
        parent = benchmark.ROOT / '.local'
        parent.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=parent) as directory:
            output = Path(directory) / 'batch'
            plan = benchmark.build_plan(self.corpus, cases=['CAP123-001'], trials=2, model='fixture/tool-model',
                                        run_ceiling='0', total_ceiling='0')
            transport = Transport()
            # run_trial catches this unexpected pre-inference failure and returns
            # execution_error with a known zero bill, rather than raising to run_batch.
            with patch.object(benchmark.PreviewDriver, 'select', side_effect=RuntimeError('PRIVATE_EXECUTION_SENTINEL')) as select:
                report = benchmark.run_batch(plan, self.corpus, output, Metadata.keys[0], metadata_factory=Metadata, transport=transport)
            first = report['trials'][0]
            self.assertEqual(first['status'], 'execution_error')
            self.assertEqual(first['error_code'], 'benchmark_execution_failed')
            self.assertEqual(first['cost_usd'], '0')
            self.assertIn('trial_digest', first)
            self.assertEqual(select.call_count, 1)
            self.assertEqual(report['trials'][1]['status'], 'not_run')
            self.assertEqual(report['status'], 'incomplete_execution')
            self.assertFalse((output / 'CAP123-001-2').exists())
            self.assertEqual(transport.wires, [])
            saved = json.loads((output / 'report.json').read_text())
            self.assertEqual([row['status'] for row in saved['trials']], ['execution_error', 'not_run'])
            self.assertNotIn('PRIVATE_EXECUTION_SENTINEL', json.dumps(saved))

    def test_unknown_billing_and_external_effect_attempt_stop_remaining_trials(self):
        parent = benchmark.ROOT / '.local'
        parent.mkdir(exist_ok=True)
        for effect in (False, True):
            with self.subTest(effect=effect), TemporaryDirectory(dir=parent) as directory:
                def interrupted(request, *, timeout):
                    if effect:
                        benchmark.SimulatedCampaignSetup.create_paused(None, 'authored-operation', {})
                    raise TimeoutError('PRIVATE_TRANSPORT_SENTINEL')
                plan = benchmark.build_plan(self.corpus, cases=['CAP123-001'], trials=2, model='fixture/tool-model', run_ceiling='0', total_ceiling='0')
                output = Path(directory) / 'batch'
                report = benchmark.run_batch(plan, self.corpus, output, Metadata.keys[0], metadata_factory=Metadata, transport=interrupted)
                self.assertEqual(report['trials'][1]['status'], 'not_run', report)
                self.assertEqual(report['status'], 'incomplete_execution')
                self.assertFalse(report['summary']['billing_complete'])
                if effect:
                    self.assertEqual(report['trials'][0]['status'], 'safety_failed')
                self.assertNotIn('PRIVATE_TRANSPORT_SENTINEL', (output / 'report.json').read_text())

    def test_all_seed_types_preserve_their_advertised_revision_and_approval_state(self):
        tasks = {task['setup']: task for task in self.corpus['tasks']}
        for setup, task in tasks.items():
            with self.subTest(setup=setup), TemporaryDirectory() as directory:
                path = Path(directory) / 'fresh.sqlite3'
                benchmark.seed_trial(path, task, self.corpus)
                runtime = benchmark.create_runtime(path, media_dir=benchmark.DEMO_MEDIA_DIR, initialize=False)
                expected = 1 if setup in ('empty', 'catalog_injection') else 3 if setup == 'edited_after_approval' else 2
                self.assertEqual(runtime.drafts.read()['revision'], expected)
                self.assertEqual(len(benchmark.approvals(path)), int(setup in ('approved', 'edited_after_approval')))
                with self.assertRaises(ValueError):
                    benchmark.seed_trial(path, task, self.corpus)

    def test_comparison_requires_matched_complete_trials_and_recomputable_metrics(self):
        # Authored report-shaped data tests the comparison contract, not a live score.
        def report(statuses, revision):
            rows = [{'task_id': 'CAP123-001', 'attempt': index, 'status': status, 'cost_usd': '0.01', 'duration_ms': 100}
                    for index, status in enumerate(statuses, 1)]
            for row in rows:
                scores = {name: 2 if row['status'] == 'pass' else 1 for name in grading.DIMENSIONS}
                row.update(automated={'status': 'pass'}, quality={'status': 'pass' if row['status'] == 'pass' else 'fail',
                    'score': sum(scores.values()), 'scores': scores, 'reviewer': 'Authored reviewer', 'critical_violations': []})
            return {'corpus_sha256': grading.CORPUS_SHA256, 'task_ids': ['CAP123-001'], 'trials_per_task': 3,
                    'max_run_cost_usd': '0.25', 'execution_mode': 'live', 'source_stable': True,
                    'code': {'revision': revision * 40, 'dirty': False}, 'model': 'fixture/tool-model',
                    'trials': rows, 'summary': grading.summarize(rows, 3)}
        baseline, candidate = report(['pass', 'quality_failed', 'pass'], 'a'), report(['pass'] * 3, 'b')
        result = grading.compare_reports(baseline, candidate)
        self.assertAlmostEqual(result['success_rate_delta'], 1 / 3)
        for changed in ({'max_run_cost_usd': '1.00'}, {'execution_mode': 'fixture'}, {'source_stable': False},
                        {'summary': {**candidate['summary'], 'all_planned_success_rate': 0}}, {'trials': candidate['trials'][:1]}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                grading.compare_reports(baseline, {**candidate, **changed})


if __name__ == '__main__':
    unittest.main()
