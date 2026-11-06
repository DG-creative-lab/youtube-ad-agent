"""Local campaign draft commands and their SQLite storage."""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from campaign_agent.access import LOCAL_BRAND, LOCAL_OPERATOR
from campaign_agent.handoff import MEDIA_DIR, package_blockers, package_fingerprint, sample_package


VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
MAX_PLACEMENTS = 2400
MAX_DRAFT_BYTES = 2_000_000
CATALOG_SOURCES = {"creator_supplied", "licensed"}
DEFAULT_DRAFT_PATH = Path(__file__).resolve().parents[1] / ".local/campaign-drafts.sqlite3"
BRIEF = {
    "id": "tts-contexts",
    "revision": 1,
    "title": "Text to Speech · YouTube test",
    "goal": "Compare how voice delivery fits two different viewing contexts.",
    "approved_claims": [
        "ElevenLabs Text to Speech generates spoken audio from written text.",
    ],
    "contexts": {
        "video-editing": {
            "title": "Video editing",
            "creative_ref": "editing-voiceover",
            "destination_ref": "editing-comparison",
            "planned_assets": ["original-editing-clip", "editing-narration-takes"],
        },
        "audiobook": {
            "title": "Audiobook production",
            "creative_ref": "audiobook-reading",
            "destination_ref": "audiobook-comparison",
            "planned_assets": ["original-story-passage", "audiobook-narration-takes"],
        },
    },
}
POLICY = {
    "id": "local-campaign-rules",
    "revision": 1,
    "rules": [
        "Use original or permitted footage, text and audio.",
        "Keep fictional placements separate from real catalog placements.",
        "Confirm targeting in Google Ads before launch.",
    ],
}


class StaleDraft(ValueError):
    """A later revision already exists for this campaign."""

    def __init__(self, latest):
        super().__init__("A newer draft exists. Review your changes against it before saving.")
        self.latest = latest


class PackageConflict(ValueError):
    """The reviewed package is stale or lacks a matching approval."""


