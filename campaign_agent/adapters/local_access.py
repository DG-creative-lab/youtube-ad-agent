"""Explicit local demo access; never a hosted authentication fallback."""
import json
from time import time, monotonic
from uuid import uuid4

from campaign_agent.domain.access_binding import CAPABILITIES, LOCAL_CONTEXT, LOCAL_OPERATOR, command_hash
from campaign_agent.ports.access import CampaignAccessReader, CommandPermit
from .sqlite_access import SQLiteCampaignAccessStorage, validate_permit


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
        if request.actor_id != LOCAL_OPERATOR.id or self.decide(request) != 'allow':
            raise PermissionError('Local command unavailable.')
        record = SQLiteCampaignAccessStorage(path).access_record(request.campaign_id)
        expected = (request.client_id, request.brand_id, request.workspace_id, request.installation_id)
        if record is None or record.owner != expected or expires_at <= self.clock():
            raise PermissionError('Local command unavailable.')
        expiry = min(expires_at, self.clock()+5)
        return CommandPermit(request, command_hash(command), session_digest, record.revision,
            command_hash(json.loads(record.snapshot)), uuid4().hex,
            self.monotonic()+max(0,expiry-self.clock()), expiry)

    def validate_permit(self, records: CampaignAccessReader, permit, request, command, session_digest):
        validate_permit(records, permit, request, command, session_digest,
                        clock=self.clock, monotonic_clock=self.monotonic)
