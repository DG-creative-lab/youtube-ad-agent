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
        rows.append({**base, 'id': 'fixture/dynamic-router', 'pricing': {'prompt': '-1', 'completion': '-1'}})
        result={r['id']:r for r in normalize(rows,self.fixture.profiles,now=0)}
        self.assertIsNone(result['fixture/dynamic-router']['input_usd_per_million'])
        self.assertEqual(result['fixture/dynamic-router']['state'], 'blocked')
        self.assertEqual(result['fixture/tool-model']['state'],'eligible')
        for ident in ('fixture/conditional','fixture/reasoning','fixture/new-unit'):
            self.assertEqual(result[ident]['state'],'blocked')
        self.assertEqual(result['fixture/conditional']['input_usd_per_million'],'1.000000')
        with self.assertRaises(ProviderError):select_endpoint('fixture/tool-model','planner',[self.fixture.endpoint],(),__import__('time').time())

    def test_live_catalogue_defers_aggregate_pricing_to_actual_endpoint(self):
        raw={**self.fixture.rows[0], 'pricing':{'prompt':'0','completion':'0','overrides':[{'min_prompt_tokens':100000,'prompt':'1'}]}}
        self.assertEqual(normalize([raw],now=0)[0]['state'],'blocked')
        self.assertEqual(normalize([raw],now=0,live_routes=True)[0]['state'],'candidate')

    def test_live_route_uses_viable_cheapest_provider_and_never_switches_after_selection(self):
        from campaign_agent.application.catalogue_policy import select_live_endpoint, maximum_cost
        from copy import deepcopy
        from decimal import Decimal
        base=deepcopy(self.fixture.endpoint)
        base['supported_parameters'].remove('parallel_tool_calls')
        cheap={**base,'tag':'vendor/cheap','pricing':{'prompt':'0.000001','completion':'0.000002','input_cache_read':'0.0000001','input_cache_write':'0.000002','discount':0}}
        expensive={**base,'tag':'vendor/other','pricing':{'prompt':'0.000004','completion':'0.000002'}}
        unusable={**cheap,'tag':'vendor/no-required','supports_tool_choice':{'required':False}}
        selected=select_live_endpoint('fixture/tool-model','planner',[unusable,expensive,cheap],100)
        self.assertEqual(selected['routing']['only'],['vendor/cheap'])
        self.assertEqual(maximum_cost(selected),Decimal('0.095488'))
        self.assertEqual(selected['charging_profile_expires_at'],3700)
        self.assertEqual(select_live_endpoint('fixture/tool-model','planner',[cheap,expensive],101,previous=selected),selected)
        for endpoints,now in (([expensive],102),([cheap],3700),([{**cheap,'pricing':{'prompt':'0','completion':'0'}}],103)):
            with self.subTest(now=now),self.assertRaises(ProviderError) as raised:
                select_live_endpoint('fixture/tool-model','planner',endpoints,now,previous=selected)
            self.assertEqual(raised.exception.code,'selection_stale')


class ModelSearchTests(unittest.TestCase):
    def test_preview_catalogue_keeps_models_outside_enabled_routes_visible(self):
        from unittest.mock import patch
        from preview.providers import LiveMetadata, profiles
        fixture = AuthoredProviderMetadata()
        gptoss = {**fixture.rows[0], "id": "openai/gpt-oss-120b", "name": "OpenAI GPT-OSS 120B"}
        with patch.object(OpenRouterMetadata, "models", return_value=[gptoss]):
            rows = LiveMetadata().models(ForegroundCredential("authored-key"))
        self.assertEqual(rows, [gptoss])
        normalized = normalize(rows, profiles(), now=0)
        self.assertEqual(normalized[0]["id"], "openai/gpt-oss-120b")
        self.assertEqual(normalized[0]["state"], "candidate")
        with self.assertRaises(ProviderError):
            select_endpoint(gptoss["id"], "planner", [fixture.endpoint], profiles(), 0)

    def test_search_punctuation_case_pagination_and_selectable_order(self):
        from campaign_agent.adapters.catalogue_cache import CatalogueCache
        cache = CatalogueCache()
        models = [
            {"id": "openai/gpt-oss-120b", "name": "OpenAI GPT-OSS 120B", "state": "candidate"},
            {"id": "openai/gpt-4.1-mini", "name": "OpenAI GPT-4.1 Mini", "state": "eligible"},
        ]
        models += [{"id": f"vendor/model-{index:02d}", "name": f"Model {index}", "state": "candidate"}
                   for index in range(25)]
        entry = {"models": models, "cursors": {}}
        for query in ("gptoss", "GPT-OSS", "gpt oss", "openai/gpt-oss"):
            with self.subTest(query=query):
                rows, cursor = cache.page(entry, query, None)
                self.assertEqual([row["id"] for row in rows], ["openai/gpt-oss-120b"])
                self.assertIsNone(cursor)
        first, cursor = cache.page(entry, "", None)
        self.assertEqual(first[0]["id"], "openai/gpt-4.1-mini")
        self.assertEqual(len(first), 20)
        second, end = cache.page(entry, "", cursor)
        self.assertEqual(len(second), 7)
        self.assertIsNone(end)
        self.assertFalse({row["id"] for row in first} & {row["id"] for row in second})
        with self.assertRaises(ProviderError):
            cache.page(entry, "different query", cursor)


