"""Bounded OpenRouter transport and instruction-test assessments."""

import json
from decimal import Decimal
import math
import os
import re
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from campaign_agent.domain.inference_errors import ReviewInferenceError
from campaign_agent.domain.fingerprints import package_fingerprint
from campaign_agent.domain.instruction_requests import (
    ASSESSMENT_SCHEMA,
    ASSESSMENT_SYSTEM,
    assessment_evidence,
)


ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
PROMPT_VERSION = "instruction-test-review-v2"
MAX_OUTPUT_TOKENS = 512
MAX_RESPONSE_BYTES = 64_000
MAX_REQUEST_BYTES = 32_000
MODEL_ID = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:free")


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def send_request(request, *, timeout):
    return build_opener(NoRedirects()).open(request, timeout=timeout)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate response field")
        result[key] = value
    return result


def parse_json(text, *, exact=False):
    def invalid_constant(_value):
        raise ValueError("Invalid JSON number")
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant, **({"parse_float":Decimal} if exact else {}))


class OpenRouterInference:
    prompt_version = PROMPT_VERSION

    def __init__(self, models=(), *, transport=None):
        if any(not isinstance(model, str) or not MODEL_ID.fullmatch(model) for model in models):
            raise ValueError("Configure explicit OpenRouter model IDs ending in :free.")
        self.models = tuple(dict.fromkeys(models))
        self.transport = transport or send_request
        self.web_disabled = False
        self.foreground = None

    def settings(self, model):
        if model not in self.models:
            raise ValueError("Choose an enabled OpenRouter model.")
        return {"mode": "openrouter", "model": model, "prompt_version": self.prompt_version,
                "max_calls": 1, "max_output_tokens": MAX_OUTPUT_TOKENS, "max_cost_usd": 0}

    def require_available(self, settings, credential=None):
        if settings.get('foreground'):
            if self.foreground is None: raise ReviewInferenceError('Foreground provider context is unavailable.')
            return
        if self.web_disabled:
            raise ReviewInferenceError('Browser inference awaits scoped admission and recovery. Use offline mode.')
        if settings != self.settings(settings["model"]):
            raise ReviewInferenceError("This inference configuration is unavailable. Start a new operation.")
        if credential is None and not os.environ.get("OPENROUTER_API_KEY", "").strip():
            raise ReviewInferenceError("Configure OPENROUTER_API_KEY on the server before using OpenRouter inference.")

    def complete(self, context, settings, evidence, *, system, schema, name, output_key):
        self.require_available(settings)
        body = {
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": name, "strict": True, "schema": schema}},
        }
        receipt = self.chat(context, settings, body)
        output = None
        message = receipt.pop("message")
        finish_reason = receipt.pop("finish_reason")
        if (finish_reason == "stop" and isinstance(message, dict) and not message.get("refusal") and not message.get("tool_calls")
                and isinstance(message.get("content"), str)):
            try:
                output = parse_json(message["content"])
            except (ValueError, RecursionError):
                pass
        return {output_key: output, **receipt}

    def encode_request(self, settings, body):
        if settings.get('foreground'):
            body = {**body, 'model': settings['model'], 'stream': False,
                    settings['output_cap_parameter']:settings['max_output_tokens'], 'provider':settings['routing']}
        else:
            body = {**body, "model": settings["model"], "stream": False,
                    "max_tokens": MAX_OUTPUT_TOKENS,
                    "provider": {"require_parameters": True, "allow_fallbacks": False,
                                 "max_price": {"prompt": 0, "completion": 0, "request": 0}}}
        encoded = json.dumps(body).encode()
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ReviewInferenceError("The inference input exceeds the configured request limit.")
        return encoded

    def chat(self, context, settings, body, *, credential=None):
        self.require_available(settings, credential)
        if settings.get('foreground'):
            return self.foreground.chat(self,context,settings,body)
        encoded = self.encode_request(settings, body)
        return self._chat_wire(context,settings,encoded,credential)

    def _chat_wire(self,context,settings,encoded,credential):
        request = Request(ENDPOINT, data=encoded, headers={
            "Authorization": "Bearer " + (credential.key if credential is not None else os.environ["OPENROUTER_API_KEY"]), "Content-Type": "application/json",
        })
        try:
            with self.transport(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Response too large")
            data = parse_json(raw,exact=settings.get("foreground",False))
            if not isinstance(data, dict) or data.get("error") and not settings.get('foreground'):
                raise ValueError("Invalid completion")
            return self._receipt(context,settings,data,http_status=200)
        except HTTPError as exc:
            if settings.get('foreground'):
                try:
                    raw=exc.read(MAX_RESPONSE_BYTES+1)
                    if len(raw)>MAX_RESPONSE_BYTES: raise ValueError()
                    data=parse_json(raw,exact=True)
                    if not isinstance(data,dict): raise ValueError()
                    # A complete HTTP error can still report charge/generation.
                    return self._receipt(context,settings,{**data,'choices':None},http_status=exc.code)
                except (ValueError,TypeError,RecursionError,OSError,OverflowError):
                    pass
                finally: exc.close()
            else: exc.close()
            raise ReviewInferenceError(f"OpenRouter returned HTTP {exc.code}. Start a new operation to retry.") from None
        except (URLError, OSError, TimeoutError):
            raise ReviewInferenceError(
                "The OpenRouter request outcome is unknown. Its request allowance is consumed. Start a new operation to retry."
            ) from None
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise ReviewInferenceError("OpenRouter returned an invalid response. Start a new operation to retry.") from None

    def _receipt(self,context,settings,data,*,http_status=200):
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        tokens = {}
        for label, field in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")):
            value = usage.get(field)
            tokens[label] = value if type(value) is int and value >= 0 else None
        cost = usage.get("cost")
        if settings.get('foreground'):
            if isinstance(cost,Decimal):
                _,digits,exponent=cost.as_tuple()
                cost=(format(cost,'f') if cost.is_finite() and cost>=0 and len(digits)<=30 and exponent>=-18 and cost.adjusted()<=11 else None)
            else: cost=str(cost) if type(cost) is int and 0<=cost<10**12 else None
        else:
            cost = cost if type(cost) in (float, int) and math.isfinite(cost) and cost >= 0 else None
        metadata = {
            **({k:v for k,v in settings.items() if k in ('mode','model','prompt_version','max_calls','max_output_tokens')} if settings.get('foreground') else settings), "evidence_id": package_fingerprint(context),
            "request_id": self._identifier(data.get("id")),
            "response_model": self._identifier(data.get("model")),
            "usage": {**tokens, "cost_usd": cost},
        }
        error=data.get('error')
        status=error.get('code') if isinstance(error,dict) and type(error.get('code')) is int and 400<=error['code']<=599 else http_status
        if error or http_status>=400:
            detail=str(error.get('message','')).casefold() if isinstance(error,dict) else ''
            code=('provider_payment_required' if status==402 else 'provider_rate_limited' if status==429
                else 'provider_privacy_unavailable' if status==404 and ('data policy' in detail or 'data collection' in detail)
                else 'provider_no_route' if status==404
                else 'provider_tools_rejected' if status==400 and ('tool_choice' in detail or 'tool choice' in detail or 'tools' in detail)
                else 'provider_unavailable' if status>=500 else 'provider_request_rejected')
            metadata['diagnostic']={'code':code,'http_status':http_status,'provider_error_code':status}
        else:
            metadata['diagnostic']={'http_status':http_status}
        if not settings.get('foreground'):
            metadata.pop('diagnostic',None)
        message, finish_reason = None, None
        choices = None if data.get("error") else data.get("choices")
        if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict):
            choice = choices[0]
            if choice.get("finish_reason") in {"stop", "tool_calls", "length", "content_filter"}:
                message = choice.get("message")
                finish_reason = choice.get("finish_reason")
        if (settings.get('foreground') and settings.get('charging_profile','').startswith('preview-text-tools/')
                and isinstance(message,dict) and isinstance(message.get('tool_calls'),list) and len(message['tool_calls'])>1):
            metadata['diagnostic']['additional_tool_calls']=len(message['tool_calls'])-1
            metadata['diagnostic']['first_call_only']=True
        result={"message": message, "finish_reason": finish_reason, "inference": metadata}
        if settings.get('foreground'):
            result=json.loads(json.dumps(result,default=lambda v:str(v) if isinstance(v,Decimal) else None))
        return result

    @staticmethod
    def _identifier(value):
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", value):
            return value
        return None


