"""Server-owned client and brand scope for local campaign commands."""

import hashlib
import json

from campaign_agent.domain.scope import BrandScope, Operator, WorkspaceContext


LOCAL_BRAND = BrandScope("local-client", "tts-demo")
LOCAL_OPERATOR = Operator("local-operator", frozenset({LOCAL_BRAND}))


LOCAL_CONTEXT = WorkspaceContext(LOCAL_BRAND, "local-workspace", "youtube-local")
CAPABILITIES = frozenset({
    "youtube:campaign.read", "youtube:campaign.draft", "youtube:campaign.approve",
    "youtube:campaign.export", "youtube:workspace.configure", "youtube:catalog.write",
    "youtube:setup.manage", "youtube:agent.run", "youtube:review.write", "youtube:learning.manage",
})


def require_access(operator, context, policy, capability, campaign_id):
    from .ports.access import AccessRequest, AccessUnavailable
    operator.require_brand(context.scope)
    request = AccessRequest(operator.id, context.scope.client_id, context.scope.brand_id,
                            context.workspace_id, context.installation_id, capability, campaign_id)
    decision = policy.decide(request)
    if decision == "unavailable":
        raise AccessUnavailable("Current workspace access is unavailable.")
    if capability not in CAPABILITIES or decision != "allow":
        raise PermissionError("This action is unavailable in the selected workspace.")


def command_hash(command):
    return 'sha256:' + hashlib.sha256(json.dumps(command, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate_permit(db, permit, request, command, session_digest, *, clock, monotonic_clock):
    """Local commit fence. This function deliberately has no authority/provider client."""
    from .ports.access import AccessUnavailable, CommandPermit
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


class CommandAccess:
    """Request-local permit set. Nested product checks never call remote authority."""
    def __init__(self,path,context,original):
        self.path,self.context,self.original=path,context,original
        self.permits={}
        self.guard=None

    def refresh(self):
        from .ports.access import AccessRequest
        c=self.context.native
        self.context.local_validate()
        permits={}
        # The catalogue may project any of these grants. Denials stay denials;
        # optional capabilities are not requirements for a read-only request.
        for capability in ('youtube:campaign.read','youtube:agent.run','youtube:campaign.draft',
                           'youtube:review.write','youtube:setup.manage','youtube:campaign.export'):
            request=AccessRequest(self.context.actor_id,c.scope.client_id,c.scope.brand_id,c.workspace_id,c.installation_id,capability,self.context.campaign_id)
            try:
                permits[capability]=self.original.permit(request,command=self.context.command,
                    session_digest=self.context.session_digest,expires_at=self.context.expires_at,path=self.path)
            except PermissionError:
                if capability in ('youtube:campaign.read','youtube:agent.run'): raise
        self.permits=permits

    def decide(self,request):
        from contextlib import closing
        import sqlite3
        permit=self.permits.get(request.capability)
        if permit is None: return 'deny'
        self.context.local_validate()
        with closing(sqlite3.connect(self.path)) as db:
            self.original.validate_permit(db,permit,request,self.context.command,self.context.session_digest)
            if self.guard is not None: self.guard(db)
        return 'allow'

    def check(self,db):
        self.context.local_validate()
        for permit in self.permits.values():
            self.original.validate_permit(db,permit,permit.request,self.context.command,self.context.session_digest)
