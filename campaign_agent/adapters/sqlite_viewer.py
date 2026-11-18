"""Comparison visits, immutable event evidence and publication grants in SQLite."""
import sqlite3

from campaign_agent.ports.viewer_storage import PublishedGrant
from .sqlite_drafts import _DraftUnit, open_sqlite_unit
from .sqlite_setup_delivery import verified_viewer_link


class _ViewerUnit(_DraftUnit):
    def visit_attribution(self, key):
        with self.drafts._use() as store:
            return store.connection.execute(
                "SELECT content_fingerprint, ad_link_id FROM viewer_visits "
                "WHERE id=? AND client_id=? AND brand_id=? AND creative_ref=? AND campaign_id IS ?",
                key).fetchone()

    def visit_link_row(self, visit_id):
        with self.drafts._use() as store:
            return store.connection.execute(
                "SELECT ad_link_id FROM viewer_visits WHERE id=?", (visit_id,)).fetchone()

    def add_visit(self, key, attribution, link_id, arrival_ms, rehearsal):
        with self.drafts._use(write=True) as store:
            store.connection.execute(
                "INSERT INTO viewer_visits (id, client_id, brand_id, creative_ref, campaign_id, "
                "content_fingerprint, ad_link_id, arrived_ms, rehearsal) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*key, attribution, link_id, arrival_ms, rehearsal))

    def clear_attribution(self, visit_id):
        with self.drafts._use(write=True) as store:
            store.connection.execute("UPDATE viewer_visits SET content_fingerprint=NULL WHERE id=?", (visit_id,))

    def add_arrival(self, visit_id, example):
        with self.drafts._use(write=True) as store:
            store.connection.execute(
                "INSERT INTO viewer_events (visit_id, event_id, example_ref, kind, take) "
                "VALUES (?, ?, ?, 'arrival', '') ON CONFLICT (visit_id, event_id) DO NOTHING",
                (visit_id, f"arrival:{example}", example))

    def event(self, visit_id, event_id):
        with self.drafts._use() as store:
            return store.connection.execute(
                "SELECT example_ref, kind, take FROM viewer_events WHERE visit_id=? AND event_id=?",
                (visit_id, event_id)).fetchone()

    def started(self, visit_id, example, take):
        with self.drafts._use() as store:
            return store.connection.execute(
                "SELECT 1 FROM viewer_events WHERE visit_id=? AND example_ref=? AND kind='start' AND take=?",
                (visit_id, example, take)).fetchone() is not None

    def finished_takes(self, visit_id, example):
        with self.drafts._use() as store:
            return [take for take, in store.connection.execute(
                "SELECT DISTINCT take FROM viewer_events WHERE visit_id=? AND example_ref=? AND kind='finish' ORDER BY take",
                (visit_id, example))]

    def last_choice(self, visit_id, example):
        with self.drafts._use() as store:
            row = store.connection.execute(
                "SELECT take FROM viewer_events WHERE visit_id=? AND example_ref=? AND kind='choose' ORDER BY seq DESC LIMIT 1",
                (visit_id, example)).fetchone()
            return row[0] if row else None

    def completed(self, visit_id, example):
        with self.drafts._use() as store:
            return store.connection.execute(
                "SELECT 1 FROM viewer_completions WHERE visit_id=? AND example_ref=?",
                (visit_id, example)).fetchone() is not None

    def add_event(self, visit_id, event_id, event):
        with self.drafts._use(write=True) as store:
            store.connection.execute(
                "INSERT INTO viewer_events (visit_id, event_id, example_ref, kind, take) VALUES (?, ?, ?, ?, ?)",
                (visit_id, event_id, *event))

    def add_completion(self, visit_id, example, take, completed_ms):
        with self.drafts._use(write=True) as store:
            store.connection.execute(
                "INSERT INTO viewer_completions (visit_id, example_ref, first_choice, completed_ms) "
                "VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING", (visit_id, example, take, completed_ms))

    def comparison_counts(self, scope, campaign, creative_ref, example_ref, fingerprint):
        with self.drafts._use() as store:
            arrivals, opened, completed = store.connection.execute("""
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
                    AND v.campaign_id = ? AND v.ad_link_id IS NULL
                    AND EXISTS (
                        SELECT 1 FROM viewer_events e WHERE e.visit_id = v.id AND e.kind = 'arrival'
                    )
            """, (example_ref, example_ref, scope.client_id, scope.brand_id, creative_ref, fingerprint, campaign)).fetchone()
            unattributed, = store.connection.execute("""
                SELECT COUNT(*) FROM viewer_visits v
                WHERE v.client_id = ? AND v.brand_id = ? AND v.creative_ref = ?
                    AND v.campaign_id = ? AND v.content_fingerprint IS NULL
                    AND EXISTS (
                        SELECT 1 FROM viewer_events e WHERE e.visit_id = v.id AND e.kind = 'arrival'
                    )
            """, (scope.client_id, scope.brand_id, creative_ref, campaign)).fetchone()
            return arrivals, opened, completed, unattributed

    def verified_setup_link(self, scope, campaign, link_id):
        with self.drafts._use() as store:
            return verified_viewer_link(store.connection, scope, link_id, campaign_id=campaign)

    def active_grant(self, token, now):
        with self.drafts._use() as store:
            row = store.connection.execute(
                """SELECT client_id,brand_id,campaign_id,revision,fingerprint,creative_ref,snapshot
                   FROM public_comparisons WHERE id=? AND active=1 AND expires_at>?""",
                (token, now)).fetchone()
            return PublishedGrant(*row) if row else None

    def active_links(self, key, now):
        with self.drafts._use() as store:
            return store.connection.execute(
                """SELECT id,creative_ref FROM public_comparisons WHERE client_id=? AND brand_id=?
                   AND campaign_id=? AND revision=? AND fingerprint=? AND active=1 AND expires_at>?""",
                (*key, now)).fetchall()

    def add_publication(self, token, grant, expires_at):
        with self.drafts._use(write=True) as store:
            store.connection.execute(
                """INSERT INTO public_comparisons
                   (id,client_id,brand_id,campaign_id,revision,fingerprint,creative_ref,snapshot,expires_at)
                   VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                (token, grant.client_id, grant.brand_id, grant.campaign_id, grant.revision, grant.fingerprint,
                 grant.creative_ref, grant.snapshot, expires_at))


class SQLiteViewerStorage:
    def __init__(self, path):
        self._path = path

    def read(self):
        return open_sqlite_unit(self._path, _ViewerUnit, write=False, foreign_keys=True)

    def write(self):
        return open_sqlite_unit(self._path, _ViewerUnit, write=True, foreign_keys=True)

    def legacy_connect(self):
        db = sqlite3.connect(self._path)
        try:
            db.execute("PRAGMA foreign_keys=ON")
        except BaseException:
            db.close()
            raise
        return db

    @staticmethod
    def borrow(db):
        return _ViewerUnit(db, writable=None)
