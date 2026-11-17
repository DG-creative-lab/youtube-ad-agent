"""The local placement save commits draft, step, run and reply together."""
from typing import ContextManager, Protocol
from .catalogs import CatalogReader
from .conversations import ConversationRepository
from .drafts import DraftRepository
from .planner_records import PlannerHistoryReader, PlannerRunScope


class PlacementRunRepository(Protocol):
    def scoped_run_row(self, run_id: str, scope: PlannerRunScope) -> tuple[str, str] | None: ...
    def step_exists_row(self, run_id: str, position: int) -> bool: ...
    def append_step(self, run_id: str, position: int, tool: str, result: str) -> None: ...
    def update_status(self, run_id: str, status: str) -> None: ...


class PlacementPlannerRepository(PlannerHistoryReader, Protocol):
    def job_snapshot_row(self, run_id: str) -> tuple[str | None] | None: ...
    def update_outcome(self, run_id: str, outcome: str) -> None: ...


class PlacementRepositories(Protocol):
    runs: PlacementRunRepository
    planner: PlacementPlannerRepository
    drafts: DraftRepository
    catalogs: CatalogReader
    conversations: ConversationRepository

class PlacementCommitUnit(PlacementRepositories, Protocol):
    def tool_attempt(self) -> ContextManager[None]: ...
    def commit(self) -> None: ...


class PlacementCommitStorage(Protocol):
    def write(self) -> ContextManager[PlacementCommitUnit]: ...
