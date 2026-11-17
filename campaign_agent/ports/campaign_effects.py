"""Campaign setup and delivery reporting contracts owned by their callers."""
from typing import NotRequired, Protocol, TypedDict


class SetupProviderError(RuntimeError):
    """The provider operation's outcome could not be established."""


class SetupProvider(Protocol):
    name: str
    account_id: str
    local_validation: bool

    def prepare(self, package: dict, fingerprint: str) -> dict: ...
    def validate(self, plan: dict) -> str | None: ...
    def create_paused(self, operation_id: str, plan: dict) -> dict: ...
    def readback(self, operation_id: str, plan: dict) -> dict | None: ...


class DeliveryGroup(TypedDict):
    name: str
    creative_version: str
    ad_group_id: str
    ad_id: str
    configured_videos: list[str]
    viewer_link: dict | None


class DeliveryBinding(TypedDict):
    setup_id: str
    account_id: str
    campaign_id: str
    groups: list[DeliveryGroup]
    demo_scenario: NotRequired[str]


class CampaignReporting(Protocol):
    provider: str
    manager_id: str
    account_id: str

    def snapshot(self, binding: DeliveryBinding) -> dict: ...
