"""Scoped viewer visits, events and comparison completion in local SQLite."""

from contextlib import closing
import re
import sqlite3
from uuid import uuid4

from .creatives import EXAMPLES


class ViewerNotFound(LookupError):
    """The requested link, example or visit is outside the viewer's scope."""


class ViewerMeasurement:
    def __init__(self, path, examples=EXAMPLES):
        self.path = path
        self.examples = {example.ref: example for example in examples}
        self.links = {example.creative_ref: example for example in examples}
        with closing(self.connect()) as db, db:
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS viewer_visits (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                    creative_ref TEXT NOT NULL, content_fingerprint TEXT
                );
                CREATE TABLE IF NOT EXISTS viewer_events (
                    seq INTEGER PRIMARY KEY, visit_id TEXT NOT NULL REFERENCES viewer_visits(id),
                    event_id TEXT NOT NULL, example_ref TEXT NOT NULL, kind TEXT NOT NULL,
                    take TEXT NOT NULL, UNIQUE (visit_id, event_id)
                );
                CREATE TABLE IF NOT EXISTS viewer_completions (
                    visit_id TEXT NOT NULL REFERENCES viewer_visits(id),
                    example_ref TEXT NOT NULL, first_choice TEXT NOT NULL,
                    PRIMARY KEY (visit_id, example_ref)
                );
            """)
            columns = db.execute("PRAGMA table_info(viewer_visits)").fetchall()
            if "content_fingerprint" not in {column[1] for column in columns}:
                db.execute("ALTER TABLE viewer_visits ADD COLUMN content_fingerprint TEXT")

    def connect(self):
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def resolve(self, creative_ref, example_ref=None):
        origin = self.links.get(creative_ref)
        target = self.examples.get(example_ref) if example_ref is not None else origin
        if origin is None or target is None or origin.scope != target.scope:
            raise ViewerNotFound("This comparison is unavailable.")
        return origin, target

    @staticmethod
    def visit_key(origin, visit_id):
        return visit_id, origin.scope.client_id, origin.scope.brand_id, origin.creative_ref

    def require_visit(self, db, origin, visit_id):
        visit = db.execute(
            "SELECT content_fingerprint FROM viewer_visits WHERE id = ? AND client_id = ? AND brand_id = ? AND creative_ref = ?",
            self.visit_key(origin, visit_id),
        ).fetchone()
        if visit is None:
            raise ViewerNotFound("This visit is unavailable.")
        return visit[0]

    def summarize(self, scope, comparisons, *, connection=None):
        """Count tagged visits and intended-example outcomes in one local snapshot."""
        if connection is None:
            with closing(self.connect()) as db:
                db.execute("BEGIN")
                return self.summarize(scope, comparisons, connection=db)
        db = connection
        observations = []
        for creative_ref, example_ref, fingerprint in comparisons:
            origin, example = self.resolve(creative_ref, example_ref)
            if origin.scope != scope or origin.ref != example.ref:
                raise ViewerNotFound("This comparison is unavailable.")
            arrivals, opened, completed = db.execute("""
                SELECT COUNT(*),
                    COUNT(CASE WHEN EXISTS (
                        SELECT 1 FROM viewer_events e WHERE e.visit_id = v.id
                            AND e.kind = 'arrival' AND e.example_ref = ?
                    ) THEN 1 END),
                    COUNT(CASE WHEN EXISTS (
                        SELECT 1 FROM viewer_completions c WHERE c.visit_id = v.id AND c.example_ref = ?
                    ) THEN 1 END)
                FROM viewer_visits v
                WHERE v.client_id = ? AND v.brand_id = ? AND v.creative_ref = ? AND v.content_fingerprint = ?
                    AND EXISTS (
                        SELECT 1 FROM viewer_events e WHERE e.visit_id = v.id AND e.kind = 'arrival'
                    )
            """, (example_ref, example_ref, scope.client_id, scope.brand_id, creative_ref, fingerprint)).fetchone()
            unattributed, = db.execute("""
                SELECT COUNT(*) FROM viewer_visits v
                WHERE v.client_id = ? AND v.brand_id = ? AND v.creative_ref = ?
                    AND v.content_fingerprint IS NULL
                    AND EXISTS (
                        SELECT 1 FROM viewer_events e WHERE e.visit_id = v.id AND e.kind = 'arrival'
                    )
            """, (scope.client_id, scope.brand_id, creative_ref)).fetchone()
            observations.append({
                "creative_version": creative_ref, "comparison_version": example_ref,
                "comparison_fingerprint": fingerprint, "unattributed_arrivals": unattributed,
                "arrivals": arrivals, "intended_opens": opened, "completions": completed,
                "completion_rate": completed / arrivals if arrivals else None,
            })
        return observations

    def open_example(self, creative_ref, example_ref=None, visit_id=None, *,
                     content_fingerprint=None, origin_unavailable=False, connection=None):
        if connection is None:
            with closing(self.connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                return self.open_example(
                    creative_ref, example_ref, visit_id, content_fingerprint=content_fingerprint,
                    origin_unavailable=origin_unavailable, connection=db,
                )
        origin, target = self.resolve(creative_ref, example_ref)
        db = connection
        if visit_id is None:
            visit_id = uuid4().hex
            attribution = None if origin_unavailable else content_fingerprint
            db.execute(
                "INSERT INTO viewer_visits (id, client_id, brand_id, creative_ref, content_fingerprint) "
                "VALUES (?, ?, ?, ?, ?)", (*self.visit_key(origin, visit_id), attribution),
            )
        else:
            attribution = self.require_visit(db, origin, visit_id)
            # A visit with unknown content can resume, but later verification cannot attribute its old activity.
            if attribution is not None:
                if attribution != content_fingerprint:
                    raise ViewerNotFound("This visit is unavailable.")
                if origin_unavailable:
                    db.execute("UPDATE viewer_visits SET content_fingerprint = NULL WHERE id = ?", (visit_id,))
        db.execute(
            "INSERT INTO viewer_events (visit_id, event_id, example_ref, kind, take) "
            "VALUES (?, ?, ?, 'arrival', '') ON CONFLICT (visit_id, event_id) DO NOTHING",
            (visit_id, f"arrival:{target.ref}", target.ref),
        )
        state = self.state(db, visit_id, target.ref)
        return {
            "visit_id": visit_id,
            "example": {
                "ref": target.ref, "title": target.title, "instruction": target.instruction,
                "passage": target.passage, "takes": [
                    {"id": take, "label": label, "video": name.endswith(".mp4"),
                     "url": f"/viewer/media/{creative_ref}/{target.ref}/{take}"}
                    for take, label, name in target.takes
                ],
                "captions": f"/viewer/media/{creative_ref}/{target.ref}/captions",
            },
            "examples": [
                {"ref": item.ref, "title": item.title}
                for item in self.examples.values() if item.scope == origin.scope
            ],
            **state,
        }

    @staticmethod
    def state(db, visit_id, example_ref):
        scope = (visit_id, example_ref)
        finished = [row[0] for row in db.execute(
            "SELECT DISTINCT take FROM viewer_events WHERE visit_id = ? AND example_ref = ? AND kind = 'finish' ORDER BY take",
            scope,
        )]
        choice = db.execute(
            "SELECT take FROM viewer_events WHERE visit_id = ? AND example_ref = ? AND kind = 'choose' ORDER BY seq DESC LIMIT 1",
            scope,
        ).fetchone()
        complete = db.execute(
            "SELECT 1 FROM viewer_completions WHERE visit_id = ? AND example_ref = ?", scope,
        ).fetchone()
        return {"finished": finished, "choice": choice[0] if choice else None, "complete": bool(complete)}

    def record(self, creative_ref, visit_id, example_ref, event_id, kind, take):
        origin, target = self.resolve(creative_ref, example_ref)
        takes = {item[0] for item in target.takes}
        if not re.fullmatch(r"[0-9a-f]{32}", event_id) or kind not in {"start", "finish", "choose"} or take not in takes:
            raise ValueError("Invalid comparison event.")
        event = (example_ref, kind, take)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self.require_visit(db, origin, visit_id)
            existing = db.execute(
                "SELECT example_ref, kind, take FROM viewer_events WHERE visit_id = ? AND event_id = ?",
                (visit_id, event_id),
            ).fetchone()
            if existing is not None:
                if existing != event:
                    raise ValueError("This event ID belongs to a different action.")
                return self.state(db, visit_id, example_ref)
            if not db.execute(
                "SELECT 1 FROM viewer_events WHERE visit_id = ? AND event_id = ?",
                (visit_id, f"arrival:{example_ref}"),
            ).fetchone():
                raise ViewerNotFound("Open this comparison before recording playback.")
            if kind == "finish" and not db.execute(
                "SELECT 1 FROM viewer_events WHERE visit_id = ? AND example_ref = ? AND kind = 'start' AND take = ?",
                (visit_id, example_ref, take),
            ).fetchone():
                raise ValueError("Start this take before finishing it.")
            if kind == "choose" and set(self.state(db, visit_id, example_ref)["finished"]) != takes:
                raise ValueError("Finish both takes before choosing.")
            db.execute(
                "INSERT INTO viewer_events (visit_id, event_id, example_ref, kind, take) VALUES (?, ?, ?, ?, ?)",
                (visit_id, event_id, *event),
            )
            if kind == "choose":
                db.execute(
                    "INSERT INTO viewer_completions VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                    (visit_id, example_ref, take),
                )
            return self.state(db, visit_id, example_ref)
