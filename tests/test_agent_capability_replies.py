"""The actual chat dispatcher explains current metadata without acquiring authority."""
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import Mock
from uuid import uuid4

from campaign_agent.agent.run import AgentRuntime
from campaign_agent.ports.access import AccessUnavailable
import test_placement_planner as fixtures


class Decisions:
    def __init__(self):
        self.denied = set()
        self.unavailable = None

    def decide(self, request):
        if request.capability == self.unavailable:
            return 'unavailable'
        return 'deny' if request.capability in self.denied else 'allow'


class CapabilityReplyTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.PlacementPlannerTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.policy = Decisions()
        self.runtime = self.reopen()

    def reopen(self):
        return AgentRuntime(self.case.path, media_dir=self.case.media, access=self.policy)

    def start(self):
        return self.runtime.planner.start('What can you do?', 'simulated', uuid4().hex,
                                          uuid4().hex, self.case.catalog)

    def test_current_catalogue_drives_reply_and_retained_transcript_without_domain_changes(self):
        # Catch static capability prose, missing limitations and accidental draft/approval effects.
        before = self.runtime.drafts.read()
        result = self.case.finish(self.start(), self.runtime)
        text = result['result']['message']
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['planner']['draft_permission'], 'none')
        self.assertIn('Offline only (simulation or labelled sample/rehearsal)', text)
        self.assertIn('Planned and unavailable: Generate a contextual voiceover', text)
        self.assertIn('choose Changes · Placement draft for a new request', text)
        self.assertIn('workspace action, not an agent tool', text)
        self.assertIn('not readiness or a successful action', text)
        for item in self.runtime.capabilities()['capabilities']:
            self.assertIn(item['title'], text)
        self.assertNotIn('youtube:', text)
        self.assertEqual(self.runtime.drafts.read(), before)
        self.assertIsNone(self.runtime.drafts.review_package('tts-sample', 1)['approval'])
        reopened = self.reopen()
        chat = reopened.planner.conversations.read(result['planner']['session_id'])
        self.assertEqual(chat['messages'][-1]['content'], text)
        self.assertFalse(chat['messages'][-1].get('needs_verification', False))

    def test_current_denials_and_configuration_are_projected_at_response_time(self):
        # Revoke a narrower grant after the first turn; never claim it stays available.
        run = self.start()
        self.runtime.resume(run, max_steps=1)
        self.policy.denied.add('youtube:review.write')
        reporting = Mock()
        self.runtime.delivery.reporting = reporting
        text = self.case.finish(run, self.runtime)['result']['message']
        self.assertIn('Review campaign performance: not permitted by current access', text)
        self.assertIn('Review saved campaign delivery (application request): not permitted by current access', text)
        reporting.snapshot.assert_not_called()
        self.policy.denied.clear()
        text = self.case.finish(self.start(), self.runtime)['result']['message']
        self.assertIn('Available with current access:', text)
        self.assertNotIn('not permitted by current access', text)
        reporting.snapshot.assert_not_called()

    def test_authority_outage_does_not_commit_an_optimistic_or_stale_answer(self):
        # The metadata call checks current grant status even after a receipt exists.
        run = self.start()
        self.runtime.resume(run, max_steps=1)
        self.policy.unavailable = 'youtube:review.write'
        with self.assertRaises(AccessUnavailable):
            self.runtime.resume(run, max_steps=1)
        with closing(sqlite3.connect(self.case.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM planner_messages WHERE run_id=? AND role='assistant'", (run,)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT status FROM agent_runs WHERE id=?', (run,)).fetchone()[0], 'running')
        self.policy.unavailable = None
        self.assertEqual(self.case.finish(run, self.runtime)['status'], 'answered')
