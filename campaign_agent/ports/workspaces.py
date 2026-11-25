"""Ownership operations for trusted workspace provisioning."""
from typing import ContextManager, Protocol

from campaign_agent.domain.scope import WorkspaceContext


class WorkspaceProvisioningUnit(Protocol):
    def has_unowned_history(self, campaign_id: str) -> bool: ...
    def bind(self, context: WorkspaceContext, campaign_id: str) -> None: ...
    def commit(self) -> None: ...


class WorkspaceStorage(Protocol):
    def write(self) -> ContextManager[WorkspaceProvisioningUnit]: ...
