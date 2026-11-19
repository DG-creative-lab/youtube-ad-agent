"""Safe diagnostics projected from the existing recovery journal, never a second log store."""
import json
from campaign_agent.ports.inference import ProviderError

FAILURES=frozenset(code for code in ProviderError.MESSAGES if code.startswith(('provider_','model_')))


def response_failure(receipt):
    info=receipt.get('inference') or {}
    code=(info.get('diagnostic') or {}).get('code')
    if code in FAILURES:
        return code
    reason=receipt.get('finish_reason')
    if reason=='length': return 'model_output_limit'
    message=receipt.get('message')
    if reason=='content_filter' or isinstance(message,dict) and message.get('refusal'):
        return 'model_refused'
    if reason!='tool_calls' or not isinstance(message,dict):
        return 'model_tool_call_missing'
    calls=message.get('tool_calls')
    if not isinstance(calls,list) or len(calls)!=1 and (info.get('diagnostic') or {}).get('first_call_only') is not True:
        return 'model_tool_call_multiple' if isinstance(calls,list) and len(calls)>1 else 'model_tool_call_missing'
    return None


def trace_projection(run_id, status, settings, rows):
    calls=[]
    for position,turn_state,turn_error,state,raw,created,updated,cost in rows:
        receipt=json.loads(raw) if raw else {}
        info=receipt.get('inference') or {}
        usage=info.get('usage') or {}
        diagnostic=info.get('diagnostic') or {}
        code=turn_error if turn_error in FAILURES else None
        # Historical receipts did not retain finish_reason=length, but their
        # independently recorded token usage still establishes exhaustion.
        if receipt and code is None:
            code=response_failure(receipt)
            if code=='model_tool_call_missing' and usage.get('output_tokens')==settings.get('max_output_tokens'):
                code='model_output_limit'
        failed=turn_state=='failed' or code is not None
        unknown=state in ('dispatching','unknown') and not receipt
        item={'position':position,'state':'failed' if failed else 'unknown' if unknown else 'received' if receipt else 'not_sent',
              'billing_state':state,'additional_tool_calls':diagnostic.get('additional_tool_calls',0),'code':code,'message':str(ProviderError(code)) if code else None,
              'http_status':diagnostic.get('http_status'),'provider_error_code':diagnostic.get('provider_error_code'),'finish_reason':receipt.get('finish_reason'),
              'request_id':info.get('request_id'),'input_tokens':usage.get('input_tokens'),
              'output_tokens':usage.get('output_tokens'),'cost_usd':cost,
              'recorded_duration_ms':round(max(0,updated-created)*1000) if created is not None and updated is not None else None}
        if failed and not item['message']:
            item['message']='The recorded model step failed. The original response did not retain a detailed error.'
        calls.append(item)
    phase='completed' if status!='running' else 'running'
    if status=='running' and calls:
        if calls[-1]['state']=='failed': phase='failed'
        elif calls[-1]['state']=='unknown': phase='unknown'
    return {'schema_version':1,'run_id':run_id,'status':phase,'model':settings.get('model'),
            'provider':settings.get('routing',{}).get('only',[]),'calls':calls}