class OpenRouterReviews(OpenRouterInference):
    def assess_instruction_test(self, context, settings):
        self.require_available(settings)
        return self.complete(context, settings, assessment_evidence(context),
                             system=ASSESSMENT_SYSTEM, schema=ASSESSMENT_SCHEMA,
                             name="instruction_test_assessment", output_key="assessment")


class OpenRouterPlanner(OpenRouterInference):
    prompt_version = 'campaign-planner-v8'

    def __init__(self, models, *, request_body: Callable[[dict, list[dict]], dict], transport=None):
        super().__init__(models, transport=transport)
        self.request_body = request_body

    def prepare_turn(self, context, history, settings):
        """Fit the actual wire request; omit complete oldest messages or tool pairs, never the new request."""
        context = {**context, 'conversation': list(context.get('conversation', []))}
        visible = list(history)
        while True:
            body = self.request_body(context, visible)
            try:
                self.encode_request(settings, body)
                return context, body
            except ReviewInferenceError:
                if context['conversation']:
                    context['conversation'].pop(0)
                    context['conversation_truncated'] = True
                elif visible:
                    visible.pop(0)
                    context['tool_history_truncated'] = True
                else:
                    raise ReviewInferenceError('The current message cannot fit the configured input limit. '
                                               'No model request was sent. Shorten the message before trying again.') from None

    def validate_turn(self, context, history, settings):
        """Check input limits without exposing the provider request body to callers."""
        self.prepare_turn(context, history, settings)

    def next_turn(self, context, history, settings):
        context, body = self.prepare_turn(context, history, settings)
        receipt = self.chat(context, settings, body)
        receipt['inference'].update(conversation_truncated=context.get('conversation_truncated', False),
                                    tool_history_truncated=context.get('tool_history_truncated', False),
                                    conversation_message_ids=[item.get('id') for item in context['conversation']])
        if settings.get('foreground'):
            from campaign_agent.ports.inference import ProviderError
            reason=receipt.get('finish_reason')
            diagnostic=receipt['inference'].get('diagnostic',{})
            if diagnostic.get('code'): raise ProviderError(diagnostic['code'])
            if reason=='length': raise ProviderError('model_output_limit')
            if reason=='content_filter' or isinstance(receipt.get('message'),dict) and receipt['message'].get('refusal'):
                raise ProviderError('model_refused')
        message = receipt['message']
        if receipt['finish_reason'] != 'tool_calls' or not isinstance(message, dict) or message.get('refusal'):
            if settings.get('foreground'): raise ProviderError('model_tool_call_missing')
            raise ValueError('The main model did not return a tool request.')
        calls = message.get('tool_calls')
        if receipt['inference'].get('diagnostic',{}).get('first_call_only') is True:
            calls=calls[:1]
        if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
            if settings.get('foreground'): raise ProviderError('model_tool_call_multiple')
            raise ValueError('The main model must return one tool request.')
        call = calls[0]
        function = call.get('function')
        if call.get('type') != 'function' or not isinstance(function, dict):
            if settings.get('foreground'): raise ProviderError('model_arguments_invalid')
            raise ValueError('The main model returned an unsupported call.')
        try:
            arguments = parse_json(function['arguments']) if isinstance(function.get('arguments'), str) else None
        except (ValueError,TypeError,RecursionError):
            if settings.get('foreground'): raise ProviderError('model_arguments_invalid') from None
            raise
        if settings.get('foreground') and (not isinstance(arguments,dict) or not isinstance(call.get('id'),str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',call['id']) or not isinstance(function.get('name'),str)):
            raise ProviderError('model_arguments_invalid')
        return {'call_id': call.get('id'), 'tool': function.get('name'), 'arguments': arguments,
                'inference': receipt['inference']}