class CampaignDrafts:
    def __init__(self, path, live, operator=LOCAL_OPERATOR, *, media_dir=MEDIA_DIR):
        operator.require_brand(LOCAL_BRAND)
        self.operator = operator
        self.path = path
        self.media_dir = media_dir
        self.live = live
        self.campaign_id = "tts-catalog" if live else "tts-sample"
        self.sources = CATALOG_SOURCES if live else {"sample_search", "synthetic"}
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                CREATE TABLE IF NOT EXISTS campaign_revisions (
                    campaign_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    snapshot TEXT NOT NULL,
                    PRIMARY KEY (campaign_id, revision)
                )
            """)
            if not live:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS campaign_package_approvals (
                        client_id TEXT NOT NULL,
                        brand_id TEXT NOT NULL,
                        campaign_id TEXT NOT NULL,
                        revision INTEGER NOT NULL,
                        fingerprint TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        approved_at TEXT NOT NULL,
                        snapshot TEXT,
                        PRIMARY KEY (client_id, brand_id, campaign_id, revision, fingerprint)
                    )
                """)
                columns = db.execute("PRAGMA table_info(campaign_package_approvals)").fetchall()
                if "snapshot" not in {column[1] for column in columns}:
                    db.execute("ALTER TABLE campaign_package_approvals ADD COLUMN snapshot TEXT")
            if live:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS catalog_entries (
                        ref TEXT PRIMARY KEY,
                        video_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        source TEXT NOT NULL,
                        source_reference TEXT NOT NULL,
                        UNIQUE (video_id, title, source, source_reference)
                    )
                """)
            seed = {
                "campaign_id": self.campaign_id,
                "revision": 1,
                "brief": BRIEF,
                "policy": POLICY,
                "placements": [],
            }
            db.execute(
                "INSERT OR IGNORE INTO campaign_revisions VALUES (?, ?, ?)",
                (self.campaign_id, 1, json.dumps(seed)),
            )

    def _read(self, db, revision=None):
        if revision is None:
            row = db.execute(
                "SELECT snapshot FROM campaign_revisions WHERE campaign_id = ? "
                "ORDER BY revision DESC LIMIT 1",
                (self.campaign_id,),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT snapshot FROM campaign_revisions WHERE campaign_id = ? AND revision = ?",
                (self.campaign_id, revision),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def read(self, revision=None):
        with closing(sqlite3.connect(self.path)) as db:
            return self._read(db, revision)

    def _package_scope(self, campaign_id, revision):
        self.operator.require_brand(LOCAL_BRAND)
        if (self.live or campaign_id != self.campaign_id
                or type(revision) is not int or not 1 <= revision < 2**63):
            raise ValueError("Choose a valid sample campaign revision.")
        return LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, campaign_id

    def _package_review(self, db, campaign_id, revision):
        scope = self._package_scope(campaign_id, revision)
        latest = self._read(db)
        draft = latest if latest["revision"] == revision else self._read(db, revision)
        if draft is None:
            raise ValueError("Campaign revision unavailable.")
        package = sample_package(draft, self.media_dir)
        fingerprint = package_fingerprint(package)
        key = (*scope, revision, fingerprint)
        row = db.execute(
            "SELECT actor_id, approved_at FROM campaign_package_approvals WHERE "
            "client_id = ? AND brand_id = ? AND campaign_id = ? AND revision = ? AND fingerprint = ? "
            "AND snapshot IS NOT NULL",
            key,
        ).fetchone()
        approval = {"actor_id": row[0], "approved_at": row[1]} if row else None
        return {"package": package, "fingerprint": fingerprint, "approval": approval,
                "current_revision": latest["revision"], "blockers": package_blockers(package)}, key

    def _approval_history(self, db, scope):
        return [
            {"revision": revision, "fingerprint": fingerprint, "approved_at": approved_at,
             "snapshot_available": bool(available)}
            for revision, fingerprint, approved_at, available in db.execute(
                "SELECT revision, fingerprint, approved_at, snapshot IS NOT NULL "
                "FROM campaign_package_approvals WHERE client_id = ? AND brand_id = ? AND campaign_id = ? "
                "ORDER BY revision DESC, approved_at DESC, fingerprint", scope,
            )
        ]

    def read_approved_package(self, campaign_id, revision, fingerprint):
        scope = self._package_scope(campaign_id, revision)
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT actor_id, approved_at, snapshot FROM campaign_package_approvals "
                "WHERE client_id = ? AND brand_id = ? AND campaign_id = ? AND revision = ? AND fingerprint = ?",
                (*scope, revision, fingerprint),
            ).fetchone()
        if row is None or row[2] is None:
            return None
        return {"fingerprint": fingerprint, "approval": {"actor_id": row[0], "approved_at": row[1]},
                "package": json.loads(row[2])}

    def review_package(self, campaign_id, revision):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN")
            review, key = self._package_review(db, campaign_id, revision)
            review["history"] = self._approval_history(db, key[:3])
            return review

    def _require_current_package(self, review, revision, fingerprint):
        if review["current_revision"] != revision or review["fingerprint"] != fingerprint:
            raise PackageConflict("The package has changed. Load and review the latest draft.")
        if review["blockers"]:
            raise PackageConflict(" ".join(review["blockers"]))

    def approve_package(self, campaign_id, revision, fingerprint):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            review, key = self._package_review(db, campaign_id, revision)
            self._require_current_package(review, revision, fingerprint)
            if review["approval"] is None:
                approved_at = datetime.now(timezone.utc).isoformat()
                db.execute(
                    "INSERT INTO campaign_package_approvals "
                    "(client_id, brand_id, campaign_id, revision, fingerprint, actor_id, approved_at, snapshot) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (*key, self.operator.id, approved_at, json.dumps(review["package"])),
                )
                review["approval"] = {"actor_id": self.operator.id, "approved_at": approved_at}
            review["history"] = self._approval_history(db, key[:3])
            return review

    def require_approved_package(self, db, campaign_id, revision, fingerprint):
        """Validate approval in the caller's transaction and return the reviewed package."""
        review, _ = self._package_review(db, campaign_id, revision)
        self._require_current_package(review, revision, fingerprint)
        if review["approval"] is None:
            raise PackageConflict("Approve this revision before continuing.")
        return review

    def export_setup(self, campaign_id, revision, fingerprint):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN")
            review = self.require_approved_package(db, campaign_id, revision, fingerprint)
            return {
                "handoff": "Manual Google Ads setup example",
                "instructions": "Use this as a walkthrough. Replace fictional placements with verified targets "
                                "and replace local preview and viewer paths before a live campaign.",
                "approval": review["approval"],
                "fingerprint": fingerprint,
                **review["package"],
            }

    def register_catalog(self, rows):
        """Record independently supplied entries admitted by the local CLI."""
        entries = []
        for row in rows:
            reference = row.get("source_reference")
            if (not self.live or row["source"] not in CATALOG_SOURCES
                    or not isinstance(reference, str) or not reference.strip() or len(reference) > 500):
                raise ValueError("Catalog registration requires a creator-supplied or licensed source and a source_reference of up to 500 characters for each entry.")
            entries.append((row["video_id"], row["description"], row["source"], reference.strip()))

        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany(
                "INSERT OR IGNORE INTO catalog_entries VALUES (?, ?, ?, ?, ?)",
                ((uuid4().hex, *entry) for entry in entries),
            )
            return {
                entry[0]: db.execute(
                    "SELECT ref FROM catalog_entries WHERE video_id = ? AND title = ? "
                    "AND source = ? AND source_reference = ?", entry,
                ).fetchone()[0]
                for entry in entries
            }

    def save(self, payload, *, connection=None):
        if not isinstance(payload, dict) or set(payload) != {"campaign_id", "revision", "placements"}:
            raise ValueError("Send a campaign ID, expected revision and placements.")
        expected = payload["revision"]
        if (payload["campaign_id"] != self.campaign_id
                or type(expected) is not int or not 1 <= expected < 2**63):
            raise ValueError("The campaign ID or revision is invalid.")
        rows = payload["placements"]
        if not isinstance(rows, list) or len(rows) > MAX_PLACEMENTS:
            raise ValueError(f"Save up to {MAX_PLACEMENTS} placements at a time.")

        if connection is not None:
            return self._save(db=connection, expected=expected, rows=rows)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            return self._save(db, expected, rows)

    def _save(self, db, expected, rows):
        current = self._read(db)
        placements = self._validate_placements(db, rows, current["brief"]["contexts"])
        revision = current["revision"]
        if expected != revision:
            if expected == revision - 1 and placements == current["placements"]:
                return current
            raise StaleDraft(current)
        if placements == current["placements"]:
            return current
        saved = {**current, "revision": revision + 1, "placements": placements}
        db.execute(
            "INSERT INTO campaign_revisions VALUES (?, ?, ?)",
            (self.campaign_id, saved["revision"], json.dumps(saved)),
        )
        return saved

    def _validate_placements(self, db, rows, contexts):
        seen = set()
        fields = ("id", "title", "creative", "source")
        live = self.live
        if live:
            fields += ("catalog_ref",)
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(fields):
                raise ValueError("Live placements need a registered catalog reference." if live
                                 else "Each placement needs a video ID, title, context and source.")
            video_id, title = row["id"], row["title"]
            context, source = row["creative"], row["source"]
            if not isinstance(source, str) or source not in self.sources:
                raise ValueError("Only sample or independently supplied placements can be saved in this mode.")
            if (not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id) or video_id in seen
                    or not isinstance(context, str) or context not in contexts
                    or not isinstance(title, str) or not title.strip() or len(title) > 3000):
                raise ValueError("Use unique video IDs, known contexts and titles of up to 3000 characters.")
            if live:
                ref = row["catalog_ref"]
                entry = None
                if isinstance(ref, str) and re.fullmatch(r"[0-9a-f]{32}", ref):
                    entry = db.execute(
                        "SELECT video_id, title, source FROM catalog_entries WHERE ref = ?", (ref,),
                    ).fetchone()
                if entry != (video_id, title, source):
                    raise ValueError("The placement does not match a registered catalog entry.")
            seen.add(video_id)
        # Canonical field order allows browser snapshots to compare consistently.
        return [{key: row[key] for key in fields} for row in rows]
