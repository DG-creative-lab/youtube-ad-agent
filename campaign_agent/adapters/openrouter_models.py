"""Bounded fixed-origin OpenRouter metadata probes. No completions or key retention."""
from urllib.parse import quote
from urllib.request import Request
from urllib.error import HTTPError, URLError
from time import monotonic, time

from campaign_agent.ports.inference import ProviderError
from .openrouter_reviews import parse_json, send_request

MAX_BYTES = 2_000_000
MAX_MODELS = 2000


class OpenRouterMetadata:
    def __init__(self, *, transport=None, monotonic_clock=monotonic, clock=time):
        self.transport = transport or send_request
        self.monotonic, self.clock = monotonic_clock, clock

    def _get(self, path, credential):
        started=self.monotonic()
        request=Request('https://openrouter.ai'+path,headers={'Authorization':'Bearer '+credential.key,'Accept':'application/json'})
        try:
            with self.transport(request,timeout=5) as response:
                raw=response.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES or self.monotonic()-started>=5:
                raise ValueError()
            data=parse_json(raw)
            if not isinstance(data,dict) or data.get('error') or 'data' not in data:
                raise ValueError()
            return data['data']
        except HTTPError as error:
            status=error.code
            error.close()
            raise ProviderError('credential_mismatch' if status in (401,403) else 'catalogue_unavailable') from None
        except (URLError,OSError,ValueError,TypeError,UnicodeError,RecursionError,TimeoutError):
            raise ProviderError('catalogue_unavailable') from None
        except Exception:
            raise ProviderError('catalogue_unavailable') from None

    def validate_key(self, credential):
        data=self._get('/api/v1/key',credential)
        if not isinstance(data,dict) or data.get('is_management_key') is not False or data.get('is_provisioning_key') is not False:
            raise ProviderError('credential_mismatch')
        if data.get('expires_at') is not None:
            from datetime import datetime
            try:
                instant=datetime.fromisoformat(data['expires_at'].replace('Z','+00:00'))
                if instant.tzinfo is None:
                    raise ValueError()
                expiry=instant.timestamp()
                if expiry<=self.clock():
                    raise ValueError()
            except (ValueError,TypeError,AttributeError,OverflowError):
                raise ProviderError('credential_mismatch') from None
        regions=data.get('allowed_data_regions')
        if regions is not None and (not isinstance(regions,list) or 'global' not in regions):
            raise ProviderError('credential_mismatch')
        # Introspection is validation data, never app identity or a retained billing record.
        remaining=data.get('limit_remaining')
        if remaining is not None and (type(remaining) not in (int,float) or not __import__('math').isfinite(remaining) or remaining<0):
            raise ProviderError('credential_mismatch')

    def models(self, credential):
        rows=self._get('/api/v1/models',credential)
        if not isinstance(rows,list) or len(rows)>MAX_MODELS:
            raise ProviderError('catalogue_unavailable')
        return rows

    def endpoints(self, credential, model):
        from campaign_agent.model_catalogue import model_id
        model_id(model)
        author,slug=model.split('/',1)
        data=self._get('/api/v1/models/'+quote(author,safe='')+'/'+quote(slug,safe='')+'/endpoints',credential)
        if not isinstance(data,dict) or not isinstance(data.get('endpoints'),list) or len(data['endpoints'])>100:
            raise ProviderError('catalogue_unavailable')
        return data['endpoints']
