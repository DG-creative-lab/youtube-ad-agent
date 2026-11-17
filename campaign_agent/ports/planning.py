"""Model and classifier operations consumed by the placement application."""
from typing import Protocol, TypedDict, Required


class MainModel(Protocol):
    def next_turn(self, context: dict, history: list[dict], settings: dict) -> dict: ...


class PlannerModel(MainModel, Protocol):
    """Configured model, including checks performed before reserving a request."""
    models: tuple[str, ...]
    prompt_version: str
    web_disabled: bool

    def settings(self, model: str) -> dict: ...
    def require_available(self, settings: dict) -> None: ...
    def validate_turn(self, context: dict, history: list[dict], settings: dict) -> None: ...


class PlacementClassifier(Protocol):
    route: str

    def classify(self, rows: list[dict], contexts: dict) -> list[dict]: ...


class StructuredUsage(TypedDict):
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: int | float | str | None


class StructuredInference(TypedDict, total=False):
    mode: str
    model: str
    prompt_version: str
    evidence_id: str
    request_id: str | None
    response_model: str | None
    usage: Required[StructuredUsage]
    run_id: str


class AssessmentReceipt(TypedDict):
    assessment: dict | None
    inference: StructuredInference


class InstructionDraftReceipt(TypedDict):
    draft: dict | None
    inference: StructuredInference


class StructuredModel(Protocol):
    models: tuple[str, ...]
    prompt_version: str
    web_disabled: bool

    def settings(self, model: str) -> dict: ...
    def require_available(self, settings: dict) -> None:
        """Check current local availability; do not dispatch an inference."""
        ...


class InstructionReviewer(StructuredModel, Protocol):
    def assess_instruction_test(self, context: dict, settings: dict) -> AssessmentReceipt: ...


class InstructionDrafter(StructuredModel, Protocol):
    def draft_instructions(self, context: dict, settings: dict) -> InstructionDraftReceipt: ...
