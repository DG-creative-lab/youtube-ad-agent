"""Immutable product ownership, with explicit admission of the original demo data."""
from contextlib import closing
import sqlite3
from pathlib import Path

from .access import LOCAL_CONTEXT, require_access
from .migrations import migrate


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


def provision_workspace(path, context, campaign_id, *, operator, access):
    """Trusted provisioning command; does not create Gateplane membership or entitlements."""
    if not isinstance(campaign_id, str) or not campaign_id.strip() or len(campaign_id) > 200:
        raise ValueError("Use a bounded campaign identity.")
    if campaign_id in {"tts-sample", "tts-catalog"} and context != LOCAL_CONTEXT:
        raise PermissionError("Demo campaign identities belong to the explicit local workspace.")
    require_access(operator, context, access, "youtube:workspace.configure", campaign_id)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        initialize(db)
        # Unknown legacy histories cannot be adopted by a newly provisioned customer.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='campaign_revisions'").fetchone():
            unowned = db.execute('''SELECT 1 FROM campaign_revisions r WHERE r.campaign_id=?
                AND NOT EXISTS(SELECT 1 FROM campaign_owners c WHERE c.campaign_id=r.campaign_id)''', (campaign_id,)).fetchone()
            if unowned:
                raise PermissionError("Legacy campaign ownership needs explicit reconciliation.")
        require_access(operator, context, access, "youtube:workspace.configure", campaign_id)
        _bind(db, context, campaign_id)
