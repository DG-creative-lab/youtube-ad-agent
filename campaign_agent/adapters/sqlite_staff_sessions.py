"""SQLite persistence for server-owned staff sessions."""
from contextlib import closing, contextmanager
import sqlite3

from campaign_agent.ports.staff_sessions import StaffSession
from campaign_agent.ports.storage_errors import StorageError


class SQLiteStaffSessionStorage:
    def __init__(self, path):
        self._path = path

    @contextmanager
    def _connect(self):
        try:
            with closing(sqlite3.connect(self._path)) as db, db:
                yield db
        except sqlite3.Error:
            raise StorageError('unavailable', 'Staff session storage is unavailable.') from None

    def insert(self, token_hash, session):
        with self._connect() as db:
            db.execute(
                """INSERT INTO staff_sessions
                   (token_hash, credential_reference, issuer, subject, upstream_session, campaign_id, csrf, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (token_hash, session.credential_reference, session.issuer, session.subject,
                 session.upstream_session, session.campaign_id, session.csrf, session.expires_at),
            )

    def read(self, token_hash):
        with self._connect() as db:
            row = db.execute(
                """SELECT credential_reference, issuer, subject, upstream_session, campaign_id, csrf, expires_at
                   FROM staff_sessions WHERE token_hash=?""",
                (token_hash,),
            ).fetchone()
        return StaffSession(*row) if row is not None else None

    def select_campaign(self, token_hash, campaign_id):
        with self._connect() as db:
            db.execute("UPDATE staff_sessions SET campaign_id=? WHERE token_hash=?", (campaign_id, token_hash))

    def delete(self, token_hash):
        with self._connect() as db:
            db.execute("DELETE FROM staff_sessions WHERE token_hash=?", (token_hash,))
