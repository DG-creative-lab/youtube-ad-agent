"""Server-owned client and brand scope for local campaign commands."""

from campaign_agent.domain.access_binding import CAPABILITIES, LOCAL_BRAND, LOCAL_CONTEXT, LOCAL_OPERATOR, command_hash
from campaign_agent.domain.scope import BrandScope, Operator, WorkspaceContext


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
