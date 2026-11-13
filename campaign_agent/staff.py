"""Server-owned staff sessions. Upstream verification is an injected boundary."""
from contextlib import closing
from dataclasses import dataclass, field
import hashlib
import math
import secrets
import sqlite3
from time import time
from typing import Protocol
from .ports.access import AccessUnavailable


class SignInRequired(PermissionError):
    pass


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    audiences: frozenset[str]
    client_id: str
    session_id: str
    expires_at: float
    subject_token: str = field(repr=False)
    kind: str = "human"
    token_type: str = "access_token"
    active: bool = True


class IdentityVerifier(Protocol):
    def verify_current(self, credential_reference: str) -> VerifiedIdentity: ...


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class StaffSessions:
    def __init__(self, path, verifier, *, issuer, audiences, client_id, clock=time):
        self.path, self.verifier, self.issuer = path, verifier, issuer
        self.audiences, self.client_id, self.clock = frozenset(audiences), client_id, clock
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS staff_sessions (
                token_hash TEXT PRIMARY KEY, credential_reference TEXT NOT NULL,
                issuer TEXT NOT NULL, subject TEXT NOT NULL, upstream_session TEXT NOT NULL,
                campaign_id TEXT NOT NULL, csrf TEXT NOT NULL, expires_at REAL NOT NULL)''')

    def _identity(self, reference):
        try:
            identity = self.verifier.verify_current(reference)
        except SignInRequired:
            raise
        except Exception:
            raise AccessUnavailable('Current identity verification is unavailable.') from None
        if (not isinstance(identity, VerifiedIdentity) or identity.issuer != self.issuer
                or identity.audiences != self.audiences or identity.client_id != self.client_id
                or identity.kind != "human" or identity.token_type != "access_token" or not identity.active
                or not isinstance(identity.expires_at, (int, float)) or not math.isfinite(identity.expires_at)
                or identity.expires_at <= self.clock() or not identity.subject or not identity.session_id):
            raise SignInRequired("Sign in with the registered staff identity profile.")
        return identity

    def establish(self, credential_reference, campaign_id):
        """Trusted callback/composition only: reference points to already verified server credentials."""
        identity = self._identity(credential_reference)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expiry = min(identity.expires_at, self.clock() + 3600)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO staff_sessions VALUES(?,?,?,?,?,?,?,?)", (digest(token), credential_reference,
                       identity.issuer, identity.subject, identity.session_id, campaign_id, csrf, expiry))
        return token

    def local(self, token, *, allow_expired=False):
        if not isinstance(token, str) or len(token) != 43:
            raise SignInRequired("Sign in to open this workspace.")
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT credential_reference,issuer,subject,upstream_session,campaign_id,csrf,expires_at "
                             "FROM staff_sessions WHERE token_hash=?", (digest(token),)).fetchone()
        if row is None or (not allow_expired and row[6] <= self.clock()):
            raise SignInRequired("Sign in to open this workspace.")
        return row

    def current(self, token):
        row = self.local(token)
        identity = self._identity(row[0])
        if (identity.issuer, identity.subject, identity.session_id) != row[1:4]:
            raise SignInRequired("The staff session identity changed. Sign in again.")
        return identity, row[4], row[5]

    def select(self, token, campaign_id):
        # The caller must authorize the candidate through the product/Gateplane context first.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE staff_sessions SET campaign_id=? WHERE token_hash=?", (campaign_id, digest(token)))

    def end(self, token):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM staff_sessions WHERE token_hash=?", (digest(token),))
