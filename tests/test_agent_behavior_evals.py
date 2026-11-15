"""Portfolio integration and fail-closed reporting, without a second runtime suite."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import evaluate_agent_behavior as evaluation


class AgentBehaviorEvaluationTests(unittest.TestCase):
    def test_frozen_portfolio_runs_actual_commands_and_reports_native_observations(self):
        report = evaluation.evaluate()
        self.assertEqual(report['status'], 'pass', report)
        self.assertTrue(report['full_acceptance'])
        self.assertFalse(report['partial'])
        self.assertEqual(report['corpus_sha256'], evaluation.CORPUS_SHA256)
        self.assertEqual(tuple(case['id'] for case in report['cases']), evaluation.CASE_IDS)
        self.assertTrue(all(case['observed'] and case['status'] == 'pass' for case in report['cases']))
        self.assertIsNotNone(report['code']['revision'])
        for case in report['cases']:
            with self.subTest(case=case['id']):
                self.assertEqual(case['observed']['dispatch_counts']['external_transport_calls'], 0)
                self.assertEqual(case['observed']['dispatch_counts']['effect_provider_calls'], 0)

    def test_invalid_noncanonical_and_incomplete_corpora_never_execute(self):
        canonical = evaluation.load_corpus()
        missing = deepcopy(canonical)
        missing['cases'].pop()
        changed = deepcopy(canonical)
        changed['cases'][0]['expected']['current_revision'] = 2
        unknown = deepcopy(canonical)
        unknown['cases'][0]['kind'] = 'import_python'
        contents = ['', '{}', '{"schema_version":1,"schema_version":1}', json.dumps(missing),
                    json.dumps(changed), json.dumps(unknown)]
        with TemporaryDirectory(prefix='factory51-report-test-') as directory:
            path = Path(directory) / 'corpus.json'
            for content in contents:
                with self.subTest(content=content[:50]), patch.object(evaluation, 'run_case') as run:
                    path.write_text(content)
                    report = evaluation.evaluate(path)
                    self.assertEqual(report['status'], 'blocked')
                    self.assertFalse(report['full_acceptance'])
                    self.assertEqual({case['status'] for case in report['cases']}, {'notrun'})
                    run.assert_not_called()
            self.assertEqual(evaluation.evaluate(Path(directory) / 'missing.json')['status'], 'blocked')

    def test_cli_subset_is_explicitly_partial_nonzero_and_preserves_notrun_rows(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = evaluation.main(['--case', 'AB51-001'])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(report['status'], 'partial')
        self.assertTrue(report['partial'])
        self.assertFalse(report['full_acceptance'])
        self.assertEqual(report['cases'][0]['status'], 'pass')
        self.assertEqual([case['status'] for case in report['cases'][1:]], ['notrun'] * 10)

    def test_unknown_empty_duplicate_selection_and_missing_corpus_fail_before_dispatch(self):
        for selected in ([], ['AB51-999'], ['AB51-001', 'AB51-001']):
            with self.subTest(selected=selected), patch.object(evaluation, 'run_case') as run:
                report = evaluation.evaluate(selected=selected)
                self.assertEqual(report['status'], 'blocked')
                self.assertFalse(report['full_acceptance'])
                run.assert_not_called()
        output = io.StringIO()
        with redirect_stdout(output):
            code = evaluation.main(['--corpus', '/tmp/factory51-no-such-corpus-file.json'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())['status'], 'blocked')

    def test_blocked_notrun_or_missing_execution_status_cannot_become_full_acceptance(self):
        for status in ('blocked', 'notrun', None):
            def incomplete(spec, case):
                return {'id': case['id'], **({'status': status} if status is not None else {})}
            with self.subTest(status=status), patch.object(evaluation, 'run_case', incomplete):
                report = evaluation.evaluate()
                self.assertEqual(report['status'], 'blocked')
                self.assertEqual(report['error'], 'incomplete_case_execution')
                self.assertFalse(report['full_acceptance'])

    def test_report_fingerprint_and_execution_specification_share_one_read(self):
        canonical = evaluation.CORPUS.read_bytes()
        reads = []
        def changing_file(path):
            reads.append(path)
            return canonical if len(reads) == 1 else b'{}'
        def accepted(spec, case):
            return {'id': case['id'], 'status': 'pass'}
        with patch.object(Path, 'read_bytes', changing_file), patch.object(evaluation, 'run_case', accepted):
            report = evaluation.evaluate()
        self.assertEqual(len(reads), 1)
        self.assertEqual(report['corpus_sha256'], evaluation.CORPUS_SHA256)
        self.assertEqual(report['status'], 'pass')

    def test_a_wrong_native_outcome_fails_the_machine_report(self):
        original = evaluation.ScriptedModel.next_turn

        def wrong_action(model, context, history, settings):
            receipt = original(model, context, history, settings)
            if receipt['tool'] == 'save_placement_draft':
                receipt.update(tool='respond', arguments={'topic': 'campaign_summary'})
            return receipt

        output = io.StringIO()
        with patch.object(evaluation.ScriptedModel, 'next_turn', wrong_action), redirect_stdout(output):
            code = evaluation.main(['--case', 'AB51-011'])
        report = json.loads(output.getvalue())
        case = report['cases'][-1]
        self.assertEqual(code, 1)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['full_acceptance'])
        self.assertEqual(case['status'], 'failed')
        self.assertIn('current_revision', case['mismatches'])
        self.assertEqual(case['observed']['current_revision'], 1)
        self.assertEqual(case['observed']['run_statuses'], ['answered'])
        self.assertEqual(case['observed']['placement_ids'], [])

    def test_attempted_dns_and_provider_effect_are_observed_even_if_adapter_catches_errors(self):
        original = evaluation.ScriptedModel.next_turn

        def attempts_io(model, context, history, settings):
            import socket
            try:
                socket.getaddrinfo('authored.invalid', 443)
            except AssertionError:
                pass
            return original(model, context, history, settings)

        spec = evaluation.load_corpus()
        with patch.object(evaluation.ScriptedModel, 'next_turn', attempts_io):
            case = evaluation.run_case(spec, spec['cases'][0])
        self.assertEqual(case['status'], 'failed')
        self.assertIn('dispatch_counts', case['mismatches'])
        self.assertEqual(case['observed']['dispatch_counts']['external_transport_calls'], 2)

        with TemporaryDirectory(prefix='factory51-effect-test-') as directory, evaluation.ExitStack() as stack:
            exercise = evaluation.Exercise(Path(directory), spec, spec['cases'][0], stack)
            with self.assertRaises(evaluation.ObservationFailure):
                exercise.runtime.setup.provider.create_paused('authored-operation', {})
            self.assertEqual(exercise.counts['effect_provider_calls'], 1)

    def test_execution_error_is_sanitized_and_keeps_partial_native_evidence(self):
        def broken_model(*args):
            raise RuntimeError('PRIVATE_AUTHORED_SENTINEL_DO_NOT_PUBLISH')
        spec = evaluation.load_corpus()
        with patch.object(evaluation.ScriptedModel, 'next_turn', broken_model):
            case = evaluation.run_case(spec, spec['cases'][0])
        self.assertEqual(case['status'], 'failed')
        self.assertEqual(case['error'], 'case_execution_failed')
        self.assertNotIn('PRIVATE_AUTHORED_SENTINEL', json.dumps(case))
        self.assertEqual(case['observed']['current_revision'], 1)
        self.assertEqual(case['observed']['run_statuses'], ['running'])

    def test_output_does_not_overwrite_an_existing_report(self):
        with TemporaryDirectory(prefix='factory51-output-test-') as directory:
            path = Path(directory) / 'report.json'
            path.write_text('keep')
            output = io.StringIO()
            with redirect_stdout(output):
                code = evaluation.main(['--output', str(path), '--case', 'AB51-999'])
            self.assertEqual(code, 2)
            self.assertEqual(path.read_text(), 'keep')
            self.assertEqual(json.loads(output.getvalue())['error'], 'report_output_unavailable')


if __name__ == '__main__':
    unittest.main()