class CatalogueFilterTests(unittest.TestCase):
    def setUp(self):
        from campaign_agent.adapters.catalogue_cache import CatalogueCache
        self.cache = CatalogueCache()
        self.rows = [
            {"id": f"fixture/model-{index:02d}", "name": f"Model {index}", "state": "candidate",
             "supports_tools": True, "input_usd_per_million": str(index),
             "output_usd_per_million": str(index * 2)}
            for index in range(25)
        ]
        self.rows.extend([
            {"id": "fixture/no-tools", "name": "No tools", "state": "eligible", "supports_tools": False,
             "input_usd_per_million": "0", "output_usd_per_million": "0"},
            {"id": "fixture/unknown", "name": "Unknown price", "state": "blocked", "supports_tools": True,
             "input_usd_per_million": None, "output_usd_per_million": None},
        ])
        self.entry = {"models": list(reversed(self.rows)), "cursors": {},
                      "provider_order": [row["id"] for row in reversed(self.rows)]}

    def test_tools_and_price_caps_apply_before_global_sort_and_pagination(self):
        first, cursor = self.cache.page(self.entry, "", None, tools_only=True, sort="pricing-low-to-high")
        self.assertEqual([row["id"] for row in first], [f"fixture/model-{index:02d}" for index in range(20)])
        second, end = self.cache.page(self.entry, "", cursor, tools_only=True, sort="pricing-low-to-high")
        self.assertEqual([row["id"] for row in second],
                         [f"fixture/model-{index:02d}" for index in range(20, 25)] + ["fixture/unknown"])
        self.assertIsNone(end)
        capped, _ = self.cache.page(self.entry, "", None, tools_only=True,
                                   max_input_price="2", max_output_price="2", sort="pricing-low-to-high")
        self.assertEqual([row["id"] for row in capped], ["fixture/model-00", "fixture/model-01"])
        zero, _ = self.cache.page(self.entry, "", None, tools_only=True,
                                  max_input_price="0", max_output_price="0")
        self.assertEqual([row["id"] for row in zero], ["fixture/model-00"])
        descending, cursor = self.cache.page(self.entry, "", None, tools_only=True, sort="pricing-high-to-low")
        self.assertEqual(descending[0]["id"], "fixture/model-24")
        final, _ = self.cache.page(self.entry, "", cursor, tools_only=True, sort="pricing-high-to-low")
        self.assertEqual(final[-1]["id"], "fixture/unknown")

    def test_cursor_cannot_change_filters_or_order(self):
        _, cursor = self.cache.page(self.entry, "", None, tools_only=True, sort="pricing-low-to-high")
        for filters in ({"tools_only": False, "sort": "pricing-low-to-high"},
                        {"tools_only": True, "sort": "pricing-high-to-low"},
                        {"tools_only": True, "sort": "pricing-low-to-high", "max_input_price": "20"}):
            with self.subTest(filters=filters), self.assertRaises(ProviderError):
                self.cache.page(self.entry, "", cursor, **filters)

    def test_provider_rank_order_is_preserved_without_inventing_scores(self):
        for sort in ("most-popular", "intelligence-high-to-low"):
            with self.subTest(sort=sort):
                rows, _ = self.cache.page(self.entry, "", None, tools_only=True, sort=sort)
                self.assertEqual(rows[0]["id"], "fixture/unknown")
                self.assertEqual(rows[1]["id"], "fixture/model-24")
                self.assertNotIn("rating", rows[0])

    def test_live_metadata_requests_openrouter_tool_filter_and_named_rank(self):
        from urllib.parse import urlsplit, parse_qs
        from unittest.mock import patch
        from preview.providers import LiveMetadata
        calls = []
        def transport(request, *, timeout):
            calls.append(request)
            return io.BytesIO(b'{"data":[]}')
        metadata = LiveMetadata()
        metadata.transport = transport
        metadata.models(ForegroundCredential("authored-key"), sort="intelligence-high-to-low")
        query = parse_qs(urlsplit(calls[0].full_url).query)
        self.assertEqual(query["supported_parameters"], ["tools,tool_choice"])
        self.assertEqual(query["output_modalities"], ["text"])
        self.assertEqual(query["sort"], ["intelligence-high-to-low"])
        self.assertNotIn("authored-key", calls[0].full_url)
