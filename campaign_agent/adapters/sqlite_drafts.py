"""SQLite draft and package records, with owned or borrowed transactions."""
from contextlib import closing, contextmanager
import sqlite3

from campaign_agent.ports.storage_errors import StorageError


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


class SQLiteDraftRepository:
    """Borrow a draft participant without exposing a connection to application policy."""
    def __init__(self, db, *, writable=None):
        # A retained caller owns borrowed transactions and their native errors.
        self._store = SQLiteDraftStore(db)
        self._writable = writable

    def _close(self):
        self._store = None

    def _require_active(self):
        if self._store is None:
            raise StorageError('closed', 'The campaign draft transaction is closed.')

    @contextmanager
    def _use(self, *, write=False):
        self._require_active()
        if write and self._writable is False:
            raise StorageError('read_only', 'The campaign draft transaction is read-only.')
        try:
            yield self._store
        except sqlite3.Error:
            if self._writable is None:
                raise
            raise StorageError('unavailable', 'Campaign draft storage is unavailable.') from None

    def latest_revision_row(self, campaign_id):
        with self._use() as store:
            return store.connection.execute(
                'SELECT revision,snapshot FROM campaign_revisions WHERE campaign_id=? ORDER BY revision DESC LIMIT 1',
                (campaign_id,)).fetchone()

    def owner_row(self, campaign_id):
        with self._use() as store:
            return store.connection.execute(
                'SELECT b.client_id,b.brand_id,b.workspace_id,b.installation_id '
                'FROM campaign_owners c JOIN brand_workspaces b '
                'ON c.client_id=b.client_id AND c.brand_id=b.brand_id WHERE c.campaign_id=?',
                (campaign_id,)).fetchone()

    def read_snapshot(self, campaign_id, revision=None):
        with self._use() as store:
            return store.read_snapshot(campaign_id, revision)

    def append_snapshot(self, campaign_id, revision, snapshot):
        with self._use(write=True) as store:
            store.append_snapshot(campaign_id, revision, snapshot)

    def live_catalog_entry(self, client_id, brand_id, campaign_id, ref):
        with self._use() as store:
            return store.live_catalog_entry(client_id, brand_id, campaign_id, ref)

    def placement_catalog_entry(self, client_id, brand_id, campaign_id, ref):
        with self._use() as store:
            return store.placement_catalog_entry(client_id, brand_id, campaign_id, ref)

    def approval_row(self, key):
        with self._use() as store:
            return store.connection.execute(
                "SELECT actor_id, approved_at FROM campaign_package_approvals WHERE "
                "client_id = ? AND brand_id = ? AND campaign_id = ? AND revision = ? AND fingerprint = ? "
                "AND snapshot IS NOT NULL", key,
            ).fetchone()

    def approval_snapshot_row(self, key):
        with self._use() as store:
            return store.connection.execute(
                "SELECT actor_id, approved_at, snapshot FROM campaign_package_approvals "
                "WHERE client_id = ? AND brand_id = ? AND campaign_id = ? AND revision = ? AND fingerprint = ?", key,
            ).fetchone()

    def approval_history(self, scope):
        with self._use() as store:
            return store.connection.execute(
                "SELECT revision, fingerprint, approved_at, snapshot IS NOT NULL "
                "FROM campaign_package_approvals WHERE client_id = ? AND brand_id = ? AND campaign_id = ? "
                "ORDER BY revision DESC, approved_at DESC, fingerprint", scope,
            ).fetchall()

    def append_approval(self, key, actor, approved_at, snapshot):
        with self._use(write=True) as store:
            store.connection.execute(
                "INSERT INTO campaign_package_approvals "
                "(client_id, brand_id, campaign_id, revision, fingerprint, actor_id, approved_at, snapshot) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (*key, actor, approved_at, snapshot),
            )

    def register_catalog_entry(self, scope, ref, entry):
        with self._use(write=True) as store:
            store.connection.execute(
                "INSERT OR IGNORE INTO catalog_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (ref, *entry, *scope),
            )

    def catalog_ref(self, scope, entry):
        with self._use() as store:
            return store.connection.execute(
                "SELECT ref FROM catalog_entries WHERE video_id = ? AND title = ? "
                "AND source = ? AND source_reference = ? AND client_id=? AND brand_id=? AND campaign_id=?",
                (*entry, *scope),
            ).fetchone()[0]

    def instructions(self, client_id, brand_id, creative, comparison):
        with self._use() as store:
            rows = store.connection.execute(
                "SELECT instruction FROM comparison_instruction_versions WHERE client_id = ? AND brand_id = ? "
                "AND creative_version = ? AND comparison_version = ?", (client_id, brand_id, creative, comparison),
            )
            return [instruction for instruction, in rows]

    def add_instructions(self, client_id, brand_id, creative, comparison, versions):
        with self._use(write=True) as store:
            store.connection.executemany(
                "INSERT INTO comparison_instruction_versions VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                [(client_id, brand_id, creative, comparison, key, text) for key, text in versions],
            )


class _DraftUnit:
    def __init__(self, db, *, writable):
        self.drafts = SQLiteDraftRepository(db, writable=writable)

    def commit(self):
        with self.drafts._use(write=True) as store:
            try:
                store.connection.commit()
            except sqlite3.Error:
                raise StorageError('commit_unknown', 'The campaign draft commit could not be confirmed.') from None
            finally:
                self.drafts._close()


class SQLiteDraftStorage:
    def __init__(self, path):
        self._path = path

    @contextmanager
    def _unit(self, *, write):
        try:
            with closing(sqlite3.connect(self._path)) as db:
                if not write:
                    db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                unit = _DraftUnit(db, writable=write)
                try:
                    yield unit
                finally:
                    unit.drafts._close()
                    if db.in_transaction:
                        db.rollback()
        except sqlite3.Error:
            raise StorageError('unavailable', 'Campaign draft storage is unavailable.') from None

    @contextmanager
    def read(self):
        with self._unit(write=False) as unit:
            yield unit.drafts

    def write(self):
        return self._unit(write=True)

    @contextmanager
    def legacy_write(self):
        """Native compatibility for a retained command that writes sibling records."""
        with closing(sqlite3.connect(self._path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db
