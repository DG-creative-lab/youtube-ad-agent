"""Catalogue records and transaction operations owned by placement commands."""
from dataclasses import dataclass
from typing import ContextManager, Protocol


@dataclass(frozen=True)
class CatalogScope:
    client_id: str
    brand_id: str
    campaign_id: str


@dataclass(frozen=True)
class CatalogRecord:
    id: str
    scope: CatalogScope
    label: str
    snapshot: str


@dataclass(frozen=True)
class CatalogEntry:
    ref: str
    scope: CatalogScope
    video_id: str
    title: str
    source: str
    source_reference: str


class CatalogStorageError(RuntimeError):
    def __init__(self):
        super().__init__('Catalogue storage is unavailable.')


class CatalogUnitClosed(CatalogStorageError):
    """A transaction-scoped repository cannot be used after its unit ends."""


class CatalogReader(Protocol):
    def read_snapshot(self, scope: CatalogScope, catalog_id: str) -> tuple[str | None] | None: ...
    def list_catalogs(self, scope: CatalogScope) -> tuple[CatalogRecord, ...]: ...


class CatalogRepository(CatalogReader, Protocol):
    def add_catalog(self, record: CatalogRecord) -> None: ...
    def add_entry(self, entry: CatalogEntry) -> None: ...


class CatalogWriteUnit(Protocol):
    catalogs: CatalogRepository

    def commit(self) -> None: ...


class CatalogStorage(Protocol):
    """Reads hold one snapshot; writes roll back unless explicitly committed."""
    def read(self) -> ContextManager[CatalogReader]: ...
    def write(self) -> ContextManager[CatalogWriteUnit]: ...
