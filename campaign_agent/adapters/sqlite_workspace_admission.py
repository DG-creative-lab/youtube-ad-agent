"""Native ownership migration and original local-demo admission."""
import sqlite3

from campaign_agent.domain.scope import BrandScope, WorkspaceContext
from .sqlite_schema import migrate

LOCAL_CONTEXT = WorkspaceContext(BrandScope("local-client", "tts-demo"), "local-workspace", "youtube-local")


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
    installation = db.execute("SELECT client_id FROM brand_workspaces WHERE installation_id=?", (context.installation_id,)).fetchone()
    if (existing is not None and existing != expected) or (installation and installation[0] != scope.client_id):
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
    row = db.execute('''SELECT b.client_id,b.brand_id,b.workspace_id,b.installation_id
        FROM campaign_owners c JOIN brand_workspaces b
        ON c.client_id=b.client_id AND c.brand_id=b.brand_id WHERE c.campaign_id=?''', (campaign_id,)).fetchone()
    if row != (context.scope.client_id, context.scope.brand_id, context.workspace_id, context.installation_id):
        raise PermissionError("The campaign is unavailable in this workspace.")
