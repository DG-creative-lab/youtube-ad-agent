from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from campaign_agent.access import BrandScope, LOCAL_BRAND, Operator
from campaign_agent.agent.run import AgentRuntime, DEMO_REQUEST
from scripts.campaign_drafts import CampaignDrafts, StaleDraft


class AgentRunTests(unittest.TestCase):
    def test_replayed_browser_start_preserves_progress_and_checks_run_owner(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "draft.sqlite"
            runtime = AgentRuntime(path)
            run_id = "a" * 32
            runtime.start(DEMO_REQUEST, run_id=run_id)
            progress = runtime.resume(run_id, max_steps=1)
            self.assertEqual(runtime.start(DEMO_REQUEST, run_id=run_id), run_id)
            self.assertEqual(runtime.read(run_id), progress)
            another_operator = Operator("another", frozenset({LOCAL_BRAND}))
            other = AgentRuntime(path, operator=another_operator)
            with self.assertRaises(PermissionError):
                other.start(DEMO_REQUEST, run_id=run_id)
            with self.assertRaises(PermissionError):
                other.resume(run_id)

    def test_restart_completes_one_draft_and_preserves_ambiguous_proposals(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "draft.sqlite"
            runtime = AgentRuntime(path)
            run_id = runtime.start(DEMO_REQUEST)
            self.assertEqual(runtime.resume(run_id, max_steps=2)["status"], "running")
            reopened = AgentRuntime(path)
            result = reopened.resume(run_id)
            self.assertEqual(result["status"], "ready_for_review")
            self.assertEqual(result["steps"][-1]["result"]["revision"], 2)
            self.assertEqual([r["id"] for r in result["steps"][-1]["result"]["ambiguous"]],
                             ["SAMPLE00003", "SAMPLE00004"])
            self.assertEqual([r["id"] for r in CampaignDrafts(path, False).read()["placements"]],
                             ["SAMPLE00001", "SAMPLE00002"])
            self.assertEqual(reopened.resume(run_id), result)
            self.assertIsNone(CampaignDrafts(path, False).read(3))

    def test_stale_draft_and_untrusted_tool_do_not_write(self):
        class WrongTool:
            def next_tool(self, request, history):
                return "save_draft"

        with TemporaryDirectory() as directory:
            path = Path(directory) / "draft.sqlite"
            runtime = AgentRuntime(path)
            run_id = runtime.start(DEMO_REQUEST)
            runtime.resume(run_id, max_steps=2)
            drafts = CampaignDrafts(path, False)
            drafts.save({"campaign_id": "tts-sample", "revision": 1, "placements": [
                {"id": "OTHER000001", "title": "Another placement",
                 "creative": "video-editing", "source": "synthetic"}]})
            with self.assertRaises(StaleDraft):
                runtime.resume(run_id)
            self.assertEqual(drafts.read()["revision"], 2)
            self.assertEqual(runtime.read(run_id)["status"], "running")
            second = AgentRuntime(path, model=WrongTool())
            other_run = second.start(DEMO_REQUEST)
            with self.assertRaises(ValueError):
                second.resume(other_run)
            self.assertEqual(second.read(other_run)["steps"], [])
            self.assertEqual(drafts.read()["revision"], 2)
            outsider = Operator("outsider", frozenset({BrandScope("other", "brand")}))
            with self.assertRaises(PermissionError):
                AgentRuntime(path, operator=outsider)


if __name__ == "__main__":
    unittest.main()
