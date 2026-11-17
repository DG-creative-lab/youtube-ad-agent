"""Scoped facts needed to pin and project a placement planner's context."""
from typing import Protocol, TypedDict

from campaign_agent.domain.scope import BrandScope


class ComparisonExample(Protocol):
    ref: str
    creative_ref: str
    scope: BrandScope
    title: str
    instruction: str
    passage: str
    takes: tuple[tuple[str, str, str], ...]
    preview: str


class MediaTake(TypedDict):
    id: str
    label: str
    asset: str
    sha256: str | None


class ComparisonContent(TypedDict):
    title: str
    instruction: str
    passage: str
    captions_sha256: str
    takes: list[MediaTake]
    preview_sha256: str | None


class ComparisonMedia(Protocol):
    """Logical content facts; implementations can capture them before a write unit."""
    def content(self, example: ComparisonExample) -> ComparisonContent: ...


class CapturedComparisonMedia(ComparisonMedia, Protocol):
    def validate(self) -> None: ...


class PlacementMedia(Protocol):
    def capture(self, examples: tuple[ComparisonExample, ...]) -> CapturedComparisonMedia: ...


class PlannerContextRepository(Protocol):
    def approval_row(self, client_id: str, brand_id: str, campaign_id: str, revision: int,
                     fingerprint: str) -> tuple[str, str] | None: ...
    def saved_review_row(self, client_id: str, brand_id: str, campaign_id: str, revision: int,
                         fingerprint: str, attribution: str,
                         review_id: str | None = None) -> tuple[str, str, str] | None: ...
    def started_test_exists(self, test_id: str, client_id: str, brand_id: str) -> bool: ...
    def correction_row(self, client_id: str, brand_id: str, campaign_id: str,
                       creative_version: str, comparison_version: str, takes_identity: str,
                       comparison_identity: str) -> tuple[str, str, str, str, str, str] | None: ...
