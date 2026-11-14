from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from campaign_agent.creatives import EXAMPLES
from scripts.campaign_drafts import CampaignDrafts, PackageConflict


class PackageHandoffTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "draft.sqlite"
        self.media_dir = self.path.parent / "media"
        self.media_dir.mkdir()
        for example in EXAMPLES:
            for name in {example.preview, *(name for _, _, name in example.takes)}:
                (self.media_dir / name).write_bytes(f"sample {name}".encode())
        self.drafts = CampaignDrafts(self.path, live=False, media_dir=self.media_dir)
        self.placements = [
            {"id": "SAMPLE00001", "title": "Voiceover editing", "creative": "video-editing",
             "source": "synthetic"},
            {"id": "SAMPLE00002", "title": "Audiobook production", "creative": "audiobook",
             "source": "synthetic"},
        ]

    def test_approval_and_export_are_bound_to_the_reviewed_revision(self):
        drafts = self.drafts
        campaign_id = drafts.campaign_id
        drafts.save({"campaign_id": campaign_id, "revision": 1, "placements": self.placements})
        reviewed = drafts.review_package(campaign_id, 2)
        fingerprint = reviewed["fingerprint"]
        with self.assertRaisesRegex(PackageConflict, "Approve this revision"):
            drafts.export_setup(campaign_id, 2, fingerprint)
        with self.assertRaisesRegex(PackageConflict, "package has changed"):
            drafts.approve_package(campaign_id, 2, "0" * 64)

        approved = drafts.approve_package(campaign_id, 2, fingerprint)
        reopened = CampaignDrafts(self.path, live=False, media_dir=self.media_dir)
        self.assertEqual(reopened.approve_package(campaign_id, 2, fingerprint), approved)
        setup = reopened.export_setup(campaign_id, 2, fingerprint)
        self.assertEqual(setup["approval"], approved["approval"])
        self.assertEqual(setup["revision"], 2)
        self.assertEqual(setup["data_label"], "Fictional placements for an offline sample")
        self.assertEqual(setup["groups"][0]["placements"], [
            {"demo_id": "SAMPLE00001", "title": "Voiceover editing", "source": "synthetic",
             "label": "Fictional placement"},
        ])
        self.assertTrue(setup["groups"][0]["viewer_path"].startswith("/viewer?ad=editing-voiceover-v1&content="))
        self.assertEqual(setup["groups"][0]["creative_version"], "editing-voiceover-v1")

        edited = [{**self.placements[0], "title": "Edited placement"}, self.placements[1]]
        reopened.save({"campaign_id": campaign_id, "revision": 2, "placements": edited})
        for action in (reopened.approve_package, reopened.export_setup):
            with self.assertRaisesRegex(PackageConflict, "package has changed"):
                action(campaign_id, 2, fingerprint)
        latest = reopened.review_package(campaign_id, 3)
        self.assertIsNone(latest["approval"])
        with self.assertRaisesRegex(PackageConflict, "Approve this revision"):
            reopened.export_setup(campaign_id, 3, latest["fingerprint"])
        self.assertEqual(reopened.review_package(campaign_id, 2)["approval"], approved["approval"])
        self.assertEqual(reopened.read_approved_package(campaign_id, 2, fingerprint)["package"], approved["package"])

    def test_review_names_missing_groups_and_blocks_approval(self):
        drafts = self.drafts
        campaign_id = drafts.campaign_id
        for index, title in ((0, "Audiobook production"), (1, "Video editing")):
            with self.subTest(missing=title):
                saved = drafts.save({"campaign_id": campaign_id, "revision": index + 1,
                                     "placements": [self.placements[index]]})
                revision = saved["revision"]
                reviewed = drafts.review_package(campaign_id, revision)
                self.assertEqual(reviewed["blockers"], [f"Add placements for {title}."])
                with self.assertRaisesRegex(PackageConflict, f"Add placements for {title}"):
                    drafts.approve_package(campaign_id, revision, reviewed["fingerprint"])

    def test_edited_text_or_media_requires_new_approval_for_same_revision(self):
        drafts = self.drafts
        campaign_id = drafts.campaign_id
        drafts.save({"campaign_id": campaign_id, "revision": 1, "placements": self.placements})
        fingerprint = drafts.review_package(campaign_id, 2)["fingerprint"]
        approved = drafts.approve_package(campaign_id, 2, fingerprint)

        def assert_changed():
            changed = drafts.review_package(campaign_id, 2)
            self.assertNotEqual(changed["fingerprint"], fingerprint)
            self.assertIsNone(changed["approval"])
            self.assertEqual(drafts.read_approved_package(campaign_id, 2, fingerprint)["package"], approved["package"])
            with self.assertRaisesRegex(PackageConflict, "package has changed"):
                drafts.export_setup(campaign_id, 2, fingerprint)
            return changed

        example, second = EXAMPLES
        with patch("campaign_agent.handoff.EXAMPLES", (replace(example, passage="Edited script."), second)):
            assert_changed()
        for name in (second.preview, example.takes[1][2]):
            with self.subTest(media=name):
                asset = self.media_dir / name
                original = asset.read_bytes()
                asset.write_bytes(b"replacement media")
                assert_changed()
                asset.write_bytes(original)

        (self.media_dir / second.preview).unlink()
        changed = assert_changed()
        self.assertEqual(changed["blockers"], ["Prepare the preview and comparison media for Audiobook production."])
        with self.assertRaisesRegex(PackageConflict, "Prepare the preview and comparison media"):
            drafts.approve_package(campaign_id, 2, changed["fingerprint"])

    def test_legacy_approval_is_listed_without_inventing_a_snapshot(self):
        campaign_id = self.drafts.campaign_id
        fingerprint = "a" * 64
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("ALTER TABLE campaign_package_approvals DROP COLUMN snapshot")
            db.execute(
                "INSERT INTO campaign_package_approvals VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("local-client", "tts-demo", campaign_id, 1, fingerprint, "local-operator", "2026-11-06T13:00:00+00:00"),
            )
        reopened = CampaignDrafts(self.path, live=False, media_dir=self.media_dir)
        history = reopened.review_package(campaign_id, 1)["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["fingerprint"], fingerprint)
        self.assertFalse(history[0]["snapshot_available"])
        self.assertIsNone(reopened.read_approved_package(campaign_id, 1, fingerprint))


if __name__ == "__main__":
    unittest.main()
