"""Read current campaign ownership and revision from a native SQLite snapshot."""
from contextlib import closing
import json
import sqlite3

from campaign_agent.domain.access_binding import command_hash
from campaign_agent.ports.access import AccessUnavailable, CampaignAccessReader, CampaignAccessRecord, CommandPermit

_OWNERS = """FROM campaign_owners c JOIN brand_workspaces b
             ON b.client_id=c.client_id AND b.brand_id=c.brand_id"""


def campaign_owner_row(db, campaign_id):
    return db.execute(
        f"SELECT b.client_id,b.brand_id,b.workspace_id,b.installation_id {_OWNERS} WHERE c.campaign_id=?",
        (campaign_id,),
    ).fetchone()


class SQLiteCampaignAccessReader:
    """Borrow the existing unit so uncommitted changes are visible to its permit fence."""

    def __init__(self, db):
        self._db = db

    def access_record(self, campaign_id):
        row = self._db.execute(
            f"""SELECT b.client_id,b.brand_id,b.workspace_id,b.installation_id,r.revision,r.snapshot {_OWNERS}
                JOIN campaign_revisions r ON r.campaign_id=c.campaign_id WHERE c.campaign_id=?
                ORDER BY r.revision DESC LIMIT 1""",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        client, brand, workspace, installation, revision, snapshot = row
        return CampaignAccessRecord((client, brand, workspace, installation), str(revision), snapshot)


class SQLiteCampaignAccessStorage:
    def __init__(self, path):
        self._path = path

    def access_record(self, campaign_id):
        with closing(sqlite3.connect(self._path)) as db:
            return SQLiteCampaignAccessReader(db).access_record(campaign_id)


def validate_permit(records: CampaignAccessReader, permit, request, command, session_digest, *, clock, monotonic_clock):
    """Local commit fence. This function has no authority or provider client."""
    if (not isinstance(permit, CommandPermit) or permit.request != request
            or permit.command_hash != command_hash(command)
            or permit.staff_session_digest != session_digest):
        raise PermissionError('The command binding changed.')
    if monotonic_clock() >= permit.valid_until or clock() >= permit.wall_expires_at:
        raise AccessUnavailable('The command decision expired.')
    record = records.access_record(request.campaign_id)
    expected = (request.client_id, request.brand_id, request.workspace_id, request.installation_id)
    if (record is None or record.owner != expected or record.revision != permit.campaign_revision
            or command_hash(json.loads(record.snapshot)) != permit.native_snapshot_hash):
        raise PermissionError('The native campaign changed.')
    if monotonic_clock() >= permit.valid_until or clock() >= permit.wall_expires_at:
        raise AccessUnavailable('The command decision expired during native verification.')
