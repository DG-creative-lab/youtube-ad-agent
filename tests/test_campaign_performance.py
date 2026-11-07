from dataclasses import replace
from contextlib import closing
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from campaign_agent.access import BrandScope
from campaign_agent.creatives import EXAMPLES
from campaign_agent.handoff import package_fingerprint
from campaign_agent.measurement import ViewerMeasurement, ViewerNotFound
from campaign_agent.performance import CampaignPerformance
from campaign_agent.agent.run import AgentRuntime, RecordedInference
from scripts.campaign_drafts import CampaignDrafts, PackageConflict


class CampaignPerformanceTests(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(TemporaryDirectory()))
        media = folder / "media"
        media.mkdir()
        for example in EXAMPLES:
            for name in {example.preview, *(name for _, _, name in example.takes)}:
                (media / name).write_bytes(name.encode())
        self.drafts = CampaignDrafts(folder / "drafts.sqlite", live=False, media_dir=media)
        self.viewer = ViewerMeasurement(self.drafts.path)
        self.performance = CampaignPerformance(self.drafts, self.viewer)
        self.campaign = self.drafts.campaign_id
        self.drafts.save({"campaign_id": self.campaign, "revision": 1, "placements": [
            {"id": "SAMPLE00001", "title": "Editing", "creative": "video-editing", "source": "synthetic"},
            {"id": "SAMPLE00002", "title": "Audiobook", "creative": "audiobook", "source": "synthetic"},
        ]})
        self.fingerprint = self.drafts.review_package(self.campaign, 2)["fingerprint"]

    def complete(self, creative, example, visit):
        for take in ("a", "b"):
            for kind in ("start", "finish"):
                self.viewer.record(creative, visit, example, uuid4().hex, kind, take)
        self.viewer.record(creative, visit, example, uuid4().hex, "choose", "a")

    def instruction_run(self):
        approved = self.drafts.approve_package(self.campaign, 2, self.fingerprint)
        content = package_fingerprint(approved["package"]["groups"][0]["content"])
        for _ in range(3):
            self.viewer.open_example(EXAMPLES[0].creative_ref, content_fingerprint=content)
        initial = self.performance.review(self.campaign, 2, self.fingerprint, "balanced")
        self.performance.save_correction(
            self.campaign, 2, self.fingerprint, initial["id"], "keep_takes", "Keep the approved audio.", uuid4().hex,
        )
        review = self.performance.review(self.campaign, 2, self.fingerprint, "balanced")
        runtime = AgentRuntime(self.drafts.path, media_dir=self.drafts.media_dir)
        run_id = runtime.start_next_test(self.campaign, 2, self.fingerprint, review["id"])
        return runtime, review, run_id

    def test_instruction_run_resumes_one_revision_and_preserves_source_and_content_attribution(self):
        runtime, source, run_id = self.instruction_run()
        runtime.resume(run_id, max_steps=2)
        reopened = AgentRuntime(self.drafts.path, media_dir=self.drafts.media_dir)
        self.assertEqual(reopened.start_next_test(self.campaign, 2, self.fingerprint, source["id"]), run_id)
        save = reopened.drafts.save_instruction_test

        def fail_after_save(*args):
            save(*args)
            raise sqlite3.OperationalError("Simulated lost transaction")

        with patch.object(reopened.drafts, "save_instruction_test", side_effect=fail_after_save):
            with self.assertRaises(sqlite3.OperationalError):
                reopened.resume(run_id, max_steps=1)
        self.assertIsNone(self.drafts.read(3))
        self.assertEqual(len(reopened.read(run_id)["steps"]), 2)
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM comparison_instruction_versions").fetchone()[0], 0)

        result = reopened.resume(run_id)
        self.assertEqual(result["status"], "ready_for_review")
        self.assertEqual(result["steps"][-1]["result"]["revision"], 3)
        self.assertEqual(reopened.start_next_test(self.campaign, 2, self.fingerprint, source["id"]), run_id)
        self.assertEqual(reopened.resume(run_id), result)
        self.assertIsNone(self.drafts.read(4))
        original = self.drafts.read_approved_package(self.campaign, 2, self.fingerprint)["package"]
        updated = self.drafts.review_package(self.campaign, 3)
        self.assertIsNone(updated["approval"])
        self.assertEqual(self.drafts.read(3)["placements"], self.drafts.read(2)["placements"])
        old_content = original["groups"][0]["content"]
        new_content = updated["package"]["groups"][0]["content"]
        self.assertNotEqual(new_content["instruction"], old_content["instruction"])
        self.assertEqual({**new_content, "instruction": old_content["instruction"]}, old_content)
        test = updated["package"]["instruction_test"]
        self.assertEqual(test["review_id"], source["id"])
        self.assertEqual(test["correction"], source["proposal"]["correction"])
        self.assertEqual(test["before"], old_content["instruction"])
        self.assertEqual(test["after"], new_content["instruction"])
        self.assertEqual(result["steps"][0]["result"]["review"], source)
        self.assertEqual(self.drafts.comparison_content(EXAMPLES[0], package_fingerprint(new_content)), new_content)
        self.assertEqual(self.drafts.comparison_content(EXAMPLES[0], package_fingerprint(old_content)), old_content)
        with self.assertRaises(PackageConflict):
            self.drafts.export_setup(self.campaign, 3, updated["fingerprint"])
        self.drafts.approve_package(self.campaign, 3, updated["fingerprint"])
        fresh = self.performance.review(self.campaign, 3, updated["fingerprint"], "balanced")
        self.assertEqual(fresh["local_viewer_activity"]["rows"][0]["arrivals"], 0)
        for _ in range(3):
            self.viewer.open_example(EXAMPLES[0].creative_ref, content_fingerprint=package_fingerprint(new_content))
        fresh = self.performance.review(self.campaign, 3, updated["fingerprint"], "balanced")
        self.assertEqual(fresh["proposal"]["correction"], source["proposal"]["correction"])
        (self.drafts.media_dir / EXAMPLES[0].takes[1][2]).write_bytes(b"Newly prepared media")
        changed_content = self.drafts.review_package(self.campaign, 3)["package"]["groups"][0]["content"]
        self.assertEqual(self.drafts.comparison_content(EXAMPLES[0], package_fingerprint(changed_content)), changed_content)

    def test_instruction_run_rejects_a_replaced_correction_and_an_unsupported_test(self):
        runtime, source, run_id = self.instruction_run()
        runtime.resume(run_id, max_steps=2)
        self.performance.save_correction(
            self.campaign, 2, self.fingerprint, source["id"], "keep_comparison", "", uuid4().hex,
        )
        with self.assertRaisesRegex(PackageConflict, "correction changed"):
            runtime.resume(run_id)
        self.assertIsNone(self.drafts.read(3))
        self.assertEqual(len(runtime.read(run_id)["steps"]), 2)
        updated = self.performance.review(self.campaign, 2, self.fingerprint, "balanced")
        with self.assertRaisesRegex(ValueError, "instruction tests"):
            runtime.start_next_test(self.campaign, 2, self.fingerprint, updated["id"])
        with self.assertRaises(ValueError):
            runtime.start_next_test("another-campaign", 2, self.fingerprint, source["id"])

    def test_instruction_run_rechecks_media_and_draft_at_save(self):
        runtime, _, run_id = self.instruction_run()
        runtime.resume(run_id, max_steps=2)
        take = self.drafts.media_dir / EXAMPLES[0].takes[1][2]
        original = take.read_bytes()
        take.write_bytes(b"Changed during preparation")
        with self.assertRaises(PackageConflict):
            runtime.resume(run_id)
        self.assertIsNone(self.drafts.read(3))
        take.write_bytes(original)
        self.drafts.save({"campaign_id": self.campaign, "revision": 2,
                          "placements": [{**row, "title": row["title"] + " edited"}
                                         for row in self.drafts.read()["placements"]]})
        with self.assertRaises(PackageConflict):
            runtime.resume(run_id)
        self.assertNotIn("instruction_test", self.drafts.read(3))
        self.assertIsNone(self.drafts.read(4))

    def test_instruction_run_validates_model_tools_and_content(self):
        class InvalidInstructions(RecordedInference):
            def revise_instructions(self, context):
                return {"instruction": "Untrusted structured output"}

        class InvalidTool(RecordedInference):
            def next_tool(self, request, history):
                return "save_instruction_test"

        runtime, _, run_id = self.instruction_run()
        runtime.model = InvalidTool()
        with self.assertRaisesRegex(ValueError, "unavailable"):
            runtime.resume(run_id)
        self.assertEqual(runtime.read(run_id)["steps"], [])
        runtime.model = InvalidInstructions()
        with self.assertRaisesRegex(ValueError, "revised comparison instructions"):
            runtime.resume(run_id)
        self.assertIsNone(self.drafts.read(3))
        self.assertEqual(len(runtime.read(run_id)["steps"]), 1)
        runtime.model = RecordedInference()
        self.assertEqual(runtime.resume(run_id)["status"], "ready_for_review")

    def test_review_keeps_sample_coverage_separate_and_requires_approval(self):
        with self.assertRaisesRegex(PackageConflict, "Approve this revision"):
            self.performance.review(self.campaign, 2, self.fingerprint, "limited")
        self.drafts.approve_package(self.campaign, 2, self.fingerprint)
        result = self.performance.review(self.campaign, 2, self.fingerprint, "limited")
        self.assertEqual(result["proposal"]["kind"], "delivery_check")
        self.assertEqual(result["sample_delivery"]["coverage"], "partial")
        self.assertEqual(result["sample_delivery"]["rows"][0]["metrics"]["impressions"], 35)
        self.assertIsNone(result["sample_delivery"]["rows"][1]["metrics"])
        self.assertIsNone(result["local_viewer_activity"]["rows"][0]["completion_rate"])
        balanced = self.performance.review(self.campaign, 2, self.fingerprint, "balanced")
        self.assertEqual(balanced["proposal"]["kind"], "collect_activity")
        reopened = CampaignPerformance(self.drafts, self.viewer)
        self.assertEqual(reopened.read(self.campaign, 2, self.fingerprint)["review"], balanced)
        self.assertEqual(reopened.review(self.campaign, 2, self.fingerprint, "limited"), result)
        self.assertEqual(reopened.read(self.campaign, 2, self.fingerprint)["review"], result)

    def test_review_counts_scoped_visits_and_only_intended_completions(self):
        approved = self.drafts.approve_package(self.campaign, 2, self.fingerprint)
        content = package_fingerprint(approved["package"]["groups"][0]["content"])
        editing, audiobook = EXAMPLES
        creative = editing.creative_ref
        intended = self.viewer.open_example(creative, content_fingerprint=content)["visit_id"]
        self.complete(creative, editing.ref, intended)
        self.viewer.open_example(creative, visit_id=intended, content_fingerprint=content)
        switched = self.viewer.open_example(creative, audiobook.ref, content_fingerprint=content)["visit_id"]
        self.complete(creative, audiobook.ref, switched)
        self.viewer.open_example(creative, content_fingerprint=content)
        self.viewer.open_example(creative)
        foreign = ViewerMeasurement(self.drafts.path, [replace(editing, scope=BrandScope("other", "other"))])
        foreign.open_example(creative, content_fingerprint=content)

        result = self.performance.review(self.campaign, 2, self.fingerprint, "balanced")
        editing_row, audiobook_row = result["local_viewer_activity"]["rows"]
        self.assertEqual((editing_row["arrivals"], editing_row["intended_opens"], editing_row["completions"]), (3, 2, 1))
        self.assertAlmostEqual(editing_row["completion_rate"], 1 / 3)
        self.assertEqual(editing_row["unattributed_arrivals"], 1)
        self.assertEqual((audiobook_row["arrivals"], audiobook_row["completions"]), (0, 0))
        self.assertEqual(result["proposal"]["kind"], "comparison_test")
        self.assertEqual(result["proposal"]["creative_version"], creative)
        self.assertEqual(result["proposal"]["evidence"], ["local_viewer_activity"])

    def test_changed_take_does_not_inherit_previous_activity(self):
        editing = EXAMPLES[0]
        approved = self.drafts.approve_package(self.campaign, 2, self.fingerprint)
        old_content = package_fingerprint(approved["package"]["groups"][0]["content"])
        old_visits = [
            self.viewer.open_example(editing.creative_ref, content_fingerprint=old_content)["visit_id"]
            for _ in range(3)
        ]
        self.viewer.open_example(editing.creative_ref)
        before = self.performance.review(self.campaign, 2, self.fingerprint, "balanced")
        self.assertEqual(before["proposal"]["kind"], "comparison_test")

        (self.drafts.media_dir / editing.takes[1][2]).write_bytes(b"Revised second take")
        fingerprint = self.drafts.review_package(self.campaign, 2)["fingerprint"]
        approved = self.drafts.approve_package(self.campaign, 2, fingerprint)
        new_content = package_fingerprint(approved["package"]["groups"][0]["content"])
        with self.assertRaises(ViewerNotFound):
            self.viewer.open_example(editing.creative_ref, visit_id=old_visits[0], content_fingerprint=new_content)
        with self.assertRaises(ViewerNotFound):
            self.viewer.open_example(editing.creative_ref, visit_id=old_visits[0])

        after = self.performance.review(self.campaign, 2, fingerprint, "balanced")
        row = after["local_viewer_activity"]["rows"][0]
        self.assertEqual((row["arrivals"], row["unattributed_arrivals"]), (0, 1))
        self.assertIsNone(row["completion_rate"])
        self.assertEqual(after["proposal"]["kind"], "collect_activity")
        self.viewer.open_example(editing.creative_ref, content_fingerprint=new_content)
        latest = self.performance.review(self.campaign, 2, fingerprint, "balanced")
        self.assertEqual(latest["local_viewer_activity"]["rows"][0]["arrivals"], 1)

    def test_saved_correction_changes_the_next_comparison_test_and_preserves_evidence(self):
        approved = self.drafts.approve_package(self.campaign, 2, self.fingerprint)
        creative = EXAMPLES[0].creative_ref
        content = package_fingerprint(approved["package"]["groups"][0]["content"])
        for _ in range(3):
            self.viewer.open_example(creative, content_fingerprint=content)
        original = self.performance.review(self.campaign, 2, self.fingerprint, "balanced")
        self.assertEqual(original["proposal"]["title"], "Test a shorter second take")
        with self.assertRaisesRegex(ValueError, "review for this approved package"):
            self.performance.save_correction(self.campaign, 2, self.fingerprint, "f" * 64, "keep_takes", "", uuid4().hex)
        original_operation = uuid4().hex
        saved = self.performance.save_correction(
            self.campaign, 2, self.fingerprint, original["id"], "keep_takes", "Keep approved narration.", original_operation,
        )
        reopened = CampaignPerformance(self.drafts, self.viewer)
        pending = reopened.read(self.campaign, 2, self.fingerprint)
        self.assertEqual(pending["review"], original)
        self.assertEqual(pending["correction"], saved)

        next_review = reopened.review(self.campaign, 2, self.fingerprint, "balanced")
        self.assertEqual(next_review["proposal"]["title"], "Test clearer comparison instructions")
        self.assertEqual(next_review["proposal"]["correction"], saved)
        self.assertEqual(next_review["proposal"]["evidence"], ["local_viewer_activity"])
        self.assertEqual(next_review["local_viewer_activity"], original["local_viewer_activity"])
        self.assertEqual(saved["review_id"], original["id"])

        later = reopened.save_correction(
            self.campaign, 2, self.fingerprint, next_review["id"], "keep_comparison", "", uuid4().hex,
        )
        self.assertEqual(reopened.save_correction(
            self.campaign, 2, self.fingerprint, original["id"], "keep_takes", "Keep approved narration.", original_operation,
        ), later)
        with self.assertRaisesRegex(ValueError, "different save"):
            reopened.save_correction(
                self.campaign, 2, self.fingerprint, original["id"], "keep_comparison", "", original_operation,
            )
        adjusted = reopened.review(self.campaign, 2, self.fingerprint, "balanced")
        self.assertEqual(adjusted["proposal"]["title"], "Test how the ad sets up the comparison")
        self.assertEqual(adjusted["proposal"]["correction"], later)
        limited = reopened.review(self.campaign, 2, self.fingerprint, "limited")
        self.assertEqual(limited["proposal"]["kind"], "delivery_check")
        self.assertNotIn("correction", limited["proposal"])
        restored = reopened.save_correction(
            self.campaign, 2, self.fingerprint, original["id"], "keep_takes", "Keep approved narration.", uuid4().hex,
        )
        self.assertNotEqual(restored["id"], saved["id"])
        self.assertEqual(restored["kind"], saved["kind"])
        revised = reopened.review(self.campaign, 2, self.fingerprint, "balanced")
        self.assertEqual(revised["proposal"]["correction"], restored)
        self.assertEqual(revised["proposal"]["title"], "Test clearer comparison instructions")

        take = self.drafts.media_dir / EXAMPLES[0].takes[1][2]
        original_take = take.read_bytes()
        take.write_bytes(b"Changed second take")
        changed = self.drafts.review_package(self.campaign, 2)["fingerprint"]
        approved = self.drafts.approve_package(self.campaign, 2, changed)
        content = package_fingerprint(approved["package"]["groups"][0]["content"])
        for _ in range(3):
            self.viewer.open_example(creative, content_fingerprint=content)
        fresh = reopened.review(self.campaign, 2, changed, "balanced")
        self.assertEqual(fresh["proposal"]["title"], "Test a shorter second take")
        self.assertNotIn("correction", fresh["proposal"])
        with self.assertRaisesRegex(ValueError, "review for this approved package"):
            reopened.save_correction(self.campaign, 2, changed, original["id"], "keep_takes", "", uuid4().hex)

        changed_correction = reopened.save_correction(
            self.campaign, 2, changed, fresh["id"], "keep_comparison", "", uuid4().hex,
        )
        self.assertEqual(changed_correction["kind"], "keep_comparison")
        take.write_bytes(original_take)
        self.assertEqual(reopened.read(self.campaign, 2, self.fingerprint)["correction"], restored)
        self.assertEqual(
            reopened.review(self.campaign, 2, self.fingerprint, "balanced")["proposal"]["correction"], restored,
        )

    def test_existing_correction_survives_a_separate_ad_preview_change(self):
        audiobook = EXAMPLES[1]

        def approve_and_review():
            fingerprint = self.drafts.review_package(self.campaign, 2)["fingerprint"]
            approved = self.drafts.approve_package(self.campaign, 2, fingerprint)
            content = package_fingerprint(approved["package"]["groups"][1]["content"])
            for _ in range(3):
                self.viewer.open_example(audiobook.creative_ref, content_fingerprint=content)
            return self.performance.review(self.campaign, 2, fingerprint, "balanced")

        original = approve_and_review()
        correction = self.performance.save_correction(
            self.campaign, 2, self.fingerprint, original["id"], "keep_comparison", "", uuid4().hex,
        )
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute("ALTER TABLE campaign_buyer_corrections DROP COLUMN comparison_identity")
        (self.drafts.media_dir / audiobook.preview).write_bytes(b"Changed only the ad preview")
        self.performance = CampaignPerformance(self.drafts, self.viewer)
        updated = approve_and_review()
        self.assertNotEqual(updated["fingerprint"], original["fingerprint"])
        self.assertEqual(updated["proposal"]["correction"], correction)
        self.assertEqual(updated["proposal"]["title"], "Test how the ad sets up the comparison")

    def test_instruction_edit_preserves_the_take_constraint_only_until_it_is_superseded(self):
        editing, audiobook = EXAMPLES

        def approve_and_review():
            fingerprint = self.drafts.review_package(self.campaign, 2)["fingerprint"]
            approved = self.drafts.approve_package(self.campaign, 2, fingerprint)
            content = package_fingerprint(approved["package"]["groups"][0]["content"])
            for _ in range(3):
                self.viewer.open_example(editing.creative_ref, content_fingerprint=content)
            return self.performance.review(self.campaign, 2, fingerprint, "balanced")

        original = approve_and_review()
        correction = self.performance.save_correction(
            self.campaign, 2, self.fingerprint, original["id"], "keep_takes", "", uuid4().hex,
        )
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute("ALTER TABLE campaign_buyer_corrections DROP COLUMN takes_identity")
        self.performance = CampaignPerformance(self.drafts, self.viewer)
        with patch("campaign_agent.handoff.EXAMPLES", (replace(editing, instruction="Listen to both takes."), audiobook)):
            updated = approve_and_review()
        self.assertNotEqual(updated["fingerprint"], original["fingerprint"])
        self.assertEqual(updated["proposal"].get("correction"), correction)
        self.assertEqual(updated["proposal"]["title"], "Test clearer comparison instructions")

        replacement = self.performance.save_correction(
            self.campaign, 2, self.fingerprint, original["id"], "keep_comparison", "", uuid4().hex,
        )
        self.assertEqual(replacement["kind"], "keep_comparison")
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            # Older keep-comparison records had no takes identity even with all columns present.
            db.execute("UPDATE campaign_buyer_corrections SET takes_identity = NULL WHERE id = ?", (replacement["id"],))
        self.performance = CampaignPerformance(self.drafts, self.viewer)
        with patch("campaign_agent.handoff.EXAMPLES", (replace(editing, instruction="Listen to both takes."), audiobook)):
            refreshed = approve_and_review()
            current = self.performance.read(self.campaign, 2, refreshed["fingerprint"])
        self.assertNotIn("correction", refreshed["proposal"])
        self.assertEqual(refreshed["proposal"]["title"], "Test a shorter second take")
        self.assertIsNone(current["correction"])

    def test_older_review_without_content_attribution_is_not_restored(self):
        self.drafts.approve_package(self.campaign, 2, self.fingerprint)
        review = self.performance.review(self.campaign, 2, self.fingerprint, "balanced")
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute(
                "UPDATE campaign_performance_reviews SET snapshot = "
                "json_remove(snapshot, '$.local_viewer_activity.attribution') WHERE id = ?", (review["id"],),
            )
        self.assertIsNone(self.performance.read(self.campaign, 2, self.fingerprint)["review"])

    def test_existing_database_keeps_old_visits_unattributed(self):
        editing = EXAMPLES[0]
        original_visit = self.viewer.open_example(editing.creative_ref)["visit_id"]
        self.complete(editing.creative_ref, editing.ref, original_visit)
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute("ALTER TABLE viewer_visits DROP COLUMN content_fingerprint")

        reopened = ViewerMeasurement(self.drafts.path)
        self.assertTrue(reopened.open_example(editing.creative_ref, visit_id=original_visit)["complete"])
        self.drafts.approve_package(self.campaign, 2, self.fingerprint)
        result = CampaignPerformance(self.drafts, reopened).review(self.campaign, 2, self.fingerprint, "balanced")
        row = result["local_viewer_activity"]["rows"][0]
        self.assertEqual((row["arrivals"], row["completions"], row["unattributed_arrivals"]), (0, 0, 1))

    def test_review_rejects_an_edit_after_evidence_collection_starts(self):
        self.drafts.approve_package(self.campaign, 2, self.fingerprint)
        sample_report = self.performance.reporting.snapshot

        def report_after_edit(scenario, creatives):
            current = self.drafts.read()
            placements = [{**current["placements"][0], "title": "Edited placement"}, current["placements"][1]]
            self.drafts.save({"campaign_id": self.campaign, "revision": 2, "placements": placements})
            return sample_report(scenario, creatives)

        with patch.object(self.performance.reporting, "snapshot", side_effect=report_after_edit):
            with self.assertRaisesRegex(PackageConflict, "The package has changed"):
                self.performance.review(self.campaign, 2, self.fingerprint, "balanced")
        self.assertEqual(self.drafts.read()["revision"], 3)
        self.assertIsNone(self.performance.read(self.campaign, 2, self.fingerprint)["review"])

        latest = self.drafts.review_package(self.campaign, 3)["fingerprint"]
        self.drafts.approve_package(self.campaign, 3, latest)
        self.assertEqual(self.performance.review(self.campaign, 3, latest, "balanced")["revision"], 3)

    def test_review_rejects_media_changed_after_evidence_collection_starts(self):
        self.drafts.approve_package(self.campaign, 2, self.fingerprint)
        sample_report = self.performance.reporting.snapshot

        def report_after_media_change(scenario, creatives):
            (self.drafts.media_dir / EXAMPLES[0].preview).write_bytes(b"Revised preview")
            return sample_report(scenario, creatives)

        with patch.object(self.performance.reporting, "snapshot", side_effect=report_after_media_change):
            with self.assertRaisesRegex(PackageConflict, "The package has changed"):
                self.performance.review(self.campaign, 2, self.fingerprint, "balanced")
        self.assertEqual(self.drafts.read()["revision"], 2)
        self.assertIsNone(self.performance.read(self.campaign, 2, self.fingerprint)["review"])


if __name__ == "__main__":
    unittest.main()
