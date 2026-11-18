from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from campaign_agent.access import BrandScope, LOCAL_BRAND, Operator
from campaign_agent.bootstrap.runtime import create_runtime as AgentRuntime
from campaign_agent.agent.run import DEMO_REQUEST
from campaign_agent.bootstrap.runtime import create_drafts as CampaignDrafts
from scripts.campaign_drafts import StaleDraft


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

    def test_step_insert_failure_after_draft_save_rolls_back_and_explicit_retry_replays(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "draft.sqlite"
            runtime = AgentRuntime(path)
            run_id = runtime.start(DEMO_REQUEST)
            progress = runtime.resume(run_id, max_steps=2)
            baseline = self._durable_rows(path)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("""CREATE TRIGGER fail_saved_draft_step BEFORE INSERT ON agent_steps
                    WHEN NEW.position=2 AND NEW.tool='save_draft'
                    AND EXISTS (SELECT 1 FROM campaign_revisions WHERE revision=2)
                    BEGIN SELECT RAISE(ABORT, 'step after saved draft'); END""")
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'step after saved draft'):
                runtime.resume(run_id, max_steps=1)
            # Fresh connections and a real runtime see exact original rows/text.
            self.assertEqual(self._durable_rows(path), baseline)
            reopened = AgentRuntime(path)
            self.assertEqual(reopened.read(run_id), progress)
            self.assertIsNone(reopened.drafts.read(2))
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('DROP TRIGGER fail_saved_draft_step')
            saved = AgentRuntime(path).resume(run_id, max_steps=1)
            self.assertEqual(saved['status'], 'running')
            self.assertEqual([step['tool'] for step in saved['steps']],
                             ['load_context', 'propose_placements', 'save_draft'])
            self.assertEqual(saved['steps'][2]['result']['revision'], 2)
            completed = AgentRuntime(path).resume(run_id)
            self.assertEqual(completed['status'], 'ready_for_review')
            accepted = self._durable_rows(path)
            self.assertEqual(AgentRuntime(path).resume(run_id), completed)
            self.assertEqual(self._durable_rows(path), accepted)
            self.assertEqual(len(accepted[0]), 2)
            self.assertEqual(len(accepted[2]), 4)
            self.assertIsNone(AgentRuntime(path).drafts.read(3))

    def test_terminal_status_failure_rolls_back_finish_step_and_preserves_accepted_draft(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "draft.sqlite"
            runtime = AgentRuntime(path)
            run_id = runtime.start(DEMO_REQUEST)
            progress = runtime.resume(run_id, max_steps=3)
            baseline = self._durable_rows(path)
            self.assertEqual(progress['steps'][2]['result']['revision'], 2)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("""CREATE TRIGGER fail_terminal_status BEFORE UPDATE OF status ON agent_runs
                    WHEN NEW.status='ready_for_review' AND EXISTS
                    (SELECT 1 FROM agent_steps WHERE run_id=NEW.id AND position=3 AND tool='finish')
                    BEGIN SELECT RAISE(ABORT, 'status after finish step'); END""")
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'status after finish step'):
                runtime.resume(run_id, max_steps=1)
            self.assertEqual(self._durable_rows(path), baseline)
            reopened = AgentRuntime(path)
            self.assertEqual(reopened.read(run_id), progress)
            self.assertEqual(reopened.drafts.read()['revision'], 2)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('DROP TRIGGER fail_terminal_status')
            completed = AgentRuntime(path).resume(run_id, max_steps=1)
            self.assertEqual(completed['status'], 'ready_for_review')
            self.assertEqual([step['tool'] for step in completed['steps']],
                             ['load_context', 'propose_placements', 'save_draft', 'finish'])
            accepted = self._durable_rows(path)
            self.assertEqual(accepted[0], baseline[0])
            self.assertEqual(accepted[2][:-1], baseline[2])
            self.assertEqual(AgentRuntime(path).resume(run_id), completed)
            self.assertEqual(self._durable_rows(path), accepted)
            self.assertIsNone(AgentRuntime(path).drafts.read(3))

    @staticmethod
    def _durable_rows(path):
        with closing(sqlite3.connect(path)) as db:
            return (db.execute('SELECT * FROM campaign_revisions ORDER BY campaign_id,revision').fetchall(),
                    db.execute('SELECT * FROM agent_runs ORDER BY id').fetchall(),
                    db.execute('SELECT * FROM agent_steps ORDER BY run_id,position').fetchall())

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
