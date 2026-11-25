"""Native setup journals and delivery evidence on the selected unit."""
import json

from .sqlite_drafts import _DraftUnit, open_sqlite_unit
from .sqlite_planner_context import SQLitePlannerContext


class _SetupDeliveryUnit(_DraftUnit):
    def setup_snapshot_row(self, key):
        with self.drafts._use() as store:
            return store.connection.execute(
                """SELECT snapshot FROM campaign_setups WHERE client_id=? AND brand_id=?
                   AND campaign_id=? AND revision=? AND fingerprint=? AND provider=? AND account_id=?""",
                key).fetchone()

    def add_setup(self, key, snapshot):
        with self.drafts._use(write=True) as store:
            store.connection.execute("INSERT INTO campaign_setups VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                     (*key, snapshot))

    def update_setup(self, key, snapshot):
        with self.drafts._use(write=True) as store:
            store.connection.execute(
                """UPDATE campaign_setups SET snapshot=? WHERE client_id=? AND brand_id=?
                   AND campaign_id=? AND revision=? AND fingerprint=? AND provider=? AND account_id=?""",
                (snapshot, *key))

    def publication_rows(self, key):
        with self.drafts._use() as store:
            return store.connection.execute(
                """SELECT id,creative_ref,snapshot,active,expires_at FROM public_comparisons
                   WHERE client_id=? AND brand_id=? AND campaign_id=? AND revision=? AND fingerprint=?""",
                key).fetchall()

    def report_snapshot_row(self, setup_id, scenario):
        with self.drafts._use() as store:
            return store.connection.execute(
                """SELECT snapshot FROM campaign_delivery_reports WHERE setup_id=?
                   AND json_extract(snapshot, '$.binding.demo_scenario') IS ? ORDER BY rowid DESC LIMIT 1""",
                (setup_id, scenario)).fetchone()

    def recommendation_snapshot_row(self, report_id):
        with self.drafts._use() as store:
            return store.connection.execute(
                "SELECT snapshot FROM campaign_delivery_recommendations WHERE report_id=? ORDER BY rowid DESC LIMIT 1",
                (report_id,)).fetchone()

    def add_report(self, report_id, setup_id, snapshot):
        with self.drafts._use(write=True) as store:
            store.connection.execute("INSERT INTO campaign_delivery_reports VALUES (?,?,?) ON CONFLICT(id) DO NOTHING",
                                     (report_id, setup_id, snapshot))

    def add_recommendation(self, recommendation_id, report_id, snapshot):
        with self.drafts._use(write=True) as store:
            store.connection.execute(
                "INSERT INTO campaign_delivery_recommendations VALUES (?,?,?) ON CONFLICT(id) DO NOTHING",
                (recommendation_id, report_id, snapshot))

    def correction_row(self, client_id, brand_id, campaign_id, creative_version, comparison_version,
                       takes_identity, comparison_identity):
        with self.drafts._use() as store:
            return SQLitePlannerContext(store.connection).correction_row(
                client_id, brand_id, campaign_id, creative_version, comparison_version,
                takes_identity, comparison_identity)

    def tagged_activity(self, scope, campaign_id, link):
        with self.drafts._use() as store:
            return store.connection.execute("""
                SELECT COUNT(*), COUNT(c.visit_id)
                FROM viewer_visits v
                JOIN viewer_events e ON e.visit_id = v.id AND e.event_id = ?
                LEFT JOIN viewer_completions c ON c.visit_id = v.id AND c.example_ref = e.example_ref
                WHERE v.client_id = ? AND v.brand_id = ? AND v.ad_link_id = ?
                    AND v.creative_ref = ? AND v.content_fingerprint = ? AND v.campaign_id = ?
            """, (f"arrival:{link['comparison_ref']}", scope.client_id, scope.brand_id, link['id'],
                  link['creative_ref'], link['content_fingerprint'], campaign_id)).fetchone()

    def tagged_window(self, scope, campaign_id, link, start_ms, end_ms):
        with self.drafts._use() as store:
            return store.connection.execute("""
                SELECT v.rehearsal, COUNT(*), COUNT(c.visit_id)
                FROM viewer_visits v
                JOIN viewer_events e ON e.visit_id = v.id AND e.event_id = ?
                LEFT JOIN viewer_completions c ON c.visit_id = v.id AND c.example_ref = e.example_ref
                    AND c.completed_ms >= v.arrived_ms AND c.completed_ms < ?
                WHERE v.client_id = ? AND v.brand_id = ? AND v.ad_link_id = ?
                    AND v.creative_ref = ? AND v.content_fingerprint = ? AND v.campaign_id = ?
                    AND v.arrived_ms >= ? AND v.arrived_ms < ? AND v.rehearsal IN (0, 1)
                GROUP BY v.rehearsal
            """, (f"arrival:{link['comparison_ref']}", end_ms, scope.client_id, scope.brand_id, link['id'],
                  link['creative_ref'], link['content_fingerprint'], campaign_id, start_ms, end_ms)).fetchall()


class SQLiteSetupDeliveryStorage:
    def __init__(self, path):
        self._path = path

    def read(self):
        return open_sqlite_unit(self._path, _SetupDeliveryUnit, write=False)

    def write(self):
        return open_sqlite_unit(self._path, _SetupDeliveryUnit, write=True)

    @staticmethod
    def borrow(db):
        return _SetupDeliveryUnit(db, writable=None)


def verified_viewer_link(db, scope, link_id, *, campaign_id="tts-sample"):
    """Look up a verified setup link within the retained viewer's write transaction."""
    row = db.execute("""SELECT link.value FROM campaign_setups AS setup,
                        json_each(setup.snapshot, '$.viewer_links') AS link
                        WHERE setup.client_id=? AND setup.brand_id=?
                        AND setup.campaign_id=?
                        AND json_extract(setup.snapshot, '$.status')='verified'
                        AND json_extract(link.value, '$.id')=?""",
                     (scope.client_id, scope.brand_id, campaign_id, link_id)).fetchone()
    return json.loads(row[0]) if row else None
