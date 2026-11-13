"""Server-owned client and brand scope for local campaign commands."""

from dataclasses import dataclass


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
