"""Durable snapshots of isolated SQLite demo workspaces in Turso."""
from contextlib import closing
from dataclasses import dataclass
from functools import cached_property
import os
import sqlite3
import zlib

MAX_SQLITE_BYTES = 4 * 1024 * 1024
MAX_COMPRESSED_BYTES = 768 * 1024
SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_workspaces (
    invite TEXT PRIMARY KEY,
    fixture TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    snapshot BLOB,
    disabled INTEGER NOT NULL CHECK (disabled IN (0, 1))
)
"""


class WorkspaceConflict(Exception):
    pass


class WorkspaceUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Workspace:
    version: int | None = None
    snapshot: bytes | None = None
    disabled: bool = False


def compress_snapshot(database):
    if not database.startswith(b"SQLite format 3\0") or len(database) > MAX_SQLITE_BYTES:
        raise WorkspaceUnavailable("Invalid or oversized workspace database.")
    payload = zlib.compress(database)
    if len(payload) > MAX_COMPRESSED_BYTES:
        raise WorkspaceUnavailable("This workspace has reached its storage limit.")
    return payload


def expand_snapshot(payload):
    if not isinstance(payload, bytes) or len(payload) > MAX_COMPRESSED_BYTES:
        raise WorkspaceUnavailable("Invalid workspace snapshot.")
    reader = zlib.decompressobj()
    try:
        database = reader.decompress(payload, MAX_SQLITE_BYTES + 1)
    except zlib.error:
        raise WorkspaceUnavailable("Invalid workspace snapshot.") from None
    if (not reader.eof or reader.unused_data or len(database) > MAX_SQLITE_BYTES
            or not database.startswith(b"SQLite format 3\0")):
        raise WorkspaceUnavailable("Invalid workspace snapshot.")
    return database


class WorkspaceStore:
    def __init__(self, connect, fixture):
        self.connect = connect
        self.fixture = fixture

    @cached_property
    def initialized(self):
        with closing(self.connect()) as db:
            db.execute(SCHEMA)
        return True

    def load(self, invite, *, include_snapshot=False):
        if not self.initialized:
            raise WorkspaceUnavailable()
        field = "snapshot" if include_snapshot else "NULL"
        with closing(self.connect()) as db:
            row = db.execute(
                f"SELECT fixture, version, disabled, {field} FROM demo_workspaces WHERE invite=?",
                (invite,),
            ).fetchone()
        if row is None:
            return Workspace()
        fixture, version, disabled, snapshot = row
        if fixture != self.fixture:
            raise WorkspaceUnavailable("The workspace needs its original fixture version.")
        return Workspace(version, expand_snapshot(snapshot) if snapshot is not None else None, bool(disabled))

    def save(self, invite, expected_version, database, *, disable=False):
        if not self.initialized:
            raise WorkspaceUnavailable()
        snapshot = compress_snapshot(database) if database is not None else None
        with closing(self.connect()) as db:
            if expected_version is None:
                row = db.execute(
                    """INSERT INTO demo_workspaces (invite, fixture, version, snapshot, disabled)
                       VALUES (?, ?, 1, ?, ?) ON CONFLICT(invite) DO NOTHING RETURNING version""",
                    (invite, self.fixture, snapshot, int(disable)),
                ).fetchone()
            else:
                row = db.execute(
                    """UPDATE demo_workspaces SET version=version+1, snapshot=?, disabled=?
                       WHERE invite=? AND fixture=? AND version=? AND disabled=0 RETURNING version""",
                    (snapshot, int(disable), invite, self.fixture, expected_version),
                ).fetchone()
        if row is None:
            raise WorkspaceConflict("The workspace changed. Refresh and retry.")


def connected_store(fixture):
    import turso_serverless

    url = os.environ["TURSO_DATABASE_URL"]
    token = os.environ["TURSO_AUTH_TOKEN"]
    if not url.startswith(("turso://", "libsql://", "https://")) or not token:
        raise WorkspaceUnavailable("Configure the isolated Turso database.")
    return WorkspaceStore(
        lambda: turso_serverless.connect(url, auth_token=token, isolation_level=None), fixture,
    )


def sqlite_store(path, fixture):
    """Offline integration tests exercise the same atomic snapshot statements."""
    return WorkspaceStore(lambda: sqlite3.connect(path, isolation_level=None), fixture)
