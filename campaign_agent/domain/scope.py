"""Immutable client, brand and workspace values; no identity admission or storage."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BrandScope:
    client_id: str
    brand_id: str


@dataclass(frozen=True)
class Operator:
    id: str
    grants: frozenset[BrandScope]

    def require_brand(self, scope: BrandScope) -> None:
        if scope not in self.grants:
            raise PermissionError("The operator has no access to this client and brand.")


@dataclass(frozen=True)
class WorkspaceContext:
    """Server-resolved product brand mapping, never browser-asserted membership."""
    scope: BrandScope
    workspace_id: str
    installation_id: str

    def __post_init__(self):
        for value in (self.scope.client_id, self.scope.brand_id, self.workspace_id, self.installation_id):
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ValueError("Use bounded, nonempty workspace identities.")
