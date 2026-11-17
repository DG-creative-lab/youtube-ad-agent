"""Conversation records participating in the placement command's transaction."""
from typing import ContextManager, Iterable, NamedTuple, Protocol


class SessionRecord(NamedTuple):
    client_id: str
    brand_id: str
    actor_id: str
    settings: str
    campaign_id: str


class MessageRecord(NamedTuple):
    id: int
    role: str
    content: str
    run_id: str
    revision: int
    catalog_id: str
    kind: str
    created_at: str
    outcome: str | None


class JobContext(NamedTuple):
    session_id: str
    snapshot: str


class LegacyTranscript(NamedTuple):
    run_id: str
    session_id: str
    snapshot: str
    outcome: str | None
    status: str


class ConversationRepository(Protocol):
    """Borrowed operations share their caller's transaction; text stays serialized."""
    def session_row(self, session_id: str) -> SessionRecord | None: ...
    def message_rows(self, session_id: str, limit: int = -1) -> tuple[MessageRecord, ...]: ...
    def append_message(self, session_id: str, run_id: str, role: str, content: str,
                       revision: int, catalog_id: str, kind: str) -> None: ...
    def job_context_row(self, run_id: str) -> JobContext | None: ...
    def latest_message_id(self, session_id: str) -> int: ...
    def message_count(self, session_id: str) -> int: ...
    def create_session(self, session_id: str, client_id: str, brand_id: str, actor_id: str,
                       settings: str, campaign_id: str) -> None: ...
    def update_settings(self, session_id: str, settings: str) -> None: ...
    def list_rows(self, client_id: str, brand_id: str, actor_id: str,
                  campaign_id: str) -> tuple[tuple[str, str, str | None], ...]: ...
    def running_runs(self, session_id: str) -> tuple[str, ...]: ...
    def supersede(self, run_id: str, outcome: str) -> None: ...
    def legacy_transcripts(self) -> Iterable[LegacyTranscript]: ...


class ConversationStorage(Protocol):
    def initialize(self) -> ContextManager[ConversationRepository]: ...
    def read(self) -> ContextManager[ConversationRepository]: ...
