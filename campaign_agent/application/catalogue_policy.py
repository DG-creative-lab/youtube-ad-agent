"""Normalized advisory models and exact qualified endpoint selection; no inference."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from campaign_agent.ports.inference import ProviderError, model_id

ROUTE = re.compile(r'[a-z0-9_.-]+(?:/[a-z0-9_.-]+)*')
PRICES = {'prompt','completion','request','image','web_search','internal_reasoning',
          'input_cache_read','input_cache_write','input_cache_write_1h','discount','audio','input_audio','output_audio'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def price(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,12}(?:\.\d{1,18})?',value):
        raise ProviderError('catalogue_unavailable')
    try:
        result=Decimal(value)
    except InvalidOperation:
        raise ProviderError('catalogue_unavailable') from None
    if not result.is_finite() or result<0:
        raise ProviderError('catalogue_unavailable')
    return result


def decimal_text(value):
    return format(value,'f')


def pricing(value, *, text_tools=False, max_input_tokens=None):
    if not isinstance(value,dict) or not {'prompt','completion'}<=value.keys() or set(value)-PRICES-{'overrides'}:
        raise ProviderError('catalogue_unavailable')
    normalized={k:decimal_text(price('0' if k=='discount' and type(v) is int and v==0 else v))
                for k,v in value.items() if k!='overrides'}
    if value.get('overrides'):
        # Foreground requests enforce a conservative full-wire byte/token ceiling.
        # Only known prompt-length tiers strictly beyond that ceiling are inert.
        tiers = value['overrides']
        if (type(max_input_tokens) is not int or max_input_tokens <= 0
                or not isinstance(tiers, list) or len(tiers) > 100):
            raise ProviderError('route_unqualified')
        for tier in tiers:
            if (not isinstance(tier, dict) or type(tier.get('min_prompt_tokens')) is not int
                    or tier['min_prompt_tokens'] <= max_input_tokens
                    or set(tier) - PRICES - {'min_prompt_tokens'}
                    or not set(tier) & PRICES):
                raise ProviderError('route_unqualified')
            # Even an unreachable tier must have a recognized, finite price shape.
            pricing({**{k: value[k] for k in ('prompt', 'completion')},
                     **{k: v for k, v in tier.items() if k != 'min_prompt_tokens'}}, text_tools=text_tools)
    allowed = {'prompt','completion','request','input_cache_read','input_cache_write','input_cache_write_1h'}
    if text_tools:
        # Text requests enable neither media nor provider-side web-search tools.
        allowed |= {'image','web_search','audio','input_audio','output_audio'}
    if any(price(v)>0 for k,v in normalized.items() if k not in allowed):
        raise ProviderError('route_unqualified')
    return normalized


def endpoint_fingerprint(endpoint):
    return fingerprint({k:endpoint.get(k) for k in ('tag','model_id','pricing','supported_parameters',
        'supports_tool_choice','context_length','max_prompt_tokens','max_completion_tokens','supports_implicit_caching')})


def compatible_model(raw, task):
    """Model-level facts must support the selected task as well as its endpoint."""
    architecture=raw.get('architecture')
    parameters=raw.get('supported_parameters')
    if (not isinstance(architecture,dict) or not isinstance(parameters,list)
            or any(not isinstance(item,str) for item in parameters)
            or not isinstance(architecture.get('input_modalities'),list) or 'text' not in architecture['input_modalities']
            or architecture.get('output_modalities')!=['text']):
        return False
    required={'planner':{'tools','tool_choice'},'structured_review':{'response_format','structured_outputs'}}
    return task in required and required[task]<=set(parameters)


def normalize(rows, profiles=(), *, now, live_routes=False):
    if not isinstance(rows,list) or len(rows)>2000:
        raise ProviderError('catalogue_unavailable')
    result=[]; seen=set()
    for raw in rows:
        try:
            if not isinstance(raw,dict):
                raise ProviderError('catalogue_unavailable')
            ident=model_id(raw.get('id'))
            if ident in seen:
                raise ProviderError('catalogue_unavailable')
            seen.add(ident)
            base=raw.get('pricing')
            if not isinstance(base,dict) or not {'prompt','completion'}<=base.keys():
                raise ProviderError('catalogue_unavailable')
            amounts = {}
            for key in ("prompt", "completion"):
                try:
                    amounts[key] = decimal_text(price(base[key]) * 1_000_000)
                except ProviderError:
                    amounts[key] = None
            try:
                pricing(base, text_tools=live_routes)
                simple_prices=True
            except ProviderError:
                simple_prices=False
            name=raw.get('name')
            if not isinstance(name,str) or not 1<=len(name)<=200 or any(ord(c)<32 for c in name):
                raise ProviderError('catalogue_unavailable')
            architecture=raw.get('architecture',{})
            parameters=raw.get('supported_parameters',[])
            if not isinstance(architecture,dict) or not isinstance(parameters,list) or any(not isinstance(x,str) for x in parameters):
                raise ProviderError('catalogue_unavailable')
            compatible=any(compatible_model(raw,task) for task in ('planner','structured_review'))
            state='candidate' if compatible else 'blocked'
            reasons=['endpoint_qualification_required'] if compatible else ['unsupported_capabilities']
            # Model-wide pricing is advisory. Live endpoint rates decide availability.
            if not simple_prices and not live_routes:
                state,reasons='blocked',['unsupported_pricing']
            elif compatible and any(p.model==ident and p.expires_at>now and p.evidence
                    and any(compatible_model(raw,task) for task in p.tasks) for p in profiles):
                state,reasons='eligible',[]
            result.append({'id':ident,'name':name,'input_usd_per_million':amounts['prompt'],
                           'output_usd_per_million':amounts['completion'],
                           'supports_tools': isinstance(architecture.get("input_modalities"), list)
                               and "text" in architecture["input_modalities"]
                               and architecture.get("output_modalities") == ["text"]
                               and {"tools", "tool_choice"} <= set(parameters),
                           'state':state,'reason_codes':reasons})
        except ProviderError as error:
            # Unsupported identities are omitted. Unknown prices remain unavailable.
            if error.code=='invalid_request':
                continue
            raise
    return sorted(result,key=lambda row:row['id'])


def select_endpoint(model, task, endpoints, profiles, now):
    if not isinstance(endpoints,list) or len(endpoints)>100:
        raise ProviderError('catalogue_unavailable')
    for endpoint in endpoints:
        if not isinstance(endpoint,dict):
            continue
        tag=endpoint.get('tag')
        if not isinstance(tag,str) or not ROUTE.fullmatch(tag) or endpoint.get('model_id')!=model:
            continue
        params=endpoint.get('supported_parameters')
        if not isinstance(params,list) or any(not isinstance(x,str) for x in params):
            continue
        for profile in profiles:
            if (profile.model!=model or profile.endpoint!=tag or task not in profile.tasks or not profile.evidence
                    or profile.expires_at<=now or profile.endpoint_hash!=endpoint_fingerprint(endpoint)
                    or not 0<profile.max_input_tokens<=2_000_000 or not 0<profile.max_output_tokens<=512
                    or profile.output_cap_parameter not in {'max_tokens','max_completion_tokens'}):
                continue
            wanted={profile.output_cap_parameter}
            if task=='planner':
                wanted|={'tools','tool_choice'}
                if not profile.version.startswith('preview-text-tools/'):
                    wanted.add('parallel_tool_calls')
                choices=endpoint.get('supports_tool_choice',{})
                if not isinstance(choices,dict) or choices.get('required') is not True:
                    continue
            else:
                wanted|={'response_format','structured_outputs'}
            if not wanted<=set(params):
                continue
            try:
                rates=pricing(endpoint.get('pricing'), text_tools=profile.version.startswith('preview-text-tools/'),
                              max_input_tokens=profile.max_input_tokens if profile.version.startswith('preview-text-tools/') else None)
                ceilings={k:price(v) for k,v in {'prompt':profile.max_prompt_usd_per_million,
                    'completion':profile.max_completion_usd_per_million,'request':profile.max_request_usd}.items()}
                if (price(rates['prompt'])*1_000_000>ceilings['prompt'] or price(rates['completion'])*1_000_000>ceilings['completion']
                        or price(rates.get('request','0'))>ceilings['request']):
                    continue
            except ProviderError:
                continue
            return {'model':model,'profile':task,'charging_profile':profile.version,'endpoint_hash':profile.endpoint_hash,
                'charging_profile_expires_at':profile.expires_at,'max_calls':8 if task=='planner' else 1,
                'max_input_tokens':profile.max_input_tokens,'max_output_tokens':profile.max_output_tokens,
                'output_cap_parameter':profile.output_cap_parameter,'max_request_bytes':32000,
                'prices':rates,'policy_version':'openrouter-session/v1','privacy':'no_training_safety_retention_may_apply',
                'routing':{'only':[tag],'order':[tag],'allow_fallbacks':False,'require_parameters':True,
                    'data_collection':'deny','max_price':{k:decimal_text(v) for k,v in ceilings.items()}}}
    raise ProviderError('route_unqualified')


def maximum_cost(settings):
    """Reserve all-input cache writes conservatively; never assume a cache hit."""
    rates=settings['prices']
    base=price(rates['prompt'])
    write=max(price(rates.get(k,'0')) for k in ('input_cache_write','input_cache_write_1h'))
    input_rate=max(base+write,price(rates.get('input_cache_read','0')))
    return (input_rate*settings['max_input_tokens']
            +price(rates['completion'])*settings['max_output_tokens']+price(rates.get('request','0')))


def select_live_endpoint(model, task, endpoints, now, *, previous=None):
    """Qualify current text/tool routes, pin one endpoint and fence price drift."""
    from campaign_agent.ports.inference import ChargingProfile
    if not isinstance(endpoints,list) or len(endpoints)>100:
        raise ProviderError('catalogue_unavailable')
    if previous is not None and previous['charging_profile_expires_at']<=now:
        raise ProviderError('selection_stale')
    candidates=[]; failures=[]
    for endpoint in endpoints:
        if not isinstance(endpoint,dict):
            continue
        tag=endpoint.get('tag')
        if not isinstance(tag,str) or not ROUTE.fullmatch(tag) or endpoint.get('model_id')!=model:
            continue
        if previous is not None and previous['routing']['only']!=[tag]:
            continue
        try:
            params=endpoint.get('supported_parameters')
            if not isinstance(params,list) or any(not isinstance(x,str) for x in params):
                raise ProviderError('route_tools_unsupported')
            if task=='planner':
                if not {'tools','tool_choice'}<=set(params):
                    raise ProviderError('route_tools_unsupported')
                choice=endpoint.get('supports_tool_choice',{})
                if not isinstance(choice,dict) or choice.get('required') is not True:
                    raise ProviderError('route_required_choice_unsupported')
            elif task!='structured_review' or not {'response_format','structured_outputs'}<=set(params):
                raise ProviderError('route_structured_unsupported')
            cap=next((k for k in ('max_completion_tokens','max_tokens') if k in params),None)
            if cap is None:
                raise ProviderError('route_output_cap_unsupported')
            context=endpoint.get('context_length')
            prompt=endpoint.get('max_prompt_tokens')
            completion=endpoint.get('max_completion_tokens')
            if (type(context) is not int or context<=512 or prompt is not None and (type(prompt) is not int or prompt<=0)
                    or completion is not None and (type(completion) is not int or completion<512)):
                raise ProviderError('route_context_unsupported')
            try:
                rates=pricing(endpoint.get('pricing'),text_tools=True,
                              max_input_tokens=min(32000,context-512,prompt or 32000))
            except ProviderError:
                raw_prices=endpoint.get('pricing')
                reason='unsupported_pricing'
                if isinstance(raw_prices,dict):
                    if raw_prices.get('overrides'):
                        reason='route_conditional_pricing'
                    elif set(raw_prices)-PRICES-{'overrides'}:
                        reason='route_unknown_pricing'
                    elif raw_prices.get('internal_reasoning') not in (None,'0','0.0','0.00'):
                        reason='route_reasoning_pricing'
                raise ProviderError(reason) from None
            profile=ChargingProfile(model=model, endpoint=tag, version='preview-text-tools/live-v2',
                endpoint_hash=endpoint_fingerprint(endpoint),
                expires_at=previous['charging_profile_expires_at'] if previous is not None else now+3600,
                tasks=(task,),max_input_tokens=min(32000,context-512,prompt or 32000),
                output_cap_parameter=cap,
                max_prompt_usd_per_million=decimal_text(price(rates['prompt'])*1_000_000),
                max_completion_usd_per_million=decimal_text(price(rates['completion'])*1_000_000),
                max_request_usd=rates.get('request','0'),evidence='Current OpenRouter text/tool endpoint metadata')
            selected=select_endpoint(model,task,[endpoint],[profile],now)
            candidates.append(selected)
        except ProviderError as error:
            failures.append(error.code if error.code.startswith('route_') else 'unsupported_pricing')
    if not candidates:
        if previous is not None:
            raise ProviderError('selection_stale')
        # Report the reason reached by the most compatible route, not arbitrary provider prose.
        priority=('route_conditional_pricing','route_unknown_pricing','route_reasoning_pricing','unsupported_pricing','route_context_unsupported','route_output_cap_unsupported',
                  'route_required_choice_unsupported','route_structured_unsupported','route_tools_unsupported')
        raise ProviderError(next((code for code in priority if code in failures),'route_unavailable'))
    selected=min(candidates,key=lambda row:(maximum_cost(row),row['routing']['only'][0]))
    if previous is not None and any(previous.get(k)!=v for k,v in selected.items()):
        raise ProviderError('selection_stale')
    return selected
