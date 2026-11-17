"""Model and classifier operations consumed by the placement application."""
from typing import Protocol


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
