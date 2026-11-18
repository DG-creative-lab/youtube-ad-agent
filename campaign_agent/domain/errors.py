"""Shared campaign and storage conflicts."""

class StaleDraft(ValueError):
    """A later revision already exists for this campaign."""

    def __init__(self, latest):
        super().__init__("A newer draft exists. Review your changes against it before saving.")
        self.latest = latest

class PackageConflict(ValueError):
    """The reviewed package is stale or lacks a matching approval."""


class SchemaConflict(RuntimeError):
    """The native storage history or ownership schema requires reconciliation."""
