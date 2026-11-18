"""Normalized advisory models and exact qualified endpoint selection; no inference."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from campaign_agent.ports.inference import ProviderError, model_id

ROUTE = re.compile(r'[a-z0-9_.-]+(?:/[a-z0-9_.-]+)*')
PRICES = {'prompt','completion','request','image','web_search','internal_reasoning',
          'input_cache_read','input_cache_write','input_cache_write_1h','audio','input_audio','output_audio'}


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


def pricing(value):
    if not isinstance(value,dict) or not {'prompt','completion'}<=value.keys() or set(value)-PRICES-{'overrides'}:
        raise ProviderError('catalogue_unavailable')
    normalized={k:decimal_text(price(v)) for k,v in value.items() if k!='overrides'}
    if value.get('overrides'):
        # A reviewed charging profile for conditional prices is a later qualification.
        raise ProviderError('route_unqualified')
    if any(price(v)>0 for k,v in normalized.items() if k not in {'prompt','completion','request'}):
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
            or architecture.get('input_modalities')!=['text'] or architecture.get('output_modalities')!=['text']):
        return False
    required={'planner':{'tools','tool_choice'},'structured_review':{'response_format','structured_outputs'}}
    return task in required and required[task]<=set(parameters)


def normalize(rows, profiles=(), *, now):
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
            amounts={key:decimal_text(price(base[key])) for key in ('prompt','completion')}
            try:
                pricing(base)
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
            if not simple_prices:
                state,reasons='blocked',['unsupported_pricing']
            elif compatible and any(p.model==ident and p.expires_at>now and p.evidence
                    and any(compatible_model(raw,task) for task in p.tasks) for p in profiles):
                state,reasons='eligible',[]
            result.append({'id':ident,'name':name,'input_usd_per_million':decimal_text(price(amounts['prompt'])*1_000_000),
                           'output_usd_per_million':decimal_text(price(amounts['completion'])*1_000_000),
                           'state':state,'reason_codes':reasons})
        except ProviderError as error:
            # Invalid prices/identities are never invented as zero-priced display rows.
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
                wanted|={'tools','tool_choice','parallel_tool_calls'}
                choices=endpoint.get('supports_tool_choice',{})
                if not isinstance(choices,dict) or choices.get('required') is not True:
                    continue
            else:
                wanted|={'response_format','structured_outputs'}
            if not wanted<=set(params):
                continue
            try:
                rates=pricing(endpoint.get('pricing'))
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
