"""Server-owned client and brand scope for local campaign commands."""

from dataclasses import dataclass
import hashlib
import json


@dataclass(frozen=True)
class BrandScope:
    client_id: str
    brand_id: str


@dataclass(frozen=True)
class Operator:
    id: str
    grants: frozenset[BrandScope]

    def require_brand(self, scope: BrandScope) -> None:
        if scope not in self.grants:
            raise PermissionError("The operator has no access to this client and brand.")


LOCAL_BRAND = BrandScope("local-client", "tts-demo")
LOCAL_OPERATOR = Operator("local-operator", frozenset({LOCAL_BRAND}))


@dataclass(frozen=True)
class WorkspaceContext:
    """Server-resolved product brand mapping, never browser-asserted membership."""
    scope: BrandScope
    workspace_id: str
    installation_id: str

    def __post_init__(self):
        for value in (self.scope.client_id, self.scope.brand_id, self.workspace_id, self.installation_id):
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ValueError("Use bounded, nonempty workspace identities.")


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
