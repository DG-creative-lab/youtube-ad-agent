"""Native planner context reads on the caller's exact transaction connection."""

from .sqlite_drafts import SQLiteDraftRepository


class SQLitePlannerContext:
    def __init__(self, db):
        self._db = db

    def approval_row(self, client_id, brand_id, campaign_id, revision, fingerprint):
        return SQLiteDraftRepository(self._db).approval_row((client_id, brand_id, campaign_id, revision, fingerprint))

    def saved_review_row(self, client_id, brand_id, campaign_id, revision, fingerprint,
                         attribution, review_id=None):
        query = ("SELECT id,created_at,snapshot FROM campaign_performance_reviews "
                 "WHERE client_id=? AND brand_id=? AND campaign_id=? AND revision=? AND fingerprint=? "
                 "AND json_extract(snapshot, '$.local_viewer_activity.attribution')=?")
        values = [client_id, brand_id, campaign_id, revision, fingerprint, attribution]
        if review_id is not None:
            query += ' AND id=?'
            values.append(review_id)
        return self._db.execute(query + ' ORDER BY last_requested_at DESC,id DESC LIMIT 1', values).fetchone()

    def started_test_exists(self, test_id, client_id, brand_id):
        return self._db.execute(
            'SELECT 1 FROM instruction_tests WHERE id=? AND client_id=? AND brand_id=?',
            (test_id, client_id, brand_id)).fetchone() is not None

    def correction_row(self, client_id, brand_id, campaign_id, creative_version,
                       comparison_version, takes_identity, comparison_identity):
        return self._db.execute("""
            SELECT id, kind, note, review_id, actor_id, created_at FROM (
                SELECT id, kind, note, review_id, actor_id, created_at, comparison_identity
                FROM campaign_buyer_corrections
                WHERE client_id = ? AND brand_id = ? AND campaign_id = ?
                    AND creative_version = ? AND comparison_version = ? AND takes_identity = ?
                ORDER BY sequence DESC LIMIT 1
            )
            WHERE kind = 'keep_takes' OR (kind = 'keep_comparison' AND comparison_identity = ?)
        """, (client_id, brand_id, campaign_id, creative_version, comparison_version,
              takes_identity, comparison_identity)).fetchone()
