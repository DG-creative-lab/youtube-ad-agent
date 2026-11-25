"""Native ownership migration and original local-demo admission."""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3

from campaign_agent.domain.access_binding import LOCAL_CONTEXT
from campaign_agent.ports.storage_errors import StorageError
from .sqlite_access import campaign_owner_row
from .sqlite_schema import migrate


def initialize(db):
    migrate(db)
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='campaign_revisions'").fetchone():
        for campaign_id, in db.execute("SELECT DISTINCT campaign_id FROM campaign_revisions WHERE campaign_id IN ('tts-sample','tts-catalog')"):
            admit_demo_campaign(db, campaign_id)


def admit_demo_campaign(db, campaign_id):
    if campaign_id not in {"tts-sample", "tts-catalog"}:
        raise PermissionError("Only original demo identities can be admitted implicitly.")
    _bind(db, LOCAL_CONTEXT, campaign_id)


def _bind(db, context, campaign_id):
    scope = context.scope
    expected = (scope.client_id, scope.brand_id, context.workspace_id, context.installation_id)
    existing = db.execute("SELECT client_id,brand_id,workspace_id,installation_id FROM brand_workspaces WHERE client_id=? AND brand_id=?",
                          (scope.client_id, scope.brand_id)).fetchone()
    foreign_installation = db.execute(
        "SELECT 1 FROM brand_workspaces WHERE installation_id=? AND client_id<>? LIMIT 1",
        (context.installation_id, scope.client_id),
    ).fetchone()
    if (existing is not None and existing != expected) or foreign_installation is not None:
        raise PermissionError("The brand or installation belongs to a different workspace.")
    owner = db.execute("SELECT client_id,brand_id FROM campaign_owners WHERE campaign_id=?", (campaign_id,)).fetchone()
    if owner is not None and owner != (scope.client_id, scope.brand_id):
        raise PermissionError("The campaign is unavailable in this workspace.")
    try:
        db.execute("INSERT OR IGNORE INTO brand_workspaces VALUES(?,?,?,?)", expected)
        db.execute("INSERT OR IGNORE INTO campaign_owners VALUES(?,?,?)", (campaign_id, scope.client_id, scope.brand_id))
    except sqlite3.IntegrityError as error:
        raise PermissionError("The workspace is already bound to another brand.") from error
    verify(db, context, campaign_id)


def verify(db, context, campaign_id):
    row = campaign_owner_row(db, campaign_id)
    if row != (context.scope.client_id, context.scope.brand_id, context.workspace_id, context.installation_id):
        raise PermissionError("The campaign is unavailable in this workspace.")


class _WorkspaceProvisioningUnit:
    def __init__(self, db):
        self._db = db

    def _connection(self):
        if self._db is None:
            raise StorageError('closed', 'The workspace provisioning transaction is closed.')
        return self._db

    def has_unowned_history(self, campaign_id):
        db = self._connection()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='campaign_revisions'").fetchone() is None:
            return False
        return db.execute(
            "SELECT 1 FROM campaign_revisions r WHERE r.campaign_id=? "
            "AND NOT EXISTS(SELECT 1 FROM campaign_owners c WHERE c.campaign_id=r.campaign_id)",
            (campaign_id,),
        ).fetchone() is not None

    def bind(self, context, campaign_id):
        _bind(self._connection(), context, campaign_id)

    def commit(self):
        db = self._connection()
        try:
            db.commit()
        except sqlite3.Error:
            raise StorageError('commit_unknown', 'The workspace ownership commit could not be confirmed.') from None
        finally:
            self.close()

    def close(self):
        self._db = None


class SQLiteWorkspaceStorage:
    def __init__(self, path):
        self._path = Path(path)

    @contextmanager
    def write(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with closing(sqlite3.connect(self._path)) as db:
                db.execute('BEGIN IMMEDIATE')
                unit = _WorkspaceProvisioningUnit(db)
                try:
                    initialize(db)
                    yield unit
                finally:
                    unit.close()
                    if db.in_transaction:
                        db.rollback()
        except sqlite3.Error:
            raise StorageError('unavailable', 'Workspace ownership storage is unavailable.') from None
