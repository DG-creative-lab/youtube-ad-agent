"""Delivery recommendations stay deterministic and independent of storage."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import unittest

from campaign_agent.domain.delivery_next_test import next_action, respect_correction

ROOT = Path(__file__).resolve().parents[1]


def report():
    return {'window': {'start': '2026-01-01', 'end': '2026-01-02'}, 'coverage': 'complete',
            'has_delivery': True, 'groups': [{'name': 'Editing', 'creative_version': 'edit-v1',
            'metrics': {'impressions': 20, 'clicks': 5},
            'window_activity': {'arrivals': 3, 'completions': 1}}]}


class DeliveryPolicyLocationTests(unittest.TestCase):
    def test_compatibility_and_pure_domain_import_in_fresh_process(self):
        code = '''
import importlib, sys
sys.path.insert(0, sys.argv[1])
new = importlib.import_module('campaign_agent.domain.delivery_next_test')
assert not any(n == 'sqlite3' or n.startswith('campaign_agent.adapters') or n.startswith('scripts.') for n in sys.modules)
old = importlib.import_module('campaign_agent.delivery_next_test')
performance = importlib.import_module('campaign_agent.performance')
for n in ('next_action', 'respect_correction', 'recommendation_message', 'apply_correction'):
    assert getattr(old, n) is getattr(new, n), n
assert performance.apply_correction is new.apply_correction
'''
        result = subprocess.run([sys.executable, '-I', '-c', code, str(ROOT)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_coverage_and_delivery_thresholds(self):
        for change, kind in (({'window': None}, 'wait'), ({'coverage': 'unavailable'}, 'wait'),
                             ({'coverage': 'empty', 'has_delivery': False}, 'wait'),
                             ({'coverage': 'partial'}, 'coverage_check'),
                             ({'has_delivery': False}, 'wait')):
            with self.subTest(change=change):
                self.assertEqual(next_action({**report(), **change})['kind'], kind)
        for impressions, clicks, arrivals, completions, kind in (
                (20, 5, 3, 1, 'comparison_test'), (20, 5, 2, 0, 'wait'),
                (20, 5, 4, 2, 'wait'), (0, 5, 3, 1, 'wait'), (20, 0, 3, 1, 'wait')):
            with self.subTest(arrivals=arrivals, completions=completions, clicks=clicks, impressions=impressions):
                value = report(); value['groups'][0]['metrics'] = {'impressions': impressions, 'clicks': clicks}
                value['groups'][0]['window_activity'] = {'arrivals': arrivals, 'completions': completions}
                self.assertEqual(next_action(value)['kind'], kind)
        value = report(); value['groups'][0]['window_activity'] = None
        self.assertEqual(next_action(value)['kind'], 'coverage_check')

    def test_exact_recommendation_and_buyer_corrections(self):
        value = report(); unchanged = deepcopy(value)
        proposal = next_action(value)
        self.assertEqual(proposal, {'kind': 'comparison_test', 'title': 'Test a shorter second take',
            'creative_version': 'edit-v1', 'group_name': 'Editing',
            'reason': '1 of 3 eligible tagged visits completed Editing in the saved window. Google Ads reported 5 clicks for that ad group.',
            'change': 'Compare a shorter second take with the current version in a local test.',
            'hold_constant': 'Keep the ad, placements, first take and comparison instructions the same.',
            'measure': 'Compare completions per tagged arrival across the two comparison versions.'})
        self.assertEqual(value, unchanged)
        self.assertIs(respect_correction(proposal, None), proposal)
        keep = {'kind': 'keep_takes', 'label': 'Keep both takes'}
        amended = respect_correction(proposal, keep)
        self.assertEqual(amended['title'], 'Test clearer comparison instructions')
        self.assertEqual(amended['hold_constant'], 'Keep the ad, placements, both takes and choice controls the same.')
        self.assertIs(amended['correction'], keep)
        fixed = {'kind': 'keep_comparison', 'label': 'Keep comparison'}
        amended = respect_correction(proposal, fixed)
        self.assertEqual((amended['kind'], amended['title']), ('hold_comparison', 'Keep the comparison unchanged'))
        self.assertIs(amended['correction'], fixed)


if __name__ == '__main__':
    unittest.main()
