"""Validate a permit against the owner and revision on the caller’s native connection."""
import json

from campaign_agent.domain.access_binding import command_hash
from campaign_agent.ports.access import AccessUnavailable, CommandPermit


def validate_permit(db, permit, request, command, session_digest, *, clock, monotonic_clock):
    """Local commit fence. This function deliberately has no authority/provider client."""
    if (not isinstance(permit, CommandPermit) or permit.request != request
            or permit.command_hash != command_hash(command)
            or permit.staff_session_digest != session_digest):
        raise PermissionError('The command binding changed.')
    if monotonic_clock() >= permit.valid_until or clock() >= permit.wall_expires_at:
        raise AccessUnavailable('The command decision expired.')
    row = db.execute('''SELECT b.client_id,b.brand_id,b.workspace_id,b.installation_id,r.revision,r.snapshot
        FROM campaign_owners c JOIN brand_workspaces b ON b.client_id=c.client_id AND b.brand_id=c.brand_id
        JOIN campaign_revisions r ON r.campaign_id=c.campaign_id WHERE c.campaign_id=?
        ORDER BY r.revision DESC LIMIT 1''', (request.campaign_id,)).fetchone()
    if (row is None or tuple(row[:4]) != (request.client_id,request.brand_id,request.workspace_id,request.installation_id)
            or str(row[4]) != permit.campaign_revision or command_hash(json.loads(row[5])) != permit.native_snapshot_hash):
        raise PermissionError('The native campaign changed.')
    if monotonic_clock() >= permit.valid_until or clock() >= permit.wall_expires_at:
        raise AccessUnavailable('The command decision expired during native verification.')
