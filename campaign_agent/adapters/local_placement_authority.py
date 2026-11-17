"""Acquire local demo permits before any adopted write unit is opened."""
import sqlite3
from .local_access import LocalDemoAccess
from .sqlite_planner import _storage_failure
from campaign_agent.ports.storage_errors import StorageError


class LocalPlacementAuthority:
    def __init__(self, path, *, clock, monotonic_clock):
        self._path = path
        self._policy = LocalDemoAccess(clock=clock, monotonic_clock=monotonic_clock)

    def decide(self, request):
        return self._policy.decide(request)

    def issue(self, request, command, session_digest, expires_at):
        try:
            return self._policy.permit(request, command=command, session_digest=session_digest,
                                       expires_at=expires_at, path=self._path)
        except sqlite3.Error as error:
            raise _storage_failure(error) from None
        except (ValueError, TypeError):
            raise StorageError('invalid', 'Placement storage contains an invalid campaign preimage.') from None
