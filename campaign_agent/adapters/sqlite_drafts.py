"""Native draft records on a caller-owned SQLite connection.

Application commands retain authorization, serialization, schema initialization
and transaction ownership. Snapshot text passes through unchanged.
"""

import sqlite3


class SQLiteDraftStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def has_revisions(self, campaign_id):
        return self.connection.execute(
            "SELECT 1 FROM campaign_revisions WHERE campaign_id=?", (campaign_id,),
        ).fetchone() is not None

    def read_snapshot(self, campaign_id, revision=None):
        if revision is None:
            row = self.connection.execute(
                "SELECT snapshot FROM campaign_revisions WHERE campaign_id = ? "
                "ORDER BY revision DESC LIMIT 1", (campaign_id,),
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT snapshot FROM campaign_revisions WHERE campaign_id = ? AND revision = ?",
                (campaign_id, revision),
            ).fetchone()
        # Legacy tables can allow NULL. A present invalid snapshot must not look
        # like a missing revision; commands previously failed while decoding it.
        if row is not None and row[0] is None:
            raise TypeError("The campaign revision snapshot is NULL.")
        return row[0] if row else None

    def append_snapshot(self, campaign_id, revision, snapshot):
        self.connection.execute(
            "INSERT INTO campaign_revisions VALUES (?, ?, ?)",
            (campaign_id, revision, snapshot),
        )

    def live_catalog_entry(self, client_id, brand_id, campaign_id, ref):
        return self.connection.execute(
            "SELECT video_id,title,source,source_reference FROM catalog_entries "
            "WHERE ref=? AND client_id=? AND brand_id=? AND campaign_id=?",
            (ref, client_id, brand_id, campaign_id),
        ).fetchone()

    def placement_catalog_entry(self, client_id, brand_id, campaign_id, ref):
        return self.connection.execute(
            "SELECT video_id,title,source,source_reference FROM placement_catalog_entries "
            "WHERE ref=? AND client_id=? AND brand_id=? AND campaign_id=?",
            (ref, client_id, brand_id, campaign_id),
        ).fetchone()
