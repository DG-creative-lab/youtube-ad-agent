"""Artifact boundaries only; these checks do not activate project permissions."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

from scripts import check_project_access_contract as contract


class ProjectAccessArtifactTests(unittest.TestCase):
    def mutated_fixture(self, change):
        value = contract.load(contract.FIXTURE_PATH)
        change(value)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'vectors.json'
            target.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            return contract.check(fixture_path=target)

    def test_complete_authored_artifacts_and_fixed_reference_fence(self):
        report = contract.check()
        self.assertEqual(report, {
            'positive_vectors': 5, 'binding_schema_negatives': 13, 'parser_negatives': 3,
            'reference_positives': 1, 'reference_negatives': 3,
            'scope': 'offline artifact/reference checks; no runtime authorization or service conformance'})

    def test_corrupted_literal_digest_and_incomplete_sets_cannot_report_pass(self):
        changes = [
            lambda f: f['positives'][0]['golden'].__setitem__('input_hash', 'sha256:' + '0' * 64),
            lambda f: f['positives'].pop(),
            lambda f: f['negatives'].pop(),
            lambda f: f['parser_negatives'].pop(),
            lambda f: f['reference_negatives'].pop(),
            lambda f: f.__setitem__('unexpected', True),
            lambda f: f['positives'][0]['native_state'].__delitem__('project_id'),
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(contract.ContractError):
                self.mutated_fixture(change)

    def test_cli_fails_closed_on_corrupt_and_subset_artifacts(self):
        for kind in ['corrupt', 'subset']:
            fixture = contract.load(contract.FIXTURE_PATH)
            if kind == 'corrupt':
                fixture['positives'][0]['golden']['input_hash'] = 'sha256:' + '0' * 64
            else:
                fixture['positives'].pop()
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / 'vectors.json'
                target.write_text(json.dumps(fixture), encoding='utf-8')
                result = subprocess.run([sys.executable, str(contract.ROOT / 'scripts/check_project_access_contract.py'),
                                         '--fixtures', str(target)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertIn('Artifact check failed:', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(result.stdout, '')

    def test_strict_parser_rejects_ambiguous_and_unbounded_json(self):
        cases = [b'{"nested":{"a":1,"a":2}}', b'{', b'NaN', b'1.5', b'Infinity',
                 b'9007199254740992', b'"\\ud800"', b'"\xff"',
                 b'[' * 34 + b'0' + b']' * 34, b' ' * (contract.MAX_BYTES + 1)]
        for raw in cases:
            with self.subTest(raw=raw[:60]), self.assertRaises(contract.ContractError) as caught:
                contract.parse(raw)
            self.assertEqual(caught.exception.category, 'schema_rejected')

    def test_unknown_or_remote_profile_is_rejected_before_schema_evaluation(self):
        profile = contract.load(contract.PROFILE_PATH)
        for value in [{**profile, 'extra': None}, {**profile, 'profile': 'future'},
                      {**profile, '$ref': 'https://example.invalid/schema'},
                      {**profile, '$dynamicRef': 'https://example.invalid/schema'}]:
            with self.subTest(value=list(value)[-1]), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / 'profile.json'
                target.write_text(json.dumps(value), encoding='utf-8')
                with self.assertRaises(contract.ContractError) as caught:
                    contract.check(profile_path=target)
                self.assertEqual(caught.exception.category, 'schema_rejected')

    def test_unicode_names_remain_literal_and_only_name_changes_input(self):
        vectors = {v['id']: v for v in contract.load(contract.FIXTURE_PATH)['positives']}
        composed, decomposed = vectors['create-unicode'], vectors['create-decomposed']
        left, right = copy.deepcopy(composed['command']), copy.deepcopy(decomposed['command'])
        self.assertEqual(left.pop('name'), 'Café 東京')
        self.assertEqual(right.pop('name'), 'Cafe\u0301 東京')
        self.assertEqual(left, right)
        self.assertNotEqual(composed['golden']['input_hash'], decomposed['golden']['input_hash'])
        for name in ['bad\nname', 'x' * 121]:
            with self.subTest(name=name), self.assertRaises(contract.ContractError):
                contract.encoded_fields({'name': name})

    def test_native_package_fingerprint_preserves_historical_non_ascii_identity(self):
        from campaign_agent.handoff import package_fingerprint
        example = contract.load(contract.FIXTURE_PATH)['native_package_example']
        expected = 'd6f7083aa51b545378bd240346de14e30cb09e5c691505d9148c1ee6aa6ea5dc'
        self.assertEqual(package_fingerprint(example['package']), expected)
        self.assertEqual(example['fingerprint'], expected)
        # The new profile canonicalizer must not replace the native helper's
        # historical ASCII-escaped package fingerprint algorithm.
        profile_digest = hashlib.sha256(contract.canonical(example['package'])).hexdigest()
        self.assertEqual(profile_digest, '9d42a3cbab1968c9c2588ee560ca65f0c78f569d255683e0d467195a9125b6e7')
        self.assertNotEqual(expected, profile_digest)
        profile = contract.load(contract.PROFILE_PATH)
        contract.validate(profile['native_state_schema']['properties']['package_fingerprint'], expected)
        for action in ['resource.share', 'resource.unshare']:
            schema = profile['command_schemas'][action]['properties']['package_fingerprint']
            contract.validate(schema, expected)
            with self.assertRaises(contract.ContractError):
                contract.validate(schema, 'sha256:' + expected)

    def test_recovery_reference_is_positive_current_incarnation_before_policy_choice(self):
        ref = contract.load(contract.FIXTURE_PATH)['recovery_reference']
        for change in [lambda r: r.__setitem__('overlays', []),
                       lambda r: r.__setitem__('current_incarnation', 'incarnation_old'),
                       lambda r: r.__setitem__('campaign_id', 'unreconciled_campaign')]:
            candidate = copy.deepcopy(ref); change(candidate)
            with self.assertRaises(contract.ContractError) as caught:
                contract.reference_fence(candidate)
            self.assertEqual(caught.exception.category, 'reference_fence_rejected')
        for key, value in [('classification', 'invented'), ('campaign_id', 5),
                           ('current_incarnation', 'x' * 129)]:
            candidate = copy.deepcopy(ref); candidate[key] = value
            with self.assertRaises(contract.ContractError) as caught:
                contract.reference_fence(candidate)
            self.assertEqual(caught.exception.category, 'schema_rejected')
        candidate = copy.deepcopy(ref); candidate['overlays'][0]['status'] = 'invented'
        with self.assertRaises(contract.ContractError):
            contract.reference_fence(candidate)


if __name__ == '__main__':
    unittest.main()
