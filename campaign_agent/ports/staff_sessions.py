"""Server-owned staff session records, independent of the identity verifier and database."""
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class StaffSession:
    credential_reference: str = field(repr=False)
    issuer: str
    subject: str
    upstream_session: str
    campaign_id: str
    csrf: str = field(repr=False)
    expires_at: float


class StaffSessionStorage(Protocol):
    """Each mutation commits one session change atomically."""

    def insert(self, token_hash: str, session: StaffSession) -> None: ...
    def read(self, token_hash: str) -> StaffSession | None: ...
    def select_campaign(self, token_hash: str, campaign_id: str) -> None: ...
    def delete(self, token_hash: str) -> None: ...
