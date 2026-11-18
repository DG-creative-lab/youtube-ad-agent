"""Current access decisions, independent of Gateplane's transport or data models."""
from dataclasses import dataclass
from typing import Literal, Protocol

from campaign_agent.domain.scope import WorkspaceContext


@dataclass(frozen=True)
class AccessRequest:
    actor_id: str
    client_id: str
    brand_id: str
    workspace_id: str
    installation_id: str
    capability: str
    campaign_id: str


class AccessPolicy(Protocol):
    def decide(self, request: AccessRequest) -> Literal["allow", "deny", "unavailable"]: ...


class GateplaneClient(Protocol):
    """Consumer facade for the private client; control authentication belongs to its adapter."""
    def context(self, subject_token: str, workspace_context) -> dict: ...
    def decide(self, request: dict) -> dict: ...


class AccessUnavailable(RuntimeError):
    """Current authorization cannot be established; no private action is permitted."""


@dataclass(frozen=True)
class CommandPermit:
    """In-process projection of an already validated command decision; never a browser token."""
    request: AccessRequest
    command_hash: str
    staff_session_digest: str
    campaign_revision: str
    native_snapshot_hash: str
    decision_id: str
    valid_until: float
    wall_expires_at: float



@dataclass(frozen=True)
class CampaignAccessRecord:
    owner: tuple[str, str, str, str]  # Client, brand, workspace and installation IDs.
    revision: str
    snapshot: str


class CampaignAccessReader(Protocol):
    def access_record(self, campaign_id: str) -> CampaignAccessRecord | None: ...


class StaffAuthority(AccessPolicy, Protocol):
    """Resolve current staff context before constructing a campaign runtime."""

    def principal(self, campaign_id: str) -> tuple[object, WorkspaceContext, dict]: ...


class StaffAuthorityFactory(Protocol):
    def __call__(self, path, sessions, token: str, client: GateplaneClient, *,
                 application_id: str, command: dict) -> StaffAuthority: ...
