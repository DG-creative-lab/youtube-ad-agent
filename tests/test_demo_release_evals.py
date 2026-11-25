"""Exercise the gate and prove it detects command, reuse and reporting regressions."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import evaluate_demo_release as gate


class DemoReleaseEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = gate.evaluate()
        cls.identity = cls.report['code']
        cls.manifest = json.loads(gate.MANIFEST.read_bytes())

    def reuse_other_suites(self, stack):
        """Fault tests rerun only the affected real command suite."""
        stack.enter_context(patch.object(gate, 'policy_evaluation', return_value=deepcopy(self.report['suites']['policy_simulation'])))
        stack.enter_context(patch.object(gate, 'learning_evaluation', return_value=deepcopy(self.report['suites']['learning_reuse'])))

    def clean_identity(self):
        return patch.object(gate.behavior, 'source_identity', return_value={**self.identity, 'dirty': False})

    def test_actual_complete_portfolio_is_sanitized_with_explicit_claim_boundaries(self):
        report = self.report
        for suite in report['suites'].values():
            self.assertEqual(suite['status'], 'pass', suite)
            self.assertEqual(suite['outbound_attempts'], {'external_transport_calls': 0, 'effect_provider_calls': 0})
        self.assertEqual(len(report['suites']['agent_behavior']['cases']), 11)
        self.assertEqual(len(report['suites']['learning_reuse']['cases']), 6)
        self.assertEqual(report['suites']['policy_simulation']['run_count'], 312)
        policies = report['suites']['policy_simulation']['policies']
        self.assertEqual(policies['keep']['mean_value'], 0)
        self.assertLess(policies['bayesian']['mean_value'], 0)
        self.assertEqual(report['hosted_smoke']['status'], 'not_run')
        self.assertEqual(report['live_model_quality']['status'], 'not_run')
        self.assertEqual(report['offline_gate_passed'], self.identity['dirty'] is False)
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'new-report'
            gate.write_report(output, report)
            self.assertEqual(len(list((output / 'traces').glob('*.json'))), 30)
            self.assertEqual(json.loads((output / 'report.json').read_text()), report)
            for trace in (output / 'traces').glob('*.json'):
                data = json.loads(trace.read_text())
                self.assertEqual(data['code'], self.identity)
                self.assertEqual(data['case']['status'], 'pass')
            text = (output / 'report.md').read_text()
            self.assertIn('traces/LR123-003.json', text)
            self.assertIn('pending hosted verification', text)

    def test_changed_manifest_and_policy_bytes_block_before_any_execution(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'changed.json'
            changed = deepcopy(self.manifest)
            changed['learning_cases'][2]['expected']['revision_delta'] = 1
            path.write_text(json.dumps(changed))
            with patch.object(gate, 'guarded') as execute:
                report = gate.evaluate(path)
                self.assertEqual(report['status'], 'blocked')
                execute.assert_not_called()
        original = Path.read_bytes
        def changed_policy(path):
            return b'{}' if path == gate.comparison.SPEC_PATH else original(path)
        with patch.object(Path, 'read_bytes', changed_policy), patch.object(gate, 'guarded') as execute:
            self.assertEqual(gate.evaluate()['status'], 'blocked')
            execute.assert_not_called()

    def test_forbidden_tool_action_fails_the_gate_with_native_evidence(self):
        original = gate.behavior.ScriptedModel.next_turn
        def invalid_action(model, context, history, settings):
            receipt = original(model, context, history, settings)
            if receipt['tool'] == 'save_placement_draft':
                receipt.update(tool='approve_package', arguments={})
            return receipt
        with gate.ExitStack() as stack:
            self.reuse_other_suites(stack)
            stack.enter_context(self.clean_identity())
            stack.enter_context(patch.object(gate.behavior.ScriptedModel, 'next_turn', invalid_action))
            report = gate.evaluate()
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['offline_gate_passed'])
        case = report['suites']['agent_behavior']['cases'][-1]
        self.assertEqual(case['status'], 'failed')
        self.assertEqual(case['observed']['current_revision'], 1)
        self.assertEqual(case['error'], 'case_execution_failed')

    def test_an_unsafe_stale_finding_write_fails_the_gate(self):
        original = gate.comparison.prepare_walkthrough
        def bypass_evidence(*args):
            runtime, target, finding, test = original(*args)
            eligible = runtime.instruction_findings.read(*target)
            # Represent a regression that reuses a cached eligibility decision.
            runtime.instruction_findings._eligible = lambda *ignored: eligible
            return runtime, target, finding, test
        stale = self.manifest['learning_cases'][2]
        with patch.object(gate.comparison, 'prepare_walkthrough', bypass_evidence):
            case = gate.guarded(lambda: gate.learning_case(stale))
        self.assertEqual(case['status'], 'failed')
        self.assertEqual(case['observed']['revision_delta'], 1)
        self.assertIsNone(case['observed']['denial'])
        self.assertIn('revision_delta', case['mismatches'])
        changed = deepcopy(self.report['suites']['learning_reuse'])
        changed['cases'][2] = case
        changed['status'] = 'failed'
        with gate.ExitStack() as stack:
            self.reuse_other_suites(stack)
            stack.enter_context(self.clean_identity())
            stack.enter_context(patch.object(gate.behavior, 'evaluate', return_value={**deepcopy(self.report['suites']['agent_behavior']), 'code': {**self.identity, 'dirty': False}}))
            stack.enter_context(patch.object(gate, 'learning_evaluation', return_value=changed))
            report = gate.evaluate()
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['offline_gate_passed'])

    def test_partial_missing_dirty_or_changed_evidence_cannot_pass(self):
        for change in ('partial', 'missing_learning', 'missing_policy', 'dirty', 'changed'):
            with self.subTest(change=change), gate.ExitStack() as stack:
                self.reuse_other_suites(stack)
                identity = {**self.identity, 'dirty': change == 'dirty'}
                stack.enter_context(patch.object(gate.behavior, 'source_identity', side_effect=[identity, {**identity, 'revision': '0' * 40}] if change == 'changed' else None, return_value=identity))
                behavior = deepcopy(self.report['suites']['agent_behavior'])
                behavior['code'] = identity
                if change == 'partial':
                    behavior['partial'] = True
                stack.enter_context(patch.object(gate.behavior, 'evaluate', return_value=behavior))
                if change == 'missing_learning':
                    stack.enter_context(patch.object(gate, 'learning_evaluation', return_value={'status': 'pass', 'cases': []}))
                if change == 'missing_policy':
                    stack.enter_context(patch.object(gate, 'policy_evaluation', return_value={'status': 'pass', 'cases': []}))
                report = gate.evaluate()
                self.assertFalse(report['offline_gate_passed'])
                self.assertNotEqual(report['status'], 'pass')

    def test_caught_io_attempts_still_fail_and_raw_errors_do_not_leak(self):
        def caught_io():
            import socket
            self.assertNotIn('OPENROUTER_API_KEY', os.environ)
            try:
                socket.getaddrinfo('authored.invalid', 443)
            except AssertionError:
                pass
            return {'status': 'pass'}
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'PRIVATE_KEY_SENTINEL'}):
            result = gate.guarded(caught_io)
            self.assertEqual(os.environ['OPENROUTER_API_KEY'], 'PRIVATE_KEY_SENTINEL')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['outbound_attempts']['external_transport_calls'], 1)
        def broken():
            raise RuntimeError('PRIVATE_PROVIDER_TEXT_SENTINEL')
        result = gate.guarded(broken)
        self.assertEqual(result['error'], 'suite_execution_failed')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_inflated_policy_utility_fails_even_when_actions_and_paired_wins_match(self):
        original = gate.comparison.score
        def inflated(*args):
            result = original(*args)
            return {**result, 'net_value': result['net_value'] + 100}
        with patch.object(gate.comparison, 'score', inflated):
            result = gate.policy_evaluation(gate.comparison.load_spec(), self.manifest['policy_reference'])
        self.assertEqual(result['paired_wins'], self.manifest['policy_reference']['paired_wins'])
        self.assertEqual(result['status'], 'failed')
        self.assertIn('scenario_invariants', result['mismatches'])
        self.assertTrue(all('fixture_truth_scoring' in case['mismatches'] for case in result['cases']))

    def test_cli_nonzero_and_reports_never_overwrite_or_mix_existing_traces(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'report'
            path.mkdir()
            sentinel = path / 'report.json'
            sentinel.write_text('preserve')
            with patch.object(gate, 'evaluate') as evaluate, redirect_stdout(io.StringIO()):
                self.assertEqual(gate.main(['--output-dir', str(path)]), 2)
                evaluate.assert_not_called()
            self.assertEqual(sentinel.read_text(), 'preserve')
            failed = deepcopy(self.report)
            failed.update(status='failed', offline_gate_passed=False)
            with patch.object(gate, 'evaluate', return_value=failed), redirect_stdout(io.StringIO()):
                self.assertEqual(gate.main(['--output-dir', str(Path(directory) / 'failed')]), 1)


if __name__ == '__main__':
    unittest.main()
