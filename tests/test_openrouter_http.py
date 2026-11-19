"""Actual foreground HTTP commands with authored identity/key/catalogue responses only."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
from threading import Event,Lock
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch,Mock
from uuid import uuid4

from starlette.testclient import TestClient
from campaign_agent.adapters.fixture_access import offline_fixture,AuthoredProviderMetadata
from campaign_agent.bootstrap.hosted import create_hosted_application as HostedApplication
from campaign_agent.ports.inference import ProviderError


class OpenRouterHttpTests(unittest.TestCase):
    def setUp(self):
        self.path=Path(self.enterContext(TemporaryDirectory()))/'provider.sqlite3'
        self.app=offline_fixture(self.path)
        self.metadata=self.app.provider_sessions.metadata
        self.service=self.app.provider_sessions
        self.key=self.metadata.keys[0];self.tab=uuid4().hex
        self.buyer=self.client('buyer-a');self.other=self.client('buyer-b');self.reviewer=self.client('reviewer-a')
        self.metadata.requests.clear()

    def client(self,profile):
        c=self.enterContext(TestClient(self.app.staff,base_url=self.app.staff_origin))
        self.assertEqual(c.post('/fixture',json={'profile':profile},headers={'Origin':self.app.staff_origin}).status_code,200)
        c.headers.update({'Origin':self.app.staff_origin,'X-CSRF-Token':c.get('/api/session').headers['x-csrf-token']})
        return c

    def post(self,action,data,*,client=None,key=True,status=200):
        header={'X-OpenRouter-Key':self.key} if key else {}
        r=(client or self.buyer).post('/api/openrouter/'+action,json=data,headers=header)
        self.assertEqual(r.status_code,status,r.text)
        self.assertEqual(r.headers['cache-control'],'no-store')
        self.assertNotIn(self.key,r.text)
        return r.json()

    def connect(self,**extra):
        return self.post('connect',dict(operation_id=uuid4().hex,tab_id=self.tab,**extra))

    def models(self,connection,**extra):
        return self.post('models',dict(connection_id=connection,tab_id=self.tab,search='',cursor=None,**extra))

    def selection(self,connection,catalogue,**extra):
        return dict(operation_id=uuid4().hex,connection_id=connection,tab_id=self.tab,
                    model_id='fixture/tool-model',catalogue_revision=catalogue,profile='planner',max_run_cost_usd='0',**extra)

    def test_model_filters_validate_and_preserve_source_ranking(self):
        connection = self.connect()["connection_id"]
        for invalid in ({"sort": []}, {"sort": "invented-rating"}, {"tools_only": "yes"},
                        {"max_input_price": "-1"}, {"max_output_price": "NaN"}):
            self.metadata.requests.clear()
            self.post("models", {"connection_id": connection, "tab_id": self.tab,
                                  "search": "", "cursor": None, **invalid}, status=400)
            self.assertEqual(self.metadata.requests, [])
        base = self.metadata.rows[0]
        self.metadata.rows.extend([
            {**base, "id": "fixture/ranked-first", "name": "Ranking first"},
            {**base, "id": "fixture/no-tools", "name": "No tools", "supported_parameters": []},
        ])
        self.metadata.rows.append({**base, "id": self.key, "name": "Rejected credential echo"})
        self.metadata.rows.reverse()
        result = self.models(connection, tools_only=True, sort="most-popular",
                             max_input_price="0", max_output_price="0")
        self.assertEqual([row["id"] for row in result["models"]],
                         ["fixture/ranked-first", "fixture/tool-model"])
        self.assertNotIn("rating", result["models"][0])
        entry = self.service.cache.get(connection, self.service.clock())
        self.assertNotIn(self.key, json.dumps(entry))

    def test_connect_catalogue_selection_replay_and_no_domain_or_secret_write(self):
        self.assertIs(self.buyer.get('/api/mode').json()['openrouterAvailable'], True)
        before=self.buyer.get('/api/campaign').json()
        op=uuid4().hex;args={'operation_id':op,'tab_id':self.tab}
        connected=self.post('connect',args)
        self.assertEqual(self.post('connect',args),connected)
        connection=connected['connection_id'];self.assertEqual(len(connection),64)
        catalogue=self.models(connection)
        self.assertEqual(catalogue['models'][0]['input_usd_per_million'],'0')
        self.assertEqual(catalogue['models'][0]['state'],'eligible')
        selected=self.selection(connection,catalogue['catalogue_revision'])
        result=self.post('select',selected)
        self.assertEqual(self.post('select',selected),result)
        self.assertEqual(result['routing']['only'],['fixture/qualified'])
        self.assertFalse(result['routing']['allow_fallbacks'])
        self.assertEqual(self.buyer.get('/api/campaign').json(),before)
        with closing(sqlite3.connect(self.path)) as db:
            raw='\n'.join(db.iterdump())
            self.assertNotIn(self.key,raw)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_selections').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM agent_runs').fetchone()[0],0)
        self.assertEqual(set(self.metadata.requests),{'key','models','endpoints'})

    def test_foreign_scope_session_tab_key_and_replay_fail_before_provider_io(self):
        args={'operation_id':uuid4().hex,'tab_id':self.tab}
        connection=self.post('connect',args)['connection_id']
        self.metadata.requests.clear()
        body={'connection_id':connection,'tab_id':self.tab,'search':'','cursor':None}
        self.post('models',body,client=self.other,status=403)
        self.post('models',{**body,'tab_id':uuid4().hex},status=403)
        old=self.key;self.key=self.metadata.keys[1]
        self.post('models',body,status=403)
        self.post('connect',args,status=403)
        self.key=old
        signed_in_again=self.client('buyer-a')
        self.post('models',body,client=signed_in_again,status=403)
        self.post('connect',{'operation_id':uuid4().hex,'tab_id':self.tab},client=self.reviewer,status=403)
        self.assertEqual(self.metadata.requests,[])
        self.buyer.post('/api/session/context',json={'campaign_id':'campaign-a-brand2'})
        self.post('models',body,status=403)
        self.assertEqual(self.metadata.requests,[])

    def test_resume_operation_is_durable_and_cannot_drop_or_swap_original_reference(self):
        connection=self.connect()['connection_id']
        op=uuid4().hex
        body={'operation_id':op,'tab_id':self.tab,'resume_connection_id':connection}
        resumed=self.post('connect',body)
        self.assertEqual(resumed['connection_id'],connection)
        self.assertEqual(self.post('connect',body),resumed)
        self.metadata.requests.clear()
        self.post('connect',{'operation_id':op,'tab_id':self.tab},status=409)
        self.post('connect',{**body,'resume_connection_id':'f'*64},status=409)
        self.assertEqual(self.metadata.requests,[])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_connections').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_connection_operations').fetchone()[0],2)

    def test_current_authority_and_binding_checked_on_cache_hits_and_outage_disconnect(self):
        connection=self.connect()['connection_id'];self.models(connection)
        self.metadata.requests.clear()
        self.models(connection)
        self.assertEqual(self.metadata.requests,[])
        self.app.client.permissions['buyer-a'].remove('youtube:agent.run')
        body={'connection_id':connection,'tab_id':self.tab,'search':'','cursor':None}
        self.post('models',body,status=403)
        self.app.client.unavailable=True
        self.post('models',body,status=503)
        self.post('disconnect',{'connection_id':connection,'tab_id':self.tab},key=False)
        self.post('disconnect',{'connection_id':connection,'tab_id':self.tab},key=False)
        self.assertEqual(self.metadata.requests,[])
        self.app.client.unavailable=False
        self.app.client.permissions['buyer-a'].add('youtube:agent.run')
        self.post('models',body,status=409)

    def test_expiry_is_fixed_and_revocation_during_capture_cannot_commit(self):
        connection=self.connect()['connection_id']
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE provider_connections SET expires_at=0 WHERE id=?',(connection,))
        self.metadata.requests.clear()
        self.post('models',{'connection_id':connection,'tab_id':self.tab,'search':'','cursor':None},status=409)
        self.assertEqual(self.metadata.requests,[])
        validate=self.metadata.validate_key
        def revoke(credential):
            validate(credential);self.app.client.permissions['buyer-a'].discard('youtube:agent.run')
        with patch.object(self.metadata,'validate_key',side_effect=revoke):
            self.post('connect',{'operation_id':uuid4().hex,'tab_id':self.tab},status=403)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_connections').fetchone()[0],1)

    def test_metadata_probes_run_without_a_sqlite_writer_lock(self):
        validate=self.metadata.validate_key
        def probe(credential):
            with closing(sqlite3.connect(self.path,timeout=0)) as db:
                db.execute('BEGIN IMMEDIATE');db.rollback()
            return validate(credential)
        with patch.object(self.metadata,'validate_key',side_effect=probe):
            connection=self.connect()['connection_id']
            catalogue=self.models(connection)
            self.post('select',self.selection(connection,catalogue['catalogue_revision']))

    def test_duplicate_headers_fields_and_public_or_invalid_origin_never_probe(self):
        body={'operation_id':uuid4().hex,'tab_id':self.tab}
        self.post('connect',body,key=False,status=409)
        self.post('connect',{**body,'actor_id':'other'},status=400)
        raw='{"operation_id":"'+body['operation_id']+'","tab_id":"'+self.tab+'","tab_id":"'+self.tab+'"}'
        r=self.buyer.post('/api/openrouter/connect',content=raw,headers={'Content-Type':'application/json','X-OpenRouter-Key':self.key})
        self.assertEqual(r.status_code,400)
        r=self.buyer.post('/api/openrouter/connect',json=body,headers=[('X-OpenRouter-Key',self.key),('X-OpenRouter-Key',self.key)])
        self.assertEqual(r.status_code,400)
        r=self.buyer.post('/api/openrouter/connect',json=body,headers={'Origin':self.app.viewer_origin,'X-OpenRouter-Key':self.key})
        self.assertEqual(r.status_code,403)
        with TestClient(self.app.viewer,base_url=self.app.viewer_origin) as public:
            self.assertEqual(public.post('/api/openrouter/connect',json=body,headers={'Origin':self.app.viewer_origin}).status_code,404)
        self.assertEqual(self.metadata.requests,[])

    def test_early_provider_denials_retain_v1_error_and_no_store(self):
        body={'operation_id':uuid4().hex,'tab_id':self.tab}
        for headers in ({'Host':'attacker.test'},{'Sec-Fetch-Site':'cross-site'},{'X-CSRF-Token':''}):
            with self.subTest(headers=headers):
                r=self.buyer.post('/api/openrouter/connect',json=body,headers=headers)
                self.assertEqual(r.status_code,403)
                self.assertEqual(set(r.json()),{'error','code','retryable'})
                self.assertEqual(r.headers['cache-control'],'no-store')
        r=self.buyer.post('/api/openrouter/connect',content='x'*800001,headers={'Content-Type':'application/json'})
        self.assertEqual(r.status_code,400)
        self.assertEqual(r.json()['code'],'invalid_request')
        self.assertEqual(r.headers['cache-control'],'no-store')
        self.assertEqual(self.metadata.requests,[])

    def test_cursor_is_connection_search_and_expiry_bound_and_mixed_prices_display_safely(self):
        base=self.metadata.rows[0]
        self.metadata.rows=[{**base,'id':'fixture/m'+str(i),'name':'Authored '+str(i)} for i in range(24)]
        self.metadata.rows.append({**base,'id':'fixture/conditional','pricing':{'prompt':'0.000001','completion':'0.000002','overrides':[{'prompt':'0.1'}]}})
        self.metadata.rows.append({**base,'id':'fixture/cached','pricing':{'prompt':'0','completion':'0','input_cache_write':'0.1'}})
        connection=self.connect()['connection_id'];first=self.models(connection)
        self.assertEqual(len(first['models']),20)
        self.assertTrue(first['next_cursor'])
        blocked=[r for r in first['models'] if r['state']=='blocked']
        self.assertTrue(blocked)
        second=self.post('models',{'connection_id':connection,'tab_id':self.tab,'search':'','cursor':first['next_cursor']})
        self.assertEqual(len(second['models']),6)
        another=self.connect()['connection_id']
        self.models(another)
        self.post('models',{'connection_id':another,'tab_id':self.tab,'search':'','cursor':first['next_cursor']},status=409)
        self.post('models',{'connection_id':connection,'tab_id':self.tab,'search':'different','cursor':first['next_cursor']},status=409)

    def test_new_web_inference_disabled_even_with_environment_key(self):
        from campaign_agent.adapters.openrouter_reviews import ReviewInferenceError
        direct=self.app.runtime(self.buyer.cookies.get(self.app.cookie),'campaign-a',{})[0]
        for adapter in (direct.planner.remote,direct.openrouter,direct.openrouter_drafts):
            adapter.models=('example/model:free',)
        with patch.dict('os.environ',{'OPENROUTER_API_KEY':'sentinel-developer-key'}):
            for adapter in (direct.planner.remote,direct.openrouter,direct.openrouter_drafts):
                adapter.transport=Mock()
                with self.assertRaises(ReviewInferenceError):
                    adapter.require_available(adapter.settings('example/model:free'))
                adapter.transport.assert_not_called()
        self.assertEqual(len(direct.planner.options()['models']),2)

    def test_selection_commit_race_rejects_different_freshly_validated_profile(self):
        connection=self.connect()['connection_id'];catalogue=self.models(connection)
        data=self.selection(connection,catalogue['catalogue_revision'])
        original=self.service.profiles
        revised=(replace(original[0],version='authored-free-v2'),)
        self.service.profiles=revised
        endpoints=self.metadata.endpoints;entered=[False]
        def interleave(credential,model):
            if not entered[0]:
                entered[0]=True;self.service.profiles=original
                self.post('select',data)
                self.service.profiles=revised
            return endpoints(credential,model)
        with patch.object(self.metadata,'endpoints',side_effect=interleave):
            self.post('select',data,status=409)
        with closing(sqlite3.connect(self.path)) as db:
            snapshot=json.loads(db.execute('SELECT snapshot FROM provider_selections').fetchone()[0])
        self.assertEqual(snapshot['charging_profile'],'authored-free-v1')

    def test_escaped_key_echo_and_malformed_catalogue_fail_without_credential_projection(self):
        self.key='fixture-quoted-"-backslash-\\-not-real-secret'
        self.metadata.keys=(self.key,)
        connection=self.connect()['connection_id']
        self.metadata.rows[0]['name']='Provider echoed '+self.key
        self.post('models',{'connection_id':connection,'tab_id':self.tab,'search':'','cursor':None},status=503)
        self.metadata.rows[0]['name']='Authored model'
        self.metadata.rows[0]['architecture']=[]
        self.post('models',{'connection_id':connection,'tab_id':self.tab,'search':'','cursor':None},status=503)


    def test_saved_selection_replays_after_cache_eviction_and_service_reopen(self):
        from campaign_agent.bootstrap.runtime import create_provider_sessions as ProviderSessions
        connection=self.connect()['connection_id'];catalogue=self.models(connection)
        data=self.selection(connection,catalogue['catalogue_revision'])
        selected=self.post('select',data)
        self.service.cache.invalidate(connection)
        self.metadata.requests.clear()
        self.assertEqual(self.post('select',data),selected)
        self.assertEqual(self.metadata.requests,['key','models','endpoints'])
        reopened=ProviderSessions(self.path,metadata=self.metadata,profiles=self.service.profiles)
        self.app.provider_sessions=self.service=reopened
        self.assertEqual(self.post('select',data),selected)
        # A refreshed catalogue may expire; the admitted original operation remains recoverable.
        self.models(connection)
        self.service.cache.entries[connection]['expires_at']=0
        self.assertEqual(self.post('select',data),selected)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_selections').fetchone()[0],1)

    def test_cacheless_selection_replay_keeps_key_access_and_profile_drift_fences(self):
        connection=self.connect()['connection_id'];catalogue=self.models(connection)
        data=self.selection(connection,catalogue['catalogue_revision'])
        self.post('select',data);self.service.cache.invalidate(connection)
        self.metadata.requests.clear()
        original_key=self.key;self.key=self.metadata.keys[1]
        self.post('select',data,status=403);self.key=original_key
        self.post('select',{**data,'max_run_cost_usd':'0.25'},status=409)
        self.app.client.permissions['buyer-a'].remove('youtube:agent.run')
        self.post('select',data,status=403)
        self.app.client.permissions['buyer-a'].add('youtube:agent.run')
        self.assertEqual(self.metadata.requests,[])
        original=self.service.profiles
        self.service.profiles=(replace(original[0],version='changed-authorized-profile'),)
        self.assertEqual(self.post('select',data,status=409)['code'],'selection_stale')
        self.service.profiles=original
        self.metadata.endpoint['pricing']={'prompt':'0.1','completion':'0.1','request':'0'}
        self.assertEqual(self.post('select',data,status=409)['code'],'route_unqualified')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_selections').fetchone()[0],1)

    def test_blocked_model_modalities_cannot_admit_a_qualified_selection_or_replay(self):
        connection=self.connect()['connection_id']
        for architecture in ({'input_modalities':['image'],'output_modalities':['text']},
                             {'input_modalities':['text'],'output_modalities':['audio']}):
            with self.subTest(architecture=architecture):
                self.metadata.rows[0]['architecture']=architecture
                self.service.cache.invalidate(connection)
                catalogue=self.models(connection)
                self.assertEqual(catalogue['models'][0]['state'],'blocked')
                data=self.selection(connection,catalogue['catalogue_revision'])
                self.assertEqual(self.post('select',data,status=409)['code'],'route_unqualified')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_selections').fetchone()[0],0)
        self.metadata.rows[0]['architecture']={'input_modalities':['text'],'output_modalities':['text']}
        self.service.cache.invalidate(connection);catalogue=self.models(connection)
        data=self.selection(connection,catalogue['catalogue_revision']);self.post('select',data)
        self.service.cache.invalidate(connection)
        self.metadata.rows[0]['architecture']={'input_modalities':['image'],'output_modalities':['text']}
        self.assertEqual(self.post('select',data,status=409)['code'],'route_unqualified')

    def test_model_capabilities_are_checked_for_the_selected_task_profile(self):
        connection=self.connect()['connection_id']
        self.metadata.rows[0]['supported_parameters']=['response_format','structured_outputs']
        catalogue=self.models(connection)
        structured=self.selection(connection,catalogue['catalogue_revision']);structured['profile']='structured_review'
        self.assertEqual(self.post('select',structured)['profile'],'structured_review')
        self.assertEqual(self.post('select',self.selection(connection,catalogue['catalogue_revision']),status=409)['code'],'route_unqualified')
        self.metadata.rows[0]['supported_parameters']=['tools','tool_choice']
        self.service.cache.invalidate(connection);catalogue=self.models(connection)
        self.assertEqual(self.post('select',self.selection(connection,catalogue['catalogue_revision']))['profile'],'planner')
        structured=self.selection(connection,catalogue['catalogue_revision']);structured['profile']='structured_review'
        self.assertEqual(self.post('select',structured,status=409)['code'],'route_unqualified')

    def test_catalogue_reads_share_one_connection_guard_across_select_and_models(self):
        for first,contender in (('select','select'),('select','models'),('models','select')):
            with self.subTest(first=first,contender=contender):
                connection=self.connect()['connection_id'];catalogue=self.models(connection)
                data=self.selection(connection,catalogue['catalogue_revision']);saved=self.post('select',data)
                independent=self.connect()['connection_id']
                body={'connection_id':connection,'tab_id':self.tab,'search':'','cursor':None}
                if first=='models':self.service.cache.invalidate(connection)
                entered=Event();release=Event();lock=Lock();calls=[0]
                original=self.metadata.models
                def held(credential):
                    with lock:
                        calls[0]+=1;position=calls[0]
                    if position==1:
                        entered.set()
                        if not release.wait(3):raise AssertionError('Catalogue read was not released')
                    return original(credential)
                with patch.object(self.metadata,'models',side_effect=held),ThreadPoolExecutor(max_workers=1) as pool:
                    pending=pool.submit(self.post,first,data if first=='select' else body)
                    try:
                        self.assertTrue(entered.wait(3))
                        if contender=='models':self.service.cache.invalidate(connection)
                        rejected=self.post(contender,data if contender=='select' else body,status=429)
                        self.assertEqual(rejected['code'],'admission_busy')
                        self.assertEqual(calls[0],1,'Contender must not start a full catalogue read')
                        # Another connection remains usable while this foreground request waits.
                        self.models(independent)
                        self.assertEqual(calls[0],2)
                    finally:release.set()
                    completed=pending.result(timeout=3)
                    if first=='select':self.assertEqual(completed,saved)
                self.assertEqual(self.post('select',data),saved)

    def test_catalogue_guard_releases_on_key_and_catalogue_errors(self):
        connection=self.connect()['connection_id'];catalogue=self.models(connection)
        data=self.selection(connection,catalogue['catalogue_revision']);saved=self.post('select',data)
        for action in ('select','models'):
            for method in ('validate_key','models'):
                with self.subTest(action=action,method=method):
                    if action=='models':self.service.cache.invalidate(connection)
                    body=data if action=='select' else {'connection_id':connection,'tab_id':self.tab,'search':'','cursor':None}
                    with patch.object(self.metadata,method,side_effect=ProviderError('catalogue_unavailable')):
                        self.assertEqual(self.post(action,body,status=503)['code'],'catalogue_unavailable')
                    if action=='models':self.models(connection)
                    self.assertEqual(self.post('select',data),saved)

    def test_detected_model_drift_refreshes_immediately_and_requires_new_operation(self):
        for position in range(21):
            self.metadata.rows.append({**deepcopy(self.metadata.rows[0]),'id':f'fixture/z-extra-{position:02}'})
        connection=self.connect()['connection_id'];catalogue=self.models(connection)
        self.assertIsNotNone(catalogue['next_cursor'])
        data=self.selection(connection,catalogue['catalogue_revision'])
        self.metadata.rows[0]['name']='Current authored display name'
        self.assertEqual(self.post('select',data,status=409)['code'],'selection_stale')
        refreshed=self.models(connection)
        self.assertNotEqual(refreshed['catalogue_revision'],catalogue['catalogue_revision'])
        self.assertEqual(refreshed['models'][0]['name'],'Current authored display name')
        self.assertEqual(self.post('models',{'connection_id':connection,'tab_id':self.tab,'search':'',
            'cursor':catalogue['next_cursor']},status=409)['code'],'selection_stale')
        self.assertEqual(self.post('select',data,status=409)['code'],'selection_stale')
        selected=self.post('select',self.selection(connection,refreshed['catalogue_revision']))
        self.assertEqual(selected['catalogue_revision'],refreshed['catalogue_revision'])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_selections').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_selections WHERE operation_id=?',(data['operation_id'],)).fetchone()[0],0)

    def test_incompatible_or_missing_current_model_does_not_leave_eligible_cache(self):
        original=deepcopy(self.metadata.rows)
        for change in ('modalities','pricing','missing'):
            with self.subTest(change=change):
                self.metadata.rows=deepcopy(original)
                connection=self.connect()['connection_id'];catalogue=self.models(connection)
                data=self.selection(connection,catalogue['catalogue_revision'])
                if change=='modalities':self.metadata.rows[0]['architecture']['output_modalities']=['audio']
                elif change=='pricing':self.metadata.rows[0]['pricing']['unknown_unit']='0.1'
                else:self.metadata.rows=[]
                self.assertEqual(self.post('select',data,status=409)['code'],'route_unqualified')
                refreshed=self.models(connection)
                self.assertNotEqual(refreshed['catalogue_revision'],catalogue['catalogue_revision'])
                if change=='missing':self.assertEqual(refreshed['models'],[])
                else:self.assertEqual(refreshed['models'][0]['state'],'blocked')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_selections').fetchone()[0],0)

    def test_endpoint_and_profile_drift_refresh_immediately_without_rewriting_receipt(self):
        connection=self.connect()['connection_id'];catalogue=self.models(connection)
        data=self.selection(connection,catalogue['catalogue_revision']);saved=self.post('select',data)
        original_profiles=self.service.profiles;original_endpoint=deepcopy(self.metadata.endpoint)
        for change in ('profile','endpoint'):
            with self.subTest(change=change):
                catalogue=self.models(connection)
                if change=='profile':self.service.profiles=(replace(original_profiles[0],version='authored-free-v2'),)
                else:self.metadata.endpoint['context_length']=16000
                try:
                    self.post('select',data,status=409)
                    self.metadata.requests.clear()
                    refreshed=self.models(connection)
                    self.assertIn('models',self.metadata.requests)
                    self.assertNotEqual(refreshed['catalogue_revision'],catalogue['catalogue_revision'])
                    with closing(sqlite3.connect(self.path)) as db:
                        rows=db.execute('SELECT snapshot FROM provider_selections').fetchall()
                    self.assertEqual([json.loads(row[0]) for row in rows],[saved])
                finally:
                    self.service.profiles=original_profiles;self.metadata.endpoint=deepcopy(original_endpoint)
        self.assertEqual(self.post('select',data),saved)


class OpenRouterLocalTests(unittest.TestCase):
    def test_actual_local_handler_allowed_path_denials_and_no_new_web_inference(self):
        from contextlib import ExitStack,redirect_stdout
        from email.message import Message
        from scripts import placement_review
        from campaign_agent.bootstrap.runtime import create_runtime as AgentRuntime
        with TemporaryDirectory() as d,ExitStack() as stack:
            path=Path(d)/'local.sqlite3';servers=[];runtimes=[];metadata=AuthoredProviderMetadata()
            def server(address,handler):
                s=Mock(server_port=address[1]);s.__enter__=Mock(return_value=s);s.__exit__=Mock(return_value=False)
                s.handler=handler;servers.append(s);return s
            def runtime(*args,**kwargs):
                r=AgentRuntime(*args,**kwargs);runtimes.append(r);return r
            stack.enter_context(patch.object(placement_review,'ThreadingHTTPServer',side_effect=server))
            stack.enter_context(patch.object(placement_review.Thread,'start'))
            stack.enter_context(patch.object(placement_review.Thread,'join'))
            stack.enter_context(patch.object(placement_review.secrets,'token_urlsafe',return_value='authored-local-operator'))
            stack.enter_context(redirect_stdout(io.StringIO()))
            placement_review.serve(18981,False,draft_path=path,viewer_port=18982,provider_metadata=metadata,runtime_factory=runtime,
                provider_profiles=metadata.profiles,main_models=('example/model:free',),openrouter_review_models=('example/model:free',))
            handler=servers[0].handler.__new__(servers[0].handler);handler.server=servers[0];handler.send=Mock()
            tab=uuid4().hex
            def call(action,data,*,key=True,host='127.0.0.1:18981',operator='authored-local-operator',origin='http://127.0.0.1:18981',duplicate=False):
                body=json.dumps(data).encode();headers=Message()
                for k,v in {'Host':host,'X-Local-Operator':operator,'Origin':origin,'Content-Type':'application/json','Content-Length':str(len(body))}.items():headers[k]=v
                if key:headers['X-OpenRouter-Key']=metadata.keys[0]
                if duplicate:headers['X-OpenRouter-Key']=metadata.keys[0]
                handler.path='/api/openrouter/'+action;handler.headers=headers;handler.rfile=io.BytesIO(body)
                handler.do_POST();return handler.send.call_args.args
            body={'operation_id':uuid4().hex,'tab_id':tab}
            code,connected=call('connect',body);self.assertEqual(code,200)
            connection=connected['connection_id']
            code,catalogue=call('models',{'connection_id':connection,'tab_id':tab,'search':'','cursor':None});self.assertEqual(code,200)
            code,selected=call('select',dict(operation_id=uuid4().hex,connection_id=connection,tab_id=tab,
                model_id='fixture/tool-model',catalogue_revision=catalogue['catalogue_revision'],profile='planner',max_run_cost_usd='0'))
            self.assertEqual(code,200);self.assertEqual(selected['connection_id'],connection)
            metadata.requests.clear()
            for kwargs in ({'operator':'wrong'},{'origin':'http://attacker.test'},{'host':'attacker.test'},{'duplicate':True}):
                code,result=call('connect',body,**kwargs);self.assertIn(code,(400,403));self.assertIn('code',result)
            self.assertEqual(metadata.requests,[])
            code,result=call('disconnect',{'connection_id':connection,'tab_id':tab},key=False);self.assertEqual(code,200)
            handler.server=servers[1]
            code,_=call('connect',body,host='127.0.0.1:18982');self.assertEqual(code,404)
            self.assertEqual(len(runtimes[0].planner.options()['models']),2)
            with patch.dict('os.environ',{'OPENROUTER_API_KEY':'sentinel-developer-key'}):
                for adapter in (runtimes[0].openrouter,runtimes[0].openrouter_drafts,runtimes[0].planner.remote):
                    adapter.transport=Mock()
                    from campaign_agent.adapters.openrouter_reviews import ReviewInferenceError
                    with self.assertRaises(ReviewInferenceError):adapter.require_available(adapter.settings('example/model:free'))
                    adapter.transport.assert_not_called()
