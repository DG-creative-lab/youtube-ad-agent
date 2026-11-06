from dataclasses import replace
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

    def test_older_review_without_content_attribution_is_not_restored(self):
        self.drafts.approve_package(self.campaign, 2, self.fingerprint)
        review = self.performance.review(self.campaign, 2, self.fingerprint, "balanced")
        with sqlite3.connect(self.drafts.path) as db:
            db.execute(
                "UPDATE campaign_performance_reviews SET snapshot = "
                "json_remove(snapshot, '$.local_viewer_activity.attribution') WHERE id = ?", (review["id"],),
            )
        self.assertIsNone(self.performance.read(self.campaign, 2, self.fingerprint)["review"])

    def test_existing_database_keeps_old_visits_unattributed(self):
        editing = EXAMPLES[0]
        original_visit = self.viewer.open_example(editing.creative_ref)["visit_id"]
        self.complete(editing.creative_ref, editing.ref, original_visit)
        with sqlite3.connect(self.drafts.path) as db:
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
