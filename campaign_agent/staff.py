"""Server-owned staff sessions. Upstream verification is an injected boundary."""
from dataclasses import dataclass, field
import hashlib
import math
from typing import Callable, Protocol

from .ports.access import AccessUnavailable
from .ports.staff_sessions import StaffSession, StaffSessionStorage


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
    def __init__(self, storage: StaffSessionStorage, verifier: IdentityVerifier, *,
                 issuer, audiences, client_id, clock: Callable[[], float], new_token: Callable[[], str]):
        self.storage, self.verifier, self.issuer = storage, verifier, issuer
        self.audiences, self.client_id = frozenset(audiences), client_id
        self.clock, self.new_token = clock, new_token

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
        token, csrf = self.new_token(), self.new_token()
        expiry = min(identity.expires_at, self.clock() + 3600)
        self.storage.insert(digest(token), StaffSession(
            credential_reference, identity.issuer, identity.subject, identity.session_id, campaign_id, csrf, expiry,
        ))
        return token

    def local(self, token, *, allow_expired=False) -> StaffSession:
        if not isinstance(token, str) or len(token) != 43:
            raise SignInRequired("Sign in to open this workspace.")
        session = self.storage.read(digest(token))
        if session is None or (not allow_expired and session.expires_at <= self.clock()):
            raise SignInRequired("Sign in to open this workspace.")
        return session

    def current(self, token):
        session = self.local(token)
        identity = self._identity(session.credential_reference)
        if ((identity.issuer, identity.subject, identity.session_id)
                != (session.issuer, session.subject, session.upstream_session)):
            raise SignInRequired("The staff session identity changed. Sign in again.")
        return identity, session.campaign_id, session.csrf

    def select(self, token, campaign_id):
        # The caller must authorize the candidate through the product/Gateplane context first.
        self.storage.select_campaign(digest(token), campaign_id)

    def end(self, token):
        self.storage.delete(digest(token))
