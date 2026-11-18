"""SQLite persistence for campaign performance and experiment evidence."""
from .sqlite_drafts import open_sqlite_unit
from .sqlite_planner_context import SQLitePlannerContext
from .sqlite_viewer import _ViewerUnit


class _EvidenceUnit(_ViewerUnit):
    def performance_review_row(self, key, attribution, review_id=None):
        with self.drafts._use() as store:
            return SQLitePlannerContext(store.connection).saved_review_row(*key, attribution, review_id)

    def correction_row(self, client_id, brand_id, campaign_id, creative_version, comparison_version,
                       takes_identity, comparison_identity):
        with self.drafts._use() as store:
            return SQLitePlannerContext(store.connection).correction_row(
                client_id, brand_id, campaign_id, creative_version, comparison_version,
                takes_identity, comparison_identity)

    def correction_operation(self, correction_id):
        with self.drafts._use() as store:
            return store.connection.execute(
                "SELECT review_id,kind,note FROM campaign_buyer_corrections WHERE id=?", (correction_id,)).fetchone()

    def add_correction(self, correction):
        with self.drafts._use(write=True) as store:
            store.connection.execute("""
                INSERT INTO campaign_buyer_corrections
                    (id, client_id, brand_id, campaign_id, creative_version, comparison_fingerprint,
                     review_id, actor_id, kind, note, created_at, comparison_identity, takes_identity, comparison_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING
            """, (correction.id, *correction.scope, correction.creative, correction.fingerprint, correction.review_id,
                  correction.actor, correction.kind, correction.note, correction.created_at,
                  correction.comparison_identity, correction.takes_identity, correction.comparison_version))

    def save_performance_review(self, key, review_id, now, snapshot):
        with self.drafts._use(write=True) as store:
            store.connection.execute(
                "INSERT INTO campaign_performance_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET last_requested_at = excluded.last_requested_at",
                (review_id, *key, now, now, snapshot))
            return store.connection.execute(
                "SELECT created_at FROM campaign_performance_reviews WHERE id=?", (review_id,)).fetchone()[0]

    def test_exists(self, test_id):
        with self.drafts._use() as store:
            return store.connection.execute("SELECT 1 FROM instruction_tests WHERE id=?", (test_id,)).fetchone() is not None

    def test_row(self, test_id, scope):
        with self.drafts._use() as store:
            return store.connection.execute(
                "SELECT snapshot FROM instruction_tests WHERE id=? AND client_id=? AND brand_id=? AND campaign_id=?",
                (test_id, *scope)).fetchone()

    def add_test(self, key, test_id, started_at, snapshot):
        with self.drafts._use(write=True) as store:
            store.connection.execute("INSERT INTO instruction_tests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                     (test_id, *key, started_at, snapshot))

    def assignment(self, test_id, participant_id):
        with self.drafts._use() as store:
            return store.connection.execute(
                "SELECT arm,visit_id,source FROM instruction_test_assignments WHERE test_id=? AND participant_id=?",
                (test_id, participant_id)).fetchone()

    def add_assignment(self, test_id, participant_id, arm, visit_id, source):
        with self.drafts._use(write=True) as store:
            store.connection.execute(
                "INSERT INTO instruction_test_assignments (test_id,participant_id,arm,visit_id,source) "
                "VALUES (?,?,?,?,?)", (test_id, participant_id, arm, visit_id, source))

    def evidence_snapshot_row(self, test_id, operation_id=None):
        with self.drafts._use() as store:
            if operation_id is not None:
                return store.connection.execute(
                    "SELECT snapshot FROM instruction_test_evidence_snapshots WHERE test_id=? AND operation_id=?",
                    (test_id, operation_id)).fetchone()
            return store.connection.execute(
                "SELECT snapshot FROM instruction_test_evidence_snapshots WHERE test_id=? ORDER BY rowid DESC LIMIT 1",
                (test_id,)).fetchone()

    def initial_checkpoint_row(self, test_id, initial):
        with self.drafts._use() as store:
            return store.connection.execute("""
                SELECT s.snapshot FROM instruction_test_evidence_snapshots s
                WHERE s.test_id = ? AND (?, 0) = (
                    SELECT SUM(json_extract(value, '$.cohorts.participant.mature_arrivals')),
                           SUM(json_extract(value, '$.cohorts.participant.unresolved'))
                    FROM json_each(s.snapshot, '$.rows')
                )
                ORDER BY s.rowid DESC LIMIT 1
            """, (test_id, initial)).fetchone()

    def add_evidence_snapshot(self, snapshot_id, test_id, operation_id, snapshot):
        with self.drafts._use(write=True) as store:
            store.connection.execute("INSERT INTO instruction_test_evidence_snapshots VALUES (?, ?, ?, ?)",
                                     (snapshot_id, test_id, operation_id, snapshot))

    def participant_watermark(self, test_id):
        with self.drafts._use() as store:
            return store.connection.execute(
                "SELECT COALESCE(MAX(e.seq),0) FROM viewer_events e JOIN instruction_test_assignments a "
                "ON a.visit_id=e.visit_id WHERE a.test_id=? AND a.source='participant'", (test_id,)).fetchone()[0]

    def latest_assessment(self, test_id):
        with self.drafts._use() as store:
            return store.connection.execute(
                "SELECT id,created_at,snapshot FROM instruction_test_reviews WHERE test_id=? ORDER BY rowid DESC LIMIT 1",
                (test_id,)).fetchone()

    def add_assessment(self, review_id, test_id, actor, now, snapshot):
        with self.drafts._use(write=True) as store:
            store.connection.execute(
                "INSERT INTO instruction_test_reviews VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (review_id, test_id, actor, now, snapshot))

    def cohort_outcomes(self, arm, window_ms, cutoff):
        with self.drafts._use() as store:
            return store.connection.execute("""
                WITH assigned AS (
                    SELECT a.source,
                           CASE WHEN v.arrived_ms IS NULL OR v.arrived_ms + :window > :cutoff
                                  OR NOT EXISTS (SELECT 1 FROM viewer_events e WHERE e.visit_id = v.id
                                                 AND e.kind = 'arrival' AND e.example_ref = :example)
                                  OR (c.visit_id IS NOT NULL AND
                                      (c.completed_ms IS NULL OR c.completed_ms < v.arrived_ms)) THEN NULL
                                WHEN c.completed_ms <= v.arrived_ms + :window THEN 1
                                ELSE 0 END AS completed
                    FROM instruction_test_assignments a JOIN viewer_visits v ON v.id = a.visit_id
                    LEFT JOIN viewer_completions c ON c.visit_id = v.id AND c.example_ref = :example
                    WHERE a.test_id = :test AND a.arm = :arm AND v.client_id = :client AND v.brand_id = :brand
                      AND v.campaign_id = :campaign
                      AND v.creative_ref = :creative AND v.content_fingerprint = :content
                      AND (v.arrived_ms IS NULL OR v.arrived_ms <= :cutoff)
                )
                SELECT source, COUNT(completed), COALESCE(SUM(completed), 0), COUNT(*) - COUNT(completed)
                FROM assigned GROUP BY source
            """, {"window": window_ms, "cutoff": cutoff, "example": arm.comparison,
                  "test": arm.test_id, "arm": arm.arm, "client": arm.scope.client_id,
                  "brand": arm.scope.brand_id, "campaign": arm.campaign, "creative": arm.creative,
                  "content": arm.fingerprint}).fetchall()

    def assignment_counts(self, arm, source):
        with self.drafts._use() as store:
            return store.connection.execute("""
                SELECT COUNT(*), COUNT(CASE WHEN EXISTS (
                    SELECT 1 FROM viewer_completions c WHERE c.visit_id = v.id AND c.example_ref = ?
                ) THEN 1 END)
                FROM instruction_test_assignments a JOIN viewer_visits v ON v.id = a.visit_id
                WHERE a.test_id = ? AND a.arm = ? AND v.client_id = ? AND v.brand_id = ?
                    AND v.campaign_id = ? AND a.source IS ?
                    AND v.creative_ref = ? AND v.content_fingerprint = ?
                    AND EXISTS (SELECT 1 FROM viewer_events e WHERE e.visit_id = v.id
                                AND e.kind = 'arrival' AND e.example_ref = ?)
            """, (arm.comparison, arm.test_id, arm.arm, arm.scope.client_id, arm.scope.brand_id,
                  arm.campaign, source, arm.creative, arm.fingerprint, arm.comparison)).fetchone()


class SQLiteEvidenceStorage:
    def __init__(self, path):
        self._path = path

    def read(self):
        return open_sqlite_unit(self._path, _EvidenceUnit, write=False, foreign_keys=True)

    def write(self):
        return open_sqlite_unit(self._path, _EvidenceUnit, write=True, foreign_keys=True)

    @staticmethod
    def borrow(db):
        return _EvidenceUnit(db, writable=None)
