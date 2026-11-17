"""Scoped serialized records used to project one planner run."""
from dataclasses import dataclass
from typing import ContextManager, Protocol


@dataclass(frozen=True)
class PlannerRunScope:
    client_id: str
    brand_id: str
    actor_id: str
    campaign_id: str


class PlannerHistoryReader(Protocol):
    def history_rows(self, run_id: str) -> list[tuple[str, str | None, str | None]]: ...


class PlannerReader(PlannerHistoryReader, Protocol):
    def scoped_run_row(self, run_id: str, scope: PlannerRunScope) -> tuple[str, str] | None: ...
    def job_result_row(self, run_id: str) -> tuple[str | None, str | None] | None: ...
    def turn_rows(self, run_id: str) -> list[tuple[int, str, str | None]]: ...


class PlannerReadStorage(Protocol):
    """All reads in the unit observe one committed snapshot."""
    def read(self) -> ContextManager[PlannerReader]: ...
