"""Current access decisions, independent of Gateplane's transport or data models."""
from dataclasses import dataclass
from typing import Literal, Protocol


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
