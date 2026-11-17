"""Core values/errors can be used without importing application infrastructure."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DomainFoundationsTests(unittest.TestCase):
    def child(self, code, *args):
        result = subprocess.run([sys.executable, '-I', '-c',
                                 'import sys; sys.path.insert(0, sys.argv[1]);\n' + code,
                                 str(ROOT), *args], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_each_domain_module_imports_without_scripts_or_effect_adapters(self):
        for module in ('scope', 'errors', 'inference_errors', 'placements'):
            with self.subTest(module=module):
                self.child('''
import importlib
importlib.import_module('campaign_agent.domain.' + sys.argv[2])
for name in sys.modules:
    assert not (name == 'scripts' or name.startswith('scripts.')
                or name == 'sqlite3' or name.startswith('sqlite3.')
                or name.startswith('urllib.request') or name.startswith('http.')
                or name.startswith('campaign_agent.adapters')), name
''', module)

    def test_compatibility_reexports_are_identical_in_both_import_orders(self):
        for order in ('old-first', 'new-first'):
            with self.subTest(order=order):
                self.child('''
import importlib
import re
pairs = [
    ('campaign_agent.access', 'campaign_agent.domain.scope', ('BrandScope', 'Operator', 'WorkspaceContext')),
    ('scripts.campaign_drafts', 'campaign_agent.domain.errors', ('StaleDraft', 'PackageConflict')),
    ('campaign_agent.adapters.openrouter_reviews', 'campaign_agent.domain.inference_errors', ('ReviewInferenceError',)),
    ('scripts.campaign_drafts', 'campaign_agent.domain.placements', ('VIDEO_ID',)),
]
# Import every first-side module before purging. In the new-first case this
# loads the canonical regex before any old script can compile a duplicate.
for old, new, names in pairs:
    importlib.import_module(old if sys.argv[2] == 'old-first' else new)
re.purge()
for old, new, names in pairs:
    importlib.import_module(new if sys.argv[2] == 'old-first' else old)
    a, b = importlib.import_module(old), importlib.import_module(new)
    for name in names:
        assert getattr(a, name) is getattr(b, name), (sys.argv[2], name)
from campaign_agent.domain.errors import StaleDraft, PackageConflict
from campaign_agent.domain.inference_errors import ReviewInferenceError
from scripts.campaign_drafts import StaleDraft as OldStale, PackageConflict as OldConflict
from campaign_agent.adapters.openrouter_reviews import ReviewInferenceError as OldInference
for new, old, base in ((StaleDraft, OldStale, ValueError),
                       (PackageConflict, OldConflict, ValueError),
                       (ReviewInferenceError, OldInference, RuntimeError)):
    value = {'revision': 7} if new is StaleDraft else 'same safe message'
    try:
        raise new(value)
    except old as error:
        assert isinstance(error, base)
        if new is StaleDraft:
            assert error.latest is value
            assert str(error) == 'A newer draft exists. Review your changes against it before saving.'
        else:
            assert str(error) == 'same safe message'
''', order)

    def test_scope_values_preserve_equality_json_bounds_and_denial(self):
        from dataclasses import FrozenInstanceError
        from campaign_agent.domain.scope import BrandScope, Operator, WorkspaceContext
        scope = BrandScope('client-a', 'brand')
        self.assertEqual(scope, BrandScope('client-a', 'brand'))
        self.assertEqual(len({scope, BrandScope('client-a', 'brand')}), 1)
        self.assertEqual(json.dumps(vars(scope), sort_keys=True),
                         '{"brand_id": "brand", "client_id": "client-a"}')
        operator = Operator('buyer', frozenset({scope}))
        operator.require_brand(scope)
        with self.assertRaisesRegex(PermissionError, 'no access to this client and brand'):
            operator.require_brand(BrandScope('client-b', 'brand'))
        with self.assertRaises(FrozenInstanceError):
            scope.client_id = 'client-b'
        self.assertEqual(WorkspaceContext(scope, 'workspace', 'install').scope, scope)
        self.assertEqual(len(WorkspaceContext(scope, 'x' * 200, 'install').workspace_id), 200)
        for workspace in ('', ' ', 'x' * 201, None):
            with self.subTest(workspace=workspace):
                with self.assertRaisesRegex(ValueError, 'bounded, nonempty workspace identities'):
                    WorkspaceContext(scope, workspace, 'install')

    def test_video_identifier_rule_preserves_exact_matching(self):
        from campaign_agent.domain.placements import VIDEO_ID
        for valid in ('abcdefghijk', 'a_B-0123456'):
            self.assertIsNotNone(VIDEO_ID.fullmatch(valid))
        for invalid in ('abcdefghij', 'abcdefghijkl', 'abcdefghij!', 'abcdefghijk\n', ''):
            self.assertIsNone(VIDEO_ID.fullmatch(invalid))


if __name__ == '__main__':
    unittest.main()
