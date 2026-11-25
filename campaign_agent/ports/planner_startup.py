"""Explicit local planner store initialization, before composing core services."""
from typing import Callable, Iterable, Protocol

from campaign_agent.domain.scope import WorkspaceContext
from .planner_context import ComparisonExample


class LocalPlannerStartup(Protocol):
    def initialize(self, *, context: WorkspaceContext, campaign_id: str | None,
                   seed_snapshot: str, examples: Iterable[ComparisonExample],
                   authorize: Callable[[str], None]) -> str: ...
