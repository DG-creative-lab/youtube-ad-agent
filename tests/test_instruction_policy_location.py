"""The domain policy stays independent and old imports preserve object identity."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstructionPolicyLocationTests(unittest.TestCase):
    def test_domain_is_pure_and_old_imports_reexport_same_objects(self):
        for first in ('campaign_agent.domain.instruction_policy', 'campaign_agent.instruction_policy'):
            code = '''
import importlib, sys
sys.path.insert(0, sys.argv[1])
domain = importlib.import_module(sys.argv[2])
assert not any(x == 'sqlite3' or x.startswith('campaign_agent.adapters') or x.startswith('scripts.') for x in sys.modules)
old = importlib.import_module('campaign_agent.instruction_policy')
new = importlib.import_module('campaign_agent.domain.instruction_policy')
for name in ('POLICY_V1', 'recommend_instruction_action', '_lift_probability', 'SAMPLE_CAP'):
    assert getattr(old, name) is getattr(new, name), name
'''
            with self.subTest(first=first):
                result = subprocess.run([sys.executable, '-I', '-c', code, str(ROOT), first],
                                        text=True, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
