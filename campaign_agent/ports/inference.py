"""Foreground provider inputs and qualified metadata contracts, independent of transport."""
from dataclasses import dataclass, field
from typing import Protocol


class ProviderError(RuntimeError):
    MESSAGES = {
        'invalid_request': (400,'Use the declared provider command fields.'),
        'sign_in_required': (401,'Sign in to manage this connection.'),
        'access_denied': (403,'This connection is unavailable in the current workspace.'),
        'credential_mismatch': (403,'Use the original connection and credential.'),
        'connection_expired': (409,'Reconnect with a new operation; this connection is inactive.'),
        'waiting_for_credentials': (409,'Supply your OpenRouter key for this foreground request.'),
        'operation_conflict': (409,'This operation already has different inputs.'),
        'selection_stale': (409,'Refresh the catalogue and choose a model again.'),
        'route_unqualified': (409,'No qualified route is available for this selection.'),
        'budget_exhausted': (409,'The chosen budget cannot admit this selection.'),
        'admission_busy': (429,'A catalogue refresh is already in progress. Try again.'),
        'authority_unavailable': (503,'Current authority is unavailable. Try again.'),
        'catalogue_unavailable': (503,'Provider metadata is unavailable. Try again.'),
    }

    def __init__(self, code):
        self.code = code
        self.status, message = self.MESSAGES[code]
        super().__init__(message)

    def response(self):
        return {'error':str(self),'code':self.code,'retryable':self.code in {'catalogue_unavailable','authority_unavailable','admission_busy'}}


@dataclass(frozen=True)
class ForegroundCredential:
    key: str = field(repr=False)

    def __post_init__(self):
        if (not isinstance(self.key,str) or not 1 <= len(self.key) <= 512
                or any(ord(c)<33 or ord(c)>126 for c in self.key)):
            raise ProviderError('invalid_request')

    @classmethod
    def from_values(cls, values, *, required=True):
        if not values:
            if required:
                raise ProviderError('waiting_for_credentials')
            return None
        if len(values) != 1:
            raise ProviderError('invalid_request')
        return cls(values[0])


class ProviderMetadata(Protocol):
    def validate_key(self, credential: ForegroundCredential) -> None: ...
    def models(self, credential: ForegroundCredential) -> list[dict]: ...
    def endpoints(self, credential: ForegroundCredential, model: str) -> list[dict]: ...


@dataclass(frozen=True)
class ChargingProfile:
    """Explicit reviewed endpoint identity; production compositions start with no profiles."""
    model: str
    endpoint: str
    version: str
    endpoint_hash: str
    expires_at: float
    tasks: tuple[str, ...] = ('planner','structured_review')
    max_prompt_usd_per_million: str = '0'
    max_completion_usd_per_million: str = '0'
    max_request_usd: str = '0'
    max_input_tokens: int = 32000
    max_output_tokens: int = 512
    output_cap_parameter: str = 'max_completion_tokens'
    evidence: str = ''
