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


class AccessUnavailable(RuntimeError):
    """Current authorization cannot be established; no private action is permitted."""
