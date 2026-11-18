from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from campaign_agent.adapters.sqlite_drafts import SQLiteDraftStorage, SQLiteDraftStore
from campaign_agent.bootstrap.runtime import create_drafts as CampaignDrafts
from campaign_agent.ports.storage_errors import StorageError


class SQLiteDraftStoreTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "drafts.sqlite3"
        CampaignDrafts(self.path, live=True)
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.store = SQLiteDraftStore(self.db)

    def test_owned_units_reject_read_writes_and_close_their_records(self):
        storage = SQLiteDraftStorage(self.path)
        with storage.read() as read:
            self.assertIsNotNone(read.read_snapshot("tts-catalog", 1))
            with self.assertRaises(StorageError) as readonly:
                read.append_snapshot("tts-catalog", 2, "{}")
            self.assertEqual(readonly.exception.kind, "read_only")
        with self.assertRaises(StorageError) as closed:
            read.read_snapshot("tts-catalog", 1)
        self.assertEqual(closed.exception.kind, "closed")
        self.assertIsNone(self.store.read_snapshot("tts-catalog", 2))

    def test_owned_writes_require_explicit_commit(self):
        storage = SQLiteDraftStorage(self.path)
        snapshot = ' {"revision": 2} '
        with storage.write() as discarded:
            discarded.drafts.append_snapshot("tts-catalog", 2, snapshot)
        self.assertIsNone(self.store.read_snapshot("tts-catalog", 2))
        with self.assertRaises(StorageError) as closed:
            discarded.commit()
        self.assertEqual(closed.exception.kind, "closed")

        with storage.write() as accepted:
            accepted.drafts.append_snapshot("tts-catalog", 2, snapshot)
            with self.assertRaises(StorageError) as duplicate:
                accepted.drafts.append_snapshot("tts-catalog", 2, "{}")
            self.assertEqual(duplicate.exception.kind, "unavailable")
            accepted.commit()
            with self.assertRaises(StorageError) as closed:
                accepted.drafts.read_snapshot("tts-catalog", 2)
            self.assertEqual(closed.exception.kind, "closed")
        self.assertEqual(self.store.read_snapshot("tts-catalog", 2), snapshot)

    def test_lost_commit_confirmation_is_safe_and_can_be_read_back(self):
        class LateFailure(sqlite3.Connection):
            def commit(self):
                super().commit()
                raise sqlite3.OperationalError("private diagnostic")

        storage = SQLiteDraftStorage(self.path)
        native_connect = sqlite3.connect
        with patch("campaign_agent.adapters.sqlite_drafts.sqlite3.connect",
                   side_effect=lambda path: native_connect(path, factory=LateFailure)):
            with self.assertRaises(StorageError) as failed:
                with storage.write() as unit:
                    unit.drafts.append_snapshot("tts-catalog", 2, "{}")
                    unit.commit()
        self.assertEqual(failed.exception.kind, "commit_unknown")
        self.assertNotIn("private diagnostic", str(failed.exception))
        with storage.read() as reopened:
            self.assertEqual(reopened.read_snapshot("tts-catalog", 2), "{}")

    def test_raw_history_latest_exact_and_missing_survive_reopen(self):
        historical = ' \n{ "title" : "Café é · 朗読 🎙", "escaped": "\\u00e9" }\n'
        latest = '{"title":"後の版", "placements" : [ ]}\n\t'
        self.assertFalse(self.store.has_revisions("history"))
        self.assertIsNone(self.store.read_snapshot("history"))
        self.assertIsNone(self.store.read_snapshot("history", 2))
        self.store.append_snapshot("history", 10, latest)
        self.store.append_snapshot("history", 2, historical)
        self.store.append_snapshot("sibling", 99, ' {"other":true} ')
        self.assertTrue(self.store.has_revisions("history"))
        self.assertFalse(self.store.has_revisions("History"))
        self.assertEqual(self.store.read_snapshot("history"), latest)
        self.assertEqual(self.store.read_snapshot("history", 2).encode("utf-8"), historical.encode("utf-8"))
        self.assertIsNone(self.store.read_snapshot("history", 3))
        self.assertIsNone(self.store.read_snapshot("history", 99))
        self.db.commit()
        with closing(sqlite3.connect(self.path)) as reopened:
            store = SQLiteDraftStore(reopened)
            self.assertEqual(store.read_snapshot("history"), latest)
            self.assertEqual(store.read_snapshot("history", 2), historical)
            self.assertEqual(store.read_snapshot("sibling"), ' {"other":true} ')

    def test_duplicate_append_raises_native_error_and_keeps_original_text(self):
        original = ' { "revision": 1, "title": "原文" }\n'
        self.store.append_snapshot("history", 1, original)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.append_snapshot("history", 1, '{"replacement":true}')
        self.assertEqual(self.store.read_snapshot("history", 1), original)
        self.assertTrue(self.db.in_transaction)
        self.assertEqual(self.db.execute("SELECT 1").fetchone(), (1,))
        self.db.rollback()
        self.assertFalse(self.store.has_revisions("history"))

    def test_present_legacy_null_snapshot_is_not_a_missing_revision(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE campaign_revisions (campaign_id TEXT, revision INTEGER, snapshot TEXT)")
            db.execute("INSERT INTO campaign_revisions VALUES ('legacy', 1, NULL)")
            store = SQLiteDraftStore(db)
            self.assertIsNone(store.read_snapshot("missing"))
            self.assertTrue(store.has_revisions("legacy"))
            with self.assertRaises(TypeError):
                store.read_snapshot("legacy")
            with self.assertRaises(TypeError):
                store.read_snapshot("legacy", 1)

    def test_caller_controls_visibility_rollback_and_sibling_commit(self):
        self.db.execute("CREATE TABLE draft_markers (label TEXT PRIMARY KEY)")
        with closing(sqlite3.connect(self.path)) as observer:
            outside = SQLiteDraftStore(observer)
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("INSERT INTO draft_markers VALUES ('rolled back')")
            self.store.append_snapshot("history", 1, ' {"uncommitted":true} ')
            self.assertTrue(self.store.has_revisions("history"))
            self.assertEqual(self.store.read_snapshot("history"), ' {"uncommitted":true} ')
            self.assertFalse(outside.has_revisions("history"))
            self.assertIsNone(outside.read_snapshot("history"))
            self.assertEqual(observer.execute("SELECT * FROM draft_markers").fetchall(), [])
            self.db.rollback()
            self.assertFalse(self.store.has_revisions("history"))
            self.assertEqual(self.db.execute("SELECT * FROM draft_markers").fetchall(), [])

            self.db.execute("BEGIN IMMEDIATE")
            self.store.append_snapshot("history", 1, ' {"committed":true} ')
            self.db.execute("INSERT INTO draft_markers VALUES ('committed')")
            self.assertIsNone(outside.read_snapshot("history"))
            self.db.commit()
            self.assertEqual(outside.read_snapshot("history"), ' {"committed":true} ')
            self.assertEqual(observer.execute("SELECT * FROM draft_markers").fetchall(), [('committed',)])
        with closing(sqlite3.connect(self.path)) as reopened:
            self.assertEqual(SQLiteDraftStore(reopened).read_snapshot("history"), ' {"committed":true} ')
            self.assertEqual(reopened.execute("SELECT * FROM draft_markers").fetchall(), [('committed',)])

    def test_catalog_facts_require_exact_client_brand_campaign_and_reference(self):
        scopes = (
            ("client-a", "brand-a", "campaign-a"),
            ("client-b", "brand-b", "campaign-b"),
            ("client-a", "brand-b", "campaign-c"),
            ("client-a", "brand-a", "campaign-d"),
        )
        for index, scope in enumerate(scopes):
            ref = str(index) * 32
            self.db.execute("INSERT INTO catalog_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (ref, "SAMPLE00001", "朗読 · licensed", "licensed", "License A", *scope))
            self.db.execute("INSERT INTO placement_catalog_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (ref, *scope, "SAMPLE00002", "Editing · supplied", "creator_supplied", "Creator B"))
        families = (
            (self.store.live_catalog_entry, ("SAMPLE00001", "朗読 · licensed", "licensed", "License A")),
            (self.store.placement_catalog_entry,
             ("SAMPLE00002", "Editing · supplied", "creator_supplied", "Creator B")),
        )
        for lookup, expected in families:
            for index, scope in enumerate(scopes):
                with self.subTest(family=lookup.__name__, scope=scope):
                    self.assertEqual(lookup(*scope, str(index) * 32), expected)
            for scope, ref in (
                (("client-b", "brand-a", "campaign-a"), "0" * 32),
                (("client-a", "brand-b", "campaign-a"), "0" * 32),
                (scopes[3], "0" * 32),
                (scopes[0], "1" * 32),
                (scopes[0], "f" * 32),
                (("Client-a", "brand-a", "campaign-a"), "0" * 32),
                (scopes[0], "' OR 1=1 --"),
            ):
                with self.subTest(family=lookup.__name__, wrong_scope=scope, ref=ref):
                    self.assertIsNone(lookup(*scope, ref))
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()
        for lookup, _ in families:
            self.assertIsNone(lookup(*scopes[0], "0" * 32))

    def test_legacy_placement_fact_retains_missing_source_reference(self):
        self.db.execute("INSERT INTO placement_catalog_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        ("0" * 32, "client-a", "brand-a", "campaign-a", "SAMPLE00001", "Legacy", "synthetic", None))
        self.assertEqual(self.store.placement_catalog_entry("client-a", "brand-a", "campaign-a", "0" * 32),
                         ("SAMPLE00001", "Legacy", "synthetic", None))
