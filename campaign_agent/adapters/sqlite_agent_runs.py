"""SQLite units for run records, step history and their campaign evidence."""
from contextlib import contextmanager
import sqlite3

from campaign_agent.ports.storage_errors import StorageError

from .sqlite_drafts import open_sqlite_unit
from .sqlite_evidence import _EvidenceUnit
from .sqlite_runs import SQLiteRunStore


def _run_storage_failure(error):
    if isinstance(error, sqlite3.IntegrityError):
        return StorageError('conflict', 'Agent run storage rejected conflicting records.')
    if isinstance(error, sqlite3.OperationalError) and ('locked' in str(error).lower() or 'busy' in str(error).lower()):
        return StorageError('busy', 'Agent run storage is busy. Retry the original command.')
    return StorageError('unavailable', 'Agent run storage is unavailable.')


class _UnitRuns(SQLiteRunStore):
    def __init__(self, drafts):
        self._drafts = drafts

    @property
    def _connection(self):
        self._drafts._require_active()
        return self._drafts._store.connection


class _AgentRunUnit(_EvidenceUnit):
    def __init__(self, db, *, writable):
        super().__init__(db, writable=writable)
        self.runs = _UnitRuns(self.drafts)

    @property
    def evidence(self):
        return self


class SQLiteAgentRunStorage:
    def __init__(self, path):
        self._path = path

    @contextmanager
    def read(self):
        with open_sqlite_unit(self._path, _AgentRunUnit, write=False, native_failure=_run_storage_failure) as unit:
            yield unit.runs

    def write(self):
        # The recorded and structured workflows historically borrow a connection
        # with the default SQLite foreign-key setting.
        return open_sqlite_unit(self._path, _AgentRunUnit, write=True, native_failure=_run_storage_failure)

    @staticmethod
    def borrow(db):
        return _AgentRunUnit(db, writable=None)
