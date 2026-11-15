from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from scripts.campaign_drafts import CampaignDrafts, StaleDraft


EDITING = {"id": "SAMPLE00001", "title": "Editing tutorial", "creative": "video-editing", "source": "synthetic"}
BOOK = {"id": "SAMPLE00002", "title": "Narration tutorial", "creative": "audiobook", "source": "sample_search"}


class CampaignDraftTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "drafts.sqlite3"
        self.drafts = CampaignDrafts(self.path, live=False)

    def save(self, revision, placements):
        return self.drafts.save({"campaign_id": "tts-sample", "revision": revision, "placements": placements})

    def test_reopen_preserves_both_groups_and_frozen_revision(self):
        seed = self.drafts.read()
        self.assertEqual(set(seed["brief"]["contexts"]), {"video-editing", "audiobook"})
        first = self.save(1, [EDITING, BOOK])
        self.assertEqual(first["revision"], 2)
        self.assertEqual(first["placements"], [EDITING, BOOK])
        reopened = CampaignDrafts(self.path, live=False)
        self.assertEqual(reopened.read(), first)
        cleared = self.save(2, [])
        self.assertEqual(cleared["placements"], [])
        self.assertEqual(reopened.read(2), first)
        self.assertEqual(reopened.read(1), seed)
        self.assertEqual(cleared["brief"], seed["brief"])
        self.assertEqual(cleared["policy"], seed["policy"])

    def test_retry_reuses_revision_and_stale_edit_leaves_it_intact(self):
        first = self.save(1, [EDITING])
        self.assertEqual(self.save(1, [EDITING]), first)
        self.assertEqual(self.save(2, [EDITING]), first)
        with self.assertRaises(StaleDraft) as conflict:
            self.save(1, [BOOK])
        self.assertEqual(conflict.exception.latest, first)
        self.assertEqual(self.drafts.read(), first)

    def test_rejects_invalid_placement_without_partial_save(self):
        for invalid in (
            {**BOOK, "source": "youtube_search"},
            {**BOOK, "creative": "unknown"},
            {**BOOK, "id": EDITING["id"]},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.save(1, [EDITING, invalid])
        self.assertEqual(self.drafts.read()["placements"], [])
        self.assertIsNone(self.drafts.read(2))

    def test_borrowed_connection_leaves_commit_and_rollback_to_the_caller(self):
        payload = {"campaign_id": "tts-sample", "revision": 1, "placements": [EDITING]}
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE draft_markers (label TEXT PRIMARY KEY)")
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO draft_markers VALUES ('rolled back')")
            self.drafts.save(payload, connection=db)
            self.assertEqual(self.drafts.read()["revision"], 1)
            db.rollback()
            self.assertEqual(db.execute("SELECT * FROM draft_markers").fetchall(), [])
            self.assertEqual(self.drafts.read()["revision"], 1)

            db.execute("BEGIN IMMEDIATE")
            saved = self.drafts.save(payload, connection=db)
            db.execute("INSERT INTO draft_markers VALUES ('committed')")
            self.assertEqual(self.drafts.read()["revision"], 1)
            db.commit()
            self.assertEqual(db.execute("SELECT * FROM draft_markers").fetchall(), [('committed',)])
        reopened = CampaignDrafts(self.path, live=False)
        self.assertEqual(reopened.read(), saved)
        self.assertIsNone(reopened.read(3))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT * FROM draft_markers").fetchall(), [('committed',)])

    def test_write_unit_rolls_back_post_save_failure_and_commits_sibling_records(self):
        payload = {"campaign_id": "tts-sample", "revision": 1, "placements": [EDITING]}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE draft_markers (label TEXT PRIMARY KEY)")
            seed = db.execute("SELECT * FROM campaign_revisions").fetchall()
        for failure in (RuntimeError, KeyboardInterrupt):
            with self.subTest(failure=failure), self.assertRaises(failure):
                with self.drafts.write_unit() as db:
                    self.drafts.save(payload, connection=db)
                    db.execute("INSERT INTO draft_markers VALUES ('interrupted')")
                    raise failure('Interrupted after draft and sibling write')
            with closing(sqlite3.connect(self.path)) as db:
                self.assertEqual(db.execute("SELECT * FROM campaign_revisions").fetchall(), seed)
                self.assertEqual(db.execute("SELECT * FROM draft_markers").fetchall(), [])
        with self.drafts.write_unit() as db:
            saved = self.drafts.save(payload, connection=db)
            db.execute("INSERT INTO draft_markers VALUES ('committed')")
        reopened = CampaignDrafts(self.path, live=False)
        self.assertEqual(reopened.read(), saved)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT * FROM campaign_revisions WHERE revision=1").fetchall(), seed)
            self.assertEqual(db.execute("SELECT * FROM draft_markers").fetchall(), [('committed',)])

    def test_catalog_and_sample_campaigns_are_separate(self):
        self.save(1, [EDITING])
        catalog = CampaignDrafts(self.path, live=True)
        self.assertEqual(catalog.read()["placements"], [])
        entry = {
            "video_id": EDITING["id"], "description": EDITING["title"], "source": "licensed",
            "source_reference": "Creator handoff 17",
        }
        with self.assertRaises(ValueError):
            catalog.register_catalog([{**entry, "source_reference": ""}])
        ref = catalog.register_catalog([entry])[EDITING["id"]]
        catalog = CampaignDrafts(self.path, live=True)
        licensed = {**EDITING, "source": "licensed", "catalog_ref": ref}
        payload = {"campaign_id": "tts-catalog", "revision": 1, "placements": [licensed]}
        for invalid in ({**payload, "campaign_id": "tts-sample"}, {**payload, "placements": [EDITING]}):
            with self.assertRaises(ValueError):
                catalog.save(invalid)
        self.assertEqual(catalog.save(payload)["placements"], [{**licensed, "source_reference": "Creator handoff 17"}])
        self.assertEqual(self.drafts.read()["placements"], [EDITING])

    def test_browser_labels_cannot_register_or_replace_catalog_evidence(self):
        catalog = CampaignDrafts(self.path, live=True)
        ref = catalog.register_catalog([{
            "video_id": EDITING["id"], "description": EDITING["title"], "source": "creator_supplied",
            "source_reference": "Creator handoff 17",
        }])[EDITING["id"]]
        attempts = (
            {**BOOK, "source": "licensed"},
            {**BOOK, "source": "licensed", "catalog_ref": "0" * 32},
            {**BOOK, "source": "creator_supplied", "catalog_ref": ref},
            {**EDITING, "source": "licensed", "catalog_ref": ref},
            {**EDITING, "source": "creator_supplied", "title": "Search title", "catalog_ref": ref},
        )
        for row in attempts:
            with self.subTest(row=row), self.assertRaises(ValueError):
                catalog.save({"campaign_id": "tts-catalog", "revision": 1, "placements": [row]})
        self.assertIsNone(catalog.read(2))
