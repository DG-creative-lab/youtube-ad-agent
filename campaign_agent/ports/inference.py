"""Foreground provider inputs and qualified metadata contracts, independent of transport."""
from dataclasses import dataclass, field
import re
from typing import Protocol


class ProviderError(RuntimeError):
    MESSAGES = {
        'provider_payment_required': (502,'OpenRouter requires credits or an account billing change for this request.'),
        'provider_rate_limited': (429,'OpenRouter or the selected provider rate-limited this request. Wait before starting a new request.'),
        'provider_privacy_unavailable': (502,'OpenRouter found no endpoint matching the no-training data policy for this model.'),
        'provider_no_route': (502,'OpenRouter found no available endpoint for the selected provider route.'),
        'provider_tools_rejected': (502,'The provider rejected the required tool-calling settings despite its advertised capabilities.'),
        'provider_unavailable': (502,'OpenRouter or the selected provider is temporarily unavailable.'),
        'provider_request_rejected': (502,'OpenRouter rejected the request. Inspect the recorded HTTP status in Agent activity.'),
        'model_output_limit': (502,'The model reached its output token limit before completing a tool call. Choose another model or start a new request with a supported larger limit.'),
        'model_tool_call_missing': (502,'The model response did not contain the required tool call.'),
        'model_tool_call_multiple': (502,'The model returned multiple tool calls; this agent accepts one call per step.'),
        'model_arguments_invalid': (502,'The model returned invalid tool arguments.'),
        'model_refused': (502,'The model declined this request.'),
        'model_input_limit': (502,'The request cannot fit the model input limit. Shorten the message or choose a model with a larger context.'),
        'model_response_invalid': (502,'The model response could not be used. No tool action was performed.'),
        'invalid_request': (400,'Use the declared provider command fields.'),
        'sign_in_required': (401,'Sign in to manage this connection.'),
        'access_denied': (403,'This connection is unavailable in the current workspace.'),
        'credential_mismatch': (403,'Use the original connection and credential.'),
        'connection_expired': (409,'Reconnect with a new operation; this connection is inactive.'),
        'waiting_for_credentials': (409,'Supply your OpenRouter key for this foreground request.'),
        'inference_outcome_unknown': (409,'This inference may have been sent. Its original reservation is retained.'),
        'operation_conflict': (409,'This operation already has different inputs.'),
        'selection_stale': (409,'Refresh the catalogue and choose a model again.'),
        'prompt_version_unsupported': (409,'The saved planner prompt version is unavailable. Start a new conversation; no new inference was sent.'),
        'unsupported_capabilities': (409,'This model does not support text input, text output and the required tools.'),
        'route_conditional_pricing': (409,'The provider publishes conditional price tiers that this app cannot bound yet.'),
        'route_unknown_pricing': (409,'The provider publishes an unrecognized billing unit that this app cannot bound.'),
        'route_reasoning_pricing': (409,'The provider bills reasoning separately and this app cannot bound that charge yet.'),
        'unsupported_pricing': (409,'This route has unknown, conditional or unsupported charges. Choose another model.'),
        'route_tools_unsupported': (409,'No provider route advertises both tool calling and tool choice.'),
        'route_required_choice_unsupported': (409,'No compatible provider route supports required tool choice.'),
        'route_output_cap_unsupported': (409,'No compatible provider route supports a bounded output token limit.'),
        'route_context_unsupported': (409,'The provider route has missing or insufficient context or token limits.'),
        'route_structured_unsupported': (409,'No provider route supports the required structured output format.'),
        'route_unavailable': (409,'OpenRouter reports no compatible provider endpoint for this model.'),
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


_MODEL_ID = re.compile(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.:-]{1,100}')


def model_id(value):
    if (not isinstance(value,str) or not _MODEL_ID.fullmatch(value) or value.startswith('openrouter/')
            or value.endswith((':auto',':floor',':nitro')) or any(part in ('.','..') for part in value.split('/'))):
        raise ProviderError('invalid_request')
    return value


class ProviderMetadata(Protocol):
    def validate_key(self, credential: ForegroundCredential) -> None: ...
    def models(self, credential: ForegroundCredential, *, sort: str | None = None) -> list[dict]: ...
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



class CatalogueState(Protocol):
    """Per-process advisory entries. Callers prove authority before access."""

    def invalidate(self, connection: str) -> None: ...
    def get(self, connection: str, now: float) -> dict | None: ...
    def begin(self, connection: str) -> None: ...
    def finish(self, connection: str, entry: dict | None = None) -> None: ...
    def page(self, entry: dict, search: str, cursor: str | None, *, tools_only: bool = False,
             max_input_price: str | None = None, max_output_price: str | None = None,
             sort: str = "available") -> tuple[list[dict], str | None]: ...
