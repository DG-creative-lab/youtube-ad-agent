"""Server-owned client and brand scope for local campaign commands."""

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


LOCAL_BRAND = BrandScope("local-client", "tts-demo")
LOCAL_OPERATOR = Operator("local-operator", frozenset({LOCAL_BRAND}))
