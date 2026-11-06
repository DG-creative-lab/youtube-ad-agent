"""Local campaign draft commands and their SQLite storage."""

from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4


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


class CampaignDrafts:
    def __init__(self, path, live):
        self.path = path
        self.live = live
        self.campaign_id = "tts-catalog" if live else "tts-sample"
        self.sources = CATALOG_SOURCES if live else {"sample_search", "synthetic"}
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS campaign_revisions (
                    campaign_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    snapshot TEXT NOT NULL,
                    PRIMARY KEY (campaign_id, revision)
                )
            """)
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

    def save(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"campaign_id", "revision", "placements"}:
            raise ValueError("Send a campaign ID, expected revision and placements.")
        expected = payload["revision"]
        if (payload["campaign_id"] != self.campaign_id
                or type(expected) is not int or not 1 <= expected < 2**63):
            raise ValueError("The campaign ID or revision is invalid.")
        rows = payload["placements"]
        if not isinstance(rows, list) or len(rows) > MAX_PLACEMENTS:
            raise ValueError(f"Save up to {MAX_PLACEMENTS} placements at a time.")

        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
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
