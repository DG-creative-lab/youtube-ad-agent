"""Metadata wire contract and display/qualification separation, with fake HTTP only."""
import io
import json
import unittest
from urllib.error import HTTPError

from campaign_agent.adapters.openrouter_models import OpenRouterMetadata,MAX_BYTES
from campaign_agent.adapters.fixture_access import AuthoredProviderMetadata
from campaign_agent.model_catalogue import normalize,select_endpoint
from campaign_agent.ports.inference import ForegroundCredential,ProviderError


class OpenRouterMetadataTests(unittest.TestCase):
    def setUp(self):
        self.key=ForegroundCredential('authored-key-quoted-"-backslash-\\-sentinel')
        self.fixture=AuthoredProviderMetadata()

    def adapter(self,data,*,ticks=None):
        calls=[]
        def transport(request,*,timeout):
            calls.append((request,timeout))
            raw=data if isinstance(data,bytes) else json.dumps({'data':data}).encode()
            if ticks is not None:ticks[0]+=6
            return io.BytesIO(raw)
        return OpenRouterMetadata(transport=transport,monotonic_clock=(lambda:ticks[0]) if ticks is not None else __import__('time').monotonic),calls

    def test_fixed_get_paths_encoded_model_segment_and_key_only_authorization(self):
        adapter,calls=self.adapter(self.fixture.rows)
        self.assertEqual(adapter.models(self.key),self.fixture.rows)
        request,timeout=calls[0]
        self.assertEqual(timeout,5);self.assertEqual(request.get_method(),'GET')
        self.assertEqual(request.full_url,'https://openrouter.ai/api/v1/models')
        self.assertEqual(request.get_header('Authorization'),'Bearer '+self.key.key)
        self.assertIsNone(request.data)
        self.assertNotIn(self.key.key,repr(self.key))
        adapter,calls=self.adapter({'endpoints':[]})
        adapter.endpoints(self.key,'fixture/model:free')
        self.assertEqual(calls[0][0].full_url,'https://openrouter.ai/api/v1/models/fixture/model%3Afree/endpoints')
        before=len(calls)
        for ident in ('https://attacker.test/model','../model','openrouter/auto','fixture/model/further'):
            with self.assertRaises(ProviderError):adapter.endpoints(self.key,ident)
        self.assertEqual(len(calls),before)

    def test_response_size_duplicate_fields_and_elapsed_admission_are_bounded_and_sanitized(self):
        for data in (b'x'*(MAX_BYTES+1),b'{"data":[],"data":[]}',{'unexpected':'shape'}):
            with self.subTest(data_type=type(data).__name__):
                adapter,_=self.adapter(data)
                with self.assertRaises(ProviderError) as raised:adapter.models(self.key)
                self.assertNotIn(self.key.key,str(raised.exception))
        tick=[0.0];adapter,calls=self.adapter([],ticks=tick)
        with self.assertRaises(ProviderError):adapter.models(self.key)
        self.assertEqual(calls[0][1],5)
        # This proves elapsed admission rejection and socket timeout argument, not hard DNS/slow-stream cancellation.

    def test_introspection_rejects_management_expiry_restrictions_and_provider_errors(self):
        valid={'is_management_key':False,'is_provisioning_key':False,'expires_at':None,'limit_remaining':None}
        adapter,_=self.adapter(valid);adapter.validate_key(self.key)
        for changed in ({'is_management_key':True},{'is_provisioning_key':True},{'expires_at':'2000-01-01T00:00:00Z'},
                        {'expires_at':'2050-01-01'},{'allowed_data_regions':['europe']},{'limit_remaining':float('inf')}):
            adapter,_=self.adapter({**valid,**changed})
            with self.assertRaises(ProviderError):adapter.validate_key(self.key)
        def fail(request,*,timeout):
            raise HTTPError(request.full_url,302,self.key.key,{},io.BytesIO(b'private error'))
        with self.assertRaises(ProviderError) as raised:OpenRouterMetadata(transport=fail).models(self.key)
        import traceback
        self.assertNotIn(self.key.key,''.join(traceback.format_exception(raised.exception)))

    def test_complex_or_unknown_charge_models_do_not_hide_valid_entries_but_cannot_qualify(self):
        base=self.fixture.rows[0]
        rows=[base,{**base,'id':'fixture/conditional','pricing':{'prompt':'0.000001','completion':'0.000002','overrides':[{'utc_start':1,'prompt':'0.1'}]}},
              {**base,'id':'fixture/reasoning','pricing':{'prompt':'0','completion':'0','internal_reasoning':'0.1'}},
              {**base,'id':'fixture/new-unit','pricing':{'prompt':'0','completion':'0','unknown_unit':'0.1'}}]
        result={r['id']:r for r in normalize(rows,self.fixture.profiles)}
        self.assertEqual(result['fixture/tool-model']['state'],'eligible')
        for ident in ('fixture/conditional','fixture/reasoning','fixture/new-unit'):
            self.assertEqual(result[ident]['state'],'blocked')
        self.assertEqual(result['fixture/conditional']['input_usd_per_million'],'1.000000')
        with self.assertRaises(ProviderError):select_endpoint('fixture/tool-model','planner',[self.fixture.endpoint],(),__import__('time').time())

