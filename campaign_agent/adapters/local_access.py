"""Explicit local demo access; never a hosted authentication fallback."""
from campaign_agent.access import CAPABILITIES, LOCAL_CONTEXT
from campaign_agent.access import LOCAL_OPERATOR, command_hash, validate_permit
from campaign_agent.ports.access import CommandPermit
from time import time, monotonic
from uuid import uuid4


class LocalDemoAccess:
    def __init__(self, *, clock=time, monotonic_clock=monotonic):
        self.clock, self.monotonic = clock, monotonic_clock

    def decide(self, request):
        expected = LOCAL_CONTEXT
        return "allow" if (
            (request.client_id, request.brand_id, request.workspace_id, request.installation_id) ==
            (expected.scope.client_id, expected.scope.brand_id, expected.workspace_id, expected.installation_id)
            and request.capability in CAPABILITIES
        ) else "deny"

    def permit(self, request, *, command, session_digest, expires_at, path):
        from contextlib import closing
        import sqlite3
        if request.actor_id != LOCAL_OPERATOR.id or self.decide(request) != 'allow':
            raise PermissionError('Local command unavailable.')
        with closing(sqlite3.connect(path)) as db:
            row = db.execute('SELECT revision,snapshot FROM campaign_revisions WHERE campaign_id=? ORDER BY revision DESC LIMIT 1',
                             (request.campaign_id,)).fetchone()
        if row is None or expires_at <= self.clock():
            raise PermissionError('Local command unavailable.')
        expiry = min(expires_at, self.clock()+5)
        return CommandPermit(request, command_hash(command), session_digest, str(row[0]),
            command_hash(__import__('json').loads(row[1])), uuid4().hex,
            self.monotonic()+max(0,expiry-self.clock()), expiry)

    def validate_permit(self, db, permit, request, command, session_digest):
        validate_permit(db,permit,request,command,session_digest,clock=self.clock,monotonic_clock=self.monotonic)
