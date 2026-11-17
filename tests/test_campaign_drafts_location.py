"""The original script import stays compatible with the application owner."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CampaignDraftsLocationTests(unittest.TestCase):
    def test_import_orders_share_objects_and_preserve_default_path(self):
        for first in ('scripts.campaign_drafts', 'campaign_agent.application.campaigns'):
            code = '''
import importlib, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
importlib.import_module(sys.argv[2])
old = importlib.import_module('scripts.campaign_drafts')
new = importlib.import_module('campaign_agent.application.campaigns')
for name in ('CampaignDrafts', 'BRIEF', 'POLICY', 'StaleDraft', 'PackageConflict', 'VIDEO_ID', 'DEFAULT_DRAFT_PATH'):
    assert getattr(old, name) is getattr(new, name), name
assert new.DEFAULT_DRAFT_PATH == Path(sys.argv[1]) / '.local/campaign-drafts.sqlite3'
'''
            with self.subTest(first=first):
                result = subprocess.run([sys.executable, '-I', '-c', code, str(ROOT), first],
                                        text=True, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
