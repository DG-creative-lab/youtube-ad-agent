"""Foreground HTTP integration with authored provider responses, never external I/O."""
from contextlib import closing
from copy import deepcopy
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from starlette.testclient import TestClient
from campaign_agent.adapters.fixture_access import offline_fixture


class ForegroundHttpTests(unittest.TestCase):
    def setUp(self):
        self.path=Path(self.enterContext(TemporaryDirectory()))/'product.sqlite'
        self.app=offline_fixture(self.path);self.meta=self.app.provider_sessions.metadata
        self.key=self.meta.keys[0];self.tab=uuid4().hex;self.calls=[]
        self.reply={'id':'gen-authored','model':'fixture/tool-model','usage':{'cost':0,'prompt_tokens':100,'completion_tokens':20},'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'id':'call-authored','type':'function','function':{'name':'respond','arguments':'{"topic":"campaign_summary"}'}}]}}]}
        self.app.provider_completion_transport=self.transport
        self.client=self.enterContext(TestClient(self.app.staff,base_url=self.app.staff_origin))
        self.client.post('/fixture',json={'profile':'buyer-a'},headers={'Origin':self.app.staff_origin})
        self.client.headers.update({'Origin':self.app.staff_origin,'X-CSRF-Token':self.client.get('/api/session').headers['x-csrf-token']})
        config=self.client.get('/api/config').json();self.catalog=config['agentPlanner']['catalogs'][0]['id']
        self.selection=self.select()
        self.meta.requests.clear()

    def transport(self,request,*,timeout):
        with closing(sqlite3.connect(self.path,timeout=0)) as db:db.execute('BEGIN IMMEDIATE');db.rollback()
        self.calls.append(request)
        return io.BytesIO(json.dumps(self.reply).encode())

    def post(self,path,data,key=True):
        return self.client.post(path,json=data,headers={'X-OpenRouter-Key':self.key} if key else {})

    def select(self,profile='planner',budget='0'):
        connection=self.post('/api/openrouter/connect',{'operation_id':uuid4().hex,'tab_id':self.tab}).json()['connection_id']
        catalogue=self.post('/api/openrouter/models',{'connection_id':connection,'tab_id':self.tab,'search':'','cursor':None}).json()
        response=self.post('/api/openrouter/select',{'operation_id':uuid4().hex,'connection_id':connection,'tab_id':self.tab,'model_id':'fixture/tool-model','catalogue_revision':catalogue['catalogue_revision'],'profile':profile,'max_run_cost_usd':budget})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def start(self,**extra):
        run=uuid4().hex
        data=dict(request='Summarise campaign',model='fixture/tool-model',session_id=uuid4().hex,run_id=run,catalog_id=self.catalog,provider_selection_id=self.selection['selection_id'],**extra)
        response=self.post('/api/agent/placements',data)
        self.assertEqual(response.status_code,200,response.text)
        return run

    def ledger(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT state,reserved_nanos,actual_cost,in_flight,receipt FROM inference_ledger ORDER BY position').fetchall()

    def dynamic_routes(self):
        from campaign_agent.application.catalogue_policy import select_live_endpoint
        self.app.provider_sessions.route_selector = lambda credential,model,task,now,previous=None: select_live_endpoint(
            model,task,self.meta.endpoints(credential,model),now,previous=previous)

    def test_live_route_accepts_non_allowlisted_model_cache_rates_and_replays_pinned_selection(self):
        self.dynamic_routes()
        self.meta.rows[0]['architecture']['input_modalities']=['text','image']
        rates={'prompt':'0','completion':'0','input_cache_read':'0','discount':0,'web_search':'0.01'}
        self.meta.rows[0]['pricing']=rates
        self.meta.endpoint['pricing']=rates
        self.meta.endpoint['supported_parameters'].remove('parallel_tool_calls')
        self.selection=self.select()
        saved=deepcopy(self.selection)
        with closing(sqlite3.connect(self.path)) as db:
            operation=db.execute('SELECT operation_id FROM provider_selections WHERE id=?',(saved['selection_id'],)).fetchone()[0]
        retry=self.post('/api/openrouter/select',dict(operation_id=operation,connection_id=saved['connection_id'],tab_id=self.tab,
            model_id=saved['model'],catalogue_revision=saved['catalogue_revision'],profile='planner',max_run_cost_usd='0'))
        self.assertEqual(retry.status_code,200,retry.text)
        self.assertEqual(retry.json(),saved)
        run=self.start()
        # Live replies use the LLM's tool result, not the authored summary.
        self.reply['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"topic":"campaign_summary","message":"Your campaign summary."}'
        result=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(len(self.calls),1)
        wire=json.loads(self.calls[0].data)
        self.assertNotIn('parallel_tool_calls',wire)
        self.assertEqual(wire['provider']['only'],['fixture/qualified'])
        self.assertEqual(wire['provider']['allow_fallbacks'],False)
        self.assertEqual(self.ledger()[0][:4],('settled',0,'0',0))

    def test_live_route_selection_explains_endpoint_failure_without_a_completion(self):
        self.dynamic_routes()
        connection=self.selection['connection_id']
        catalogue=self.post('/api/openrouter/models',dict(connection_id=connection,tab_id=self.tab,search='',cursor=None)).json()
        self.assertTrue(catalogue['route_check_available'])
        original=deepcopy(self.meta.endpoint)
        cases=[({'supports_tool_choice':{'required':False}},'route_required_choice_unsupported'),
            ({'supported_parameters':['tools','tool_choice']},'route_output_cap_unsupported'),
            ({'context_length':None},'route_context_unsupported'),
            ({'pricing':{'prompt':'0','completion':'0','unknown_fee':'1'}},'route_unknown_pricing')]
        for changed,code in cases:
            with self.subTest(code=code):
                self.meta.endpoint={**original,**changed}
                response=self.post('/api/openrouter/select',dict(operation_id=uuid4().hex,connection_id=connection,tab_id=self.tab,
                    model_id='fixture/tool-model',catalogue_revision=catalogue['catalogue_revision'],profile='planner',max_run_cost_usd='0'))
                self.assertEqual(response.status_code,409,response.text)
                self.assertEqual(response.json()['code'],code)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.ledger(),[])

    def test_live_pinned_endpoint_drift_stops_before_completion(self):
        self.dynamic_routes();self.selection=self.select();run=self.start()
        self.meta.endpoint['pricing']={'prompt':'0.000001','completion':'0'}
        result=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(result.status_code,409,result.text)
        self.assertEqual(result.json()['code'],'selection_stale')
        self.assertEqual(self.calls,[]);self.assertEqual(self.ledger(),[])

    def test_cache_write_cost_is_reserved_and_zero_budget_cannot_select_it(self):
        self.dynamic_routes()
        rates={'prompt':'0','completion':'0','input_cache_write':'0.000001','input_cache_read':'0.0000001'}
        self.meta.endpoint['pricing']=rates;self.meta.rows[0]['pricing']=rates
        self.selection=self.select(budget='0.25')
        self.assertEqual(self.selection['prices']['input_cache_write'],'0.000001')
        run=self.start()
        self.reply['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"topic":"campaign_summary","message":"Summary."}'
        result=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.ledger()[0][1],31488000)
        connection=self.selection['connection_id']
        response=self.post('/api/openrouter/select',dict(operation_id=uuid4().hex,connection_id=connection,tab_id=self.tab,
            model_id='fixture/tool-model',catalogue_revision=self.selection['catalogue_revision'],profile='planner',max_run_cost_usd='0'))
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(response.json()['code'],'budget_exhausted')
        self.assertEqual(len(self.calls),1)

    def test_live_parallel_proposal_evaluates_one_action_and_replans_without_executing_extra_write(self):
        self.dynamic_routes();self.selection=self.select()
        self.reply['choices'][0]['message']['tool_calls']=[
            {'id':'read-first','type':'function','function':{'name':'read_campaign','arguments':'{}'}},
            {'id':'unexecuted-write','type':'function','function':{'name':'save_placement_draft','arguments':'{"ids":["SAMPLE00001"]}'}}]
        run=self.start()
        first=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual([s['tool'] for s in first.json()['steps']],['read_campaign'])
        self.assertEqual(first.json()['diagnostics']['calls'][0]['additional_tool_calls'],1)
        self.assertEqual(first.json()['diagnostics']['status'],'running')
        self.reply['choices'][0]['message']['tool_calls']=[
            {'id':'answer-next','type':'function','function':{'name':'respond',
             'arguments':'{"topic":"campaign_summary","message":"Here are recommendations for review."}'}}]
        second=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(second.status_code,200,second.text)
        self.assertEqual(second.json()['status'],'answered')
        self.assertEqual([s['tool'] for s in second.json()['steps']],['read_campaign','respond'])
        # The follow-up model sees only the evaluated call/result pair.
        wire=json.loads(self.calls[1].data)
        assistant=[m for m in wire['messages'] if m['role']=='assistant']
        self.assertEqual(len(assistant[0]['tool_calls']),1)
        self.assertEqual(assistant[0]['tool_calls'][0]['id'],'read-first')
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.post('/api/agent/run',{'run_id':run},key=False).json()['status'],'answered')
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.client.get('/api/campaign').json()['revision'],1)

    def test_provider_failure_is_explained_and_trace_survives_keyless_read_without_resend(self):
        self.reply={'error':{'code':404,'message':'No endpoints found that support your data policy.'}}
        run=self.start()
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,502,response.text)
        self.assertEqual(response.json()['code'],'provider_privacy_unavailable')
        saved=self.client.get('/api/agent/run',params={'id':run}).json()
        trace=saved['diagnostics']
        self.assertEqual(trace['status'],'failed')
        self.assertEqual(trace['calls'][0]['code'],'provider_privacy_unavailable')
        self.assertEqual(trace['calls'][0]['provider_error_code'],404)
        self.assertNotIn(self.key,json.dumps(trace))
        self.assertNotIn('messages',json.dumps(trace))
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.post('/api/agent/run',{'run_id':run},key=False).json()['code'],'provider_privacy_unavailable')
        self.assertEqual(len(self.calls),1)
        # The same-shaped foreign principal cannot read this trace.
        self.client.post('/fixture',json={'profile':'buyer-b'})
        self.assertEqual(self.client.get('/api/agent/run',params={'id':run}).status_code,403)

    def test_rate_limit_response_has_specific_status_and_excludes_provider_echoes(self):
        self.reply={'error':{'code':429,'message':'Rate limit exceeded '+self.key,'metadata':{'raw':self.key}}}
        run=self.start()
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,429,response.text)
        self.assertEqual(response.json()['code'],'provider_rate_limited')
        trace=self.client.get('/api/agent/run',params={'id':run}).json()['diagnostics']
        self.assertEqual(trace['calls'][0]['provider_error_code'],429)
        self.assertEqual(trace['calls'][0]['http_status'],200)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertNotIn(self.key,'\n'.join(db.iterdump()))
        self.assertEqual(len(self.calls),1)

    def test_truncated_model_response_is_distinct_from_provider_error_and_never_repeated(self):
        self.reply['choices'][0]['finish_reason']='length'
        self.reply['choices'][0]['message']={'content':'Incomplete reply, not a valid action'}
        self.reply['usage']['completion_tokens']=512
        run=self.start()
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,502,response.text)
        self.assertEqual(response.json()['code'],'model_output_limit')
        trace=self.client.get('/api/agent/run',params={'id':run}).json()['diagnostics']
        self.assertEqual(trace['status'],'failed')
        self.assertEqual(trace['calls'][0]['finish_reason'],'length')
        self.assertEqual(trace['calls'][0]['output_tokens'],512)
        self.assertEqual(trace['calls'][0]['cost_usd'],'0')
        self.assertEqual(self.post('/api/agent/run',{'run_id':run},key=False).json()['code'],'model_output_limit')
        self.assertEqual(len(self.calls),1)

    def test_planner_receipt_accounting_and_no_internal_or_secret_prompt(self):
        run=self.start();self.assertEqual(self.calls,[])
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['status'],'answered')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.ledger()[0][:4],('settled',0,'0',0))
        body=json.loads(self.calls[0].data)
        self.assertEqual(body['provider']['only'],['fixture/qualified'])
        self.assertEqual(body['max_completion_tokens'],512)
        for word in (self.key,'selection_id','connection_id','max_run_cost_usd','charging_profile','key_verifier'):
            self.assertNotIn(word,self.calls[0].data.decode())
        self.assertEqual(self.calls[0].get_header('Authorization'),'Bearer '+self.key)
        self.assertEqual(self.post('/api/agent/run',{'run_id':run},key=False).status_code,200)
        self.assertEqual(len(self.calls),1)
        with closing(sqlite3.connect(self.path)) as db:self.assertNotIn(self.key,'\n'.join(db.iterdump()))

    def test_missing_key_waits_without_reservation_and_original_key_resumes(self):
        run=self.start()
        response=self.post('/api/agent/run',{'run_id':run},key=False)
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(response.json()['code'],'waiting_for_credentials')
        self.assertEqual(self.ledger(),[]);self.assertEqual(self.calls,[])
        self.assertEqual(self.post('/api/agent/run',{'run_id':run}).status_code,200)
        self.assertEqual(len(self.calls),1)

    def test_timeout_is_unknown_and_never_redispatched_even_after_reopen(self):
        run=self.start()
        def timeout(*args,**kwargs):self.calls.append('attempt');raise TimeoutError()
        self.app.provider_completion_transport=timeout
        self.assertEqual(self.post('/api/agent/run',{'run_id':run}).status_code,409)
        self.assertEqual(self.ledger()[0][:4],('unknown',0,None,1))
        self.app.provider_completion_transport=self.transport
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(response.json()['code'],'inference_outcome_unknown')
        self.assertEqual(len(self.calls),1)

    def test_invalid_semantics_still_save_accounting_and_echo_content_is_not_persisted(self):
        self.reply['choices'][0]['message']['tool_calls'][0]['function']['arguments']='not-json'
        run=self.start();self.assertNotEqual(self.post('/api/agent/run',{'run_id':run}).status_code,200)
        self.assertEqual(self.ledger()[0][:4],('settled',0,'0',0))
        self.reply['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps({'secret':self.key})
        run=self.start();self.assertEqual(self.post('/api/agent/run',{'run_id':run}).status_code,409)
        self.assertEqual(self.ledger()[1][:4],('settled',0,'0',0))
        with closing(sqlite3.connect(self.path)) as db:self.assertNotIn(self.key,'\n'.join(db.iterdump()))

    def test_local_key_and_mode_substitution_make_zero_provider_requests(self):
        run=self.start();self.meta.requests.clear();self.key=self.meta.keys[1]
        response=self.post('/api/agent/run',{'run_id':run});self.assertEqual(response.status_code,403,response.text)
        self.assertEqual(self.meta.requests,[]);self.assertEqual(self.calls,[]);self.assertEqual(self.ledger(),[])
        data={'test_id':uuid4().hex,'mode':'offline','provider_selection_id':self.selection['selection_id']}
        self.assertEqual(self.post('/api/agent/instruction-review',data).status_code,400)

    def setup_performance(self):
        from campaign_agent.handoff import package_fingerprint
        # Product setup through existing native commands with the authorized
        # buyer and separate reviewer actors; no synthetic approval bypass.
        self.app.client.permissions['buyer-a'].add('youtube:campaign.export')
        token=self.client.cookies.get(self.app.cookie)
        buyer=self.app.runtime(token,'campaign-a',{})[0]
        buyer.drafts.save({'campaign_id':'campaign-a','revision':1,'placements':[
            {'id':'SAMPLE00001','title':'Editing','creative':'video-editing','source':'synthetic'},
            {'id':'SAMPLE00002','title':'Audiobook','creative':'audiobook','source':'synthetic'}]})
        reviewer=self.enterContext(TestClient(self.app.staff,base_url=self.app.staff_origin))
        reviewer.post('/fixture',json={'profile':'reviewer-a'},headers={'Origin':self.app.staff_origin})
        reviewer.headers.update({'Origin':self.app.staff_origin,'X-CSRF-Token':reviewer.get('/api/session').headers['x-csrf-token']})
        fingerprint=buyer.drafts.review_package('campaign-a',2)['fingerprint']
        response=reviewer.post('/api/campaign/approve',json={'campaign_id':'campaign-a','revision':2,'fingerprint':fingerprint})
        self.assertEqual(response.status_code,200,response.text)
        package=response.json()['package'];creative=package['groups'][0]['creative']['ref'] if 'creative' in package['groups'][0] else buyer.drafts.examples[0].creative_ref
        for _ in range(3):buyer.performance.viewer.open_example(creative,content_fingerprint=package_fingerprint(package['groups'][0]['content']))
        review=buyer.performance.review('campaign-a',2,fingerprint,'balanced')
        buyer.performance.save_correction('campaign-a',2,fingerprint,review['id'],'keep_takes','Keep the approved audio.',uuid4().hex)
        review=buyer.performance.review('campaign-a',2,fingerprint,'balanced')
        return buyer,review,fingerprint,reviewer

    def structured_reply(self,content):
        self.reply['choices']=[{'finish_reason':'stop','message':{'content':json.dumps(content)}}]

    def advance(self,run,count=6):
        result=None
        for _ in range(count):
            response=self.post('/api/agent/run',{'run_id':run})
            self.assertEqual(response.status_code,200,response.text)
            result=response.json()
            if result['status']!='running':return result
        return result

    def test_all_three_structured_start_resume_routes_use_original_selection_and_shared_ledger(self):
        buyer,review,fingerprint,reviewer=self.setup_performance()
        selection=self.select('structured_review')
        self.structured_reply({'playback':'both_in_full','focus':'delivery','choice':'scene_fit'})
        args={'campaign_id':'campaign-a','revision':2,'fingerprint':fingerprint,'review_id':review['id'],
              'mode':'openrouter','operation_id':uuid4().hex,'provider_selection_id':selection['selection_id']}
        response=self.post('/api/agent/next-test',args);self.assertEqual(response.status_code,200,response.text)
        run=response.json()['run_id'];result=self.advance(run)
        self.assertEqual(result['status'],'ready_for_review');self.assertEqual(len(self.calls),1)
        self.assertEqual(self.ledger()[0][:4],('settled',0,'0',0))
        fingerprint=buyer.drafts.review_package('campaign-a',3)['fingerprint']
        self.assertEqual(reviewer.post('/api/campaign/approve',json={'campaign_id':'campaign-a','revision':3,'fingerprint':fingerprint}).status_code,200)
        test=buyer.instruction_tests.start('campaign-a',3,fingerprint)
        for arm in ('original','revised'):
            for _ in range(20):
                with patch('campaign_agent.instruction_tests.secrets.choice',return_value=arm):
                    buyer.instruction_tests.open(test['id'],uuid4().hex,source='participant')
        self.structured_reply({'reason_code':'revised_not_higher'})
        response=self.post('/api/agent/instruction-review',{'test_id':test['id'],'mode':'openrouter','operation_id':uuid4().hex,'provider_selection_id':selection['selection_id']})
        self.assertEqual(response.status_code,200,response.text)
        self.advance(response.json()['run_id']);self.assertEqual(len(self.calls),2)
        review=buyer.instruction_tests.read('campaign-a',3,fingerprint)['review']
        self.structured_reply({'playback':'take_order','focus':'pacing','choice':'moment_fit'})
        response=self.post('/api/agent/experiment-next-test',{'test_id':test['id'],'review_id':review['id'],'mode':'openrouter','operation_id':uuid4().hex,'provider_selection_id':selection['selection_id']})
        self.assertEqual(response.status_code,200,response.text)
        result=self.advance(response.json()['run_id'])
        self.assertEqual(result['status'],'ready_for_review');self.assertEqual(len(self.calls),3)
        self.assertEqual(len(self.ledger()),3)
        self.assertEqual(buyer.drafts.read()['revision'],4)
        self.assertIsNone(buyer.drafts.review_package('campaign-a',4)['approval'])

    def test_eight_turns_refresh_each_endpoint_and_cap_without_a_lifetime_quota(self):
        self.reply['choices'][0]['message']['tool_calls'][0]['function']={'name':'read_campaign','arguments':'{}'}
        run=self.start()
        for _ in range(8):
            response=self.post('/api/agent/run',{'run_id':run});self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['status'],'needs_input')
        self.assertEqual(len(self.calls),8)
        self.assertEqual(self.meta.requests.count('endpoints'),8)
        self.assertEqual(self.meta.requests.count('models'),8)
        self.assertEqual(len(self.ledger()),8)
        self.assertEqual(self.post('/api/agent/run',{'run_id':run},key=False).status_code,200)
        self.assertEqual(len(self.calls),8)

    def test_planner_saves_one_unapproved_draft_and_reads_its_own_new_revision(self):
        run=self.start(draft_permission='placements')
        for name,args in (('read_campaign',{}),('classify_catalog',{}),('save_placement_draft',{'contexts':['video-editing','audiobook']})):
            self.reply['choices'][0]['message']['tool_calls'][0]['function']={'name':name,'arguments':json.dumps(args)}
            response=self.post('/api/agent/run',{'run_id':run})
            self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['status'],'ready_for_review')
        self.assertEqual(self.client.get('/api/campaign').json()['revision'],2)
        self.assertIsNone(self.client.get('/api/campaign/package?revision=2').json()['approval'])
        self.assertEqual(len(self.calls),3)
        self.assertEqual(self.post('/api/agent/run',{'run_id':run},key=False).status_code,200)
        self.assertEqual(len(self.calls),3)

    def test_receipt_only_recovery_after_lost_semantic_write_needs_no_credential_or_metadata(self):
        from campaign_agent.agent.planner import PlacementAgent
        run=self.start()
        with patch.object(PlacementAgent,'_tool',side_effect=sqlite3.OperationalError('authored commit interruption')):
            self.assertNotEqual(self.post('/api/agent/run',{'run_id':run}).status_code,200)
        self.assertEqual(len(self.calls),1)
        self.meta.requests.clear()
        response=self.post('/api/agent/run',{'run_id':run},key=False)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['status'],'answered')
        self.assertEqual(self.meta.requests,[]);self.assertEqual(len(self.calls),1)

    def test_revocation_and_supersession_after_dispatch_keep_cost_but_block_domain_effect(self):
        for change in ('authority','supersession','connection'):
            with self.subTest(change=change):
                self.reply['choices'][0]['message']['tool_calls'][0]['function']={'name':'read_campaign','arguments':'{}'}
                run=self.start()
                def late(request,*,timeout):
                    receipt=self.transport(request,timeout=timeout)
                    if change=='authority':self.app.client.permissions['buyer-a'].discard('youtube:agent.run')
                    elif change=='supersession':
                        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE agent_runs SET status='superseded' WHERE id=?",(run,))
                    else:
                        self.client.post('/api/openrouter/disconnect',json={'connection_id':self.selection['connection_id'],'tab_id':self.tab})
                    return receipt
                self.app.provider_completion_transport=late
                response=self.post('/api/agent/run',{'run_id':run})
                self.assertIn(response.status_code,(200,403,409))
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM agent_steps WHERE run_id=?',(run,)).fetchone()[0],0)
                    self.assertEqual(db.execute('SELECT state,actual_cost FROM inference_ledger WHERE run_id=?',(run,)).fetchone(),('settled','0'))
                self.app.client.permissions['buyer-a'].add('youtube:agent.run')
                self.app.provider_completion_transport=self.transport
                if change=='connection':self.selection=self.select()

    def test_http_accounting_reconcile_proves_original_key_after_expiry_but_never_recovers_content(self):
        run=self.start();self.reply['usage'].pop('cost')
        self.assertEqual(self.post('/api/agent/run',{'run_id':run}).status_code,200)
        self.assertEqual(self.ledger()[0][:4],('received',0,None,0))
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE provider_connections SET expires_at=0')
        self.meta.generation=lambda credential,generation:{'id':generation,'total_cost':'0'}
        self.meta.requests.clear()
        body={'run_id':run,'inference_position':0}
        old=self.key;self.key=self.meta.keys[1]
        self.assertEqual(self.post('/api/openrouter/reconcile',body).status_code,403)
        self.assertEqual(self.meta.requests,[]);self.key=old
        response=self.post('/api/openrouter/reconcile',body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),{'state':'settled','reserved_cost_usd':'0','actual_cost_usd':'0'})
        self.assertNotIn('message',response.json());self.assertEqual(len(self.calls),1)

    def test_dispatch_marker_failure_releases_only_unsent_and_same_operation_can_resume(self):
        from campaign_agent.inference_ledger import InferenceLedger
        run=self.start()
        with patch.object(InferenceLedger,'dispatch',side_effect=sqlite3.OperationalError('before marker')):
            self.assertNotEqual(self.post('/api/agent/run',{'run_id':run}).status_code,200)
        self.assertEqual(self.ledger()[0][:4],('released_unsent',0,None,0));self.assertEqual(self.calls,[])
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(len(self.calls),1)

    def test_lost_receipt_write_and_lost_commit_ack_have_distinct_recovery_without_dispatch(self):
        from campaign_agent.inference_ledger import InferenceLedger
        run=self.start()
        with patch.object(InferenceLedger,'receive',side_effect=sqlite3.OperationalError('lost receipt')):
            self.assertNotEqual(self.post('/api/agent/run',{'run_id':run}).status_code,200)
        self.assertEqual(self.ledger()[0][0],'dispatching');self.assertEqual(len(self.calls),1)
        self.assertEqual(self.post('/api/agent/run',{'run_id':run}).status_code,409);self.assertEqual(len(self.calls),1)
        # A separate fixture actor is required while the first call is unresolved.
        with closing(sqlite3.connect(self.path)) as db,db:
            # Explicit authored terminal reconciliation for the fault fixture only;
            # application code never auto-expires this lost-call claim.
            db.execute('UPDATE inference_ledger SET in_flight=0 WHERE run_id=?',(run,))
        run=self.start();receive=InferenceLedger.receive
        def lost_ack(owner,db,*args):
            receive(owner,db,*args);db.commit();raise sqlite3.OperationalError('acknowledgement lost after commit')
        with patch.object(InferenceLedger,'receive',lost_ack):
            self.assertNotEqual(self.post('/api/agent/run',{'run_id':run}).status_code,200)
        self.assertEqual(self.ledger()[1][0],'settled')
        response=self.post('/api/agent/run',{'run_id':run},key=False)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(len(self.calls),2)

    def test_same_run_parallel_advance_cannot_dispatch_twice(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        run=self.start();entered=Event();release=Event()
        def blocked(request,*,timeout):
            entered.set();self.assertTrue(release.wait(10));return self.transport(request,timeout=timeout)
        self.app.provider_completion_transport=blocked
        with ThreadPoolExecutor(2) as executor:
            first=executor.submit(self.post,'/api/agent/run',{'run_id':run})
            self.assertTrue(entered.wait(10))
            contender=self.post('/api/agent/run',{'run_id':run})
            self.assertEqual(contender.status_code,409,contender.text)
            release.set();self.assertEqual(first.result().status_code,200)
        self.assertEqual(len(self.calls),1);self.assertEqual(len(self.ledger()),1)

    def test_backup_restore_retains_unresolved_reserve_while_revoking_authority(self):
        from campaign_agent.recovery import backup_store,restore_store
        run=self.start()
        self.app.provider_completion_transport=lambda *_a,**_k: (_ for _ in ()).throw(TimeoutError())
        self.assertEqual(self.post('/api/agent/run',{'run_id':run}).status_code,409)
        before=self.ledger()
        root=self.path.parent
        backup_store(self.path,self.path.with_suffix('.assets'),root/'backup')
        restore_store(root/'backup',root/'restored')
        with closing(sqlite3.connect(root/'restored/state.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT state,reserved_nanos,actual_cost,in_flight,receipt FROM inference_ledger ORDER BY position').fetchall(),before)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM staff_sessions').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_connections WHERE revoked_at IS NULL').fetchone()[0],0)


    def test_inference_selection_cannot_cross_actor_session_campaign_model_or_task(self):
        data=dict(request='Summarise',model='fixture/tool-model',session_id=uuid4().hex,run_id=uuid4().hex,catalog_id=self.catalog,provider_selection_id=self.selection['selection_id'])
        self.meta.requests.clear()
        for profile in ('buyer-b','buyer-a'):
            client=self.enterContext(TestClient(self.app.staff,base_url=self.app.staff_origin))
            client.post('/fixture',json={'profile':profile},headers={'Origin':self.app.staff_origin})
            client.headers.update({'Origin':self.app.staff_origin,'X-CSRF-Token':client.get('/api/session').headers['x-csrf-token']})
            response=client.post('/api/agent/placements',json=data,headers={'X-OpenRouter-Key':self.key})
            self.assertEqual(response.status_code,403,response.text)
        self.assertEqual(self.post('/api/agent/placements',{**data,'model':'other/model'}).status_code,400)
        structured=self.post('/api/agent/instruction-review',{'test_id':uuid4().hex,'mode':'openrouter','operation_id':uuid4().hex,'provider_selection_id':self.selection['selection_id']})
        self.assertEqual(structured.status_code,400,structured.text)
        self.client.post('/api/session/context',json={'campaign_id':'campaign-a-sibling'})
        self.assertEqual(self.post('/api/agent/placements',data).status_code,403)
        self.assertEqual(self.meta.requests,[]);self.assertEqual(self.calls,[]);self.assertEqual(self.ledger(),[])

    def test_current_metadata_and_charging_drift_reject_before_completion_or_reservation(self):
        from dataclasses import replace
        from campaign_agent.ports.inference import ProviderError
        run=self.start();original=deepcopy(self.meta.endpoint)
        for change in ('key','modality','endpoint','profile'):
            with self.subTest(change=change):
                old_profiles=self.app.provider_sessions.profiles
                old_architecture=deepcopy(self.meta.rows[0]['architecture'])
                if change=='modality':self.meta.rows[0]['architecture']['input_modalities']=['image']
                elif change=='endpoint':self.meta.endpoint['pricing']['request']='0.1'
                elif change=='profile':self.app.provider_sessions.profiles=(replace(old_profiles[0],version='changed'),)
                try:
                    if change=='key':
                        with patch.object(self.meta,'validate_key',side_effect=ProviderError('credential_mismatch')):
                            response=self.post('/api/agent/run',{'run_id':run})
                    else:response=self.post('/api/agent/run',{'run_id':run})
                    self.assertIn(response.status_code,(403,409),response.text)
                    self.assertEqual(self.ledger(),[]);self.assertEqual(self.calls,[])
                finally:
                    self.app.provider_sessions.profiles=old_profiles;self.meta.endpoint=deepcopy(original);self.meta.rows[0]['architecture']=old_architecture
        self.assertEqual(self.post('/api/agent/run',{'run_id':run}).status_code,200)

    def test_explicit_authored_paid_profile_settles_exact_cost_and_respects_run_cap(self):
        from dataclasses import replace
        from campaign_agent.model_catalogue import endpoint_fingerprint
        self.meta.endpoint['pricing']['request']='0.1'
        profile=replace(self.meta.profiles[0],endpoint_hash=endpoint_fingerprint(self.meta.endpoint),max_request_usd='0.1',version='authored-bounded-paid')
        self.app.provider_sessions.profiles=(profile,)
        connection=self.post('/api/openrouter/connect',{'operation_id':uuid4().hex,'tab_id':self.tab}).json()['connection_id']
        catalogue=self.post('/api/openrouter/models',{'connection_id':connection,'tab_id':self.tab,'search':'','cursor':None}).json()
        response=self.post('/api/openrouter/select',{'operation_id':uuid4().hex,'connection_id':connection,'tab_id':self.tab,'model_id':'fixture/tool-model','catalogue_revision':catalogue['catalogue_revision'],'profile':'planner','max_run_cost_usd':'0.25'})
        self.assertEqual(response.status_code,200,response.text);self.selection=response.json()
        self.reply['usage']['cost']=0.1
        self.reply['choices'][0]['message']['tool_calls'][0]['function']={'name':'read_campaign','arguments':'{}'}
        run=self.start()
        for _ in range(2):self.assertEqual(self.post('/api/agent/run',{'run_id':run}).status_code,200)
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,409,response.text);self.assertEqual(response.json()['code'],'budget_exhausted')
        self.assertEqual(len(self.calls),2)
        self.assertEqual([row[:4] for row in self.ledger()],[('settled',100000000,'0.1',0)]*2)


    def test_pinned_token_bounds_and_huge_usage_exponents_cannot_escape_accounting(self):
        from dataclasses import replace
        self.app.provider_sessions.profiles=(replace(self.meta.profiles[0],max_output_tokens=16),)
        self.selection=self.select()
        run=self.start()
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,409,response.text)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT actual_cost,anomaly FROM inference_ledger WHERE run_id=?',(run,)).fetchone(),('0',1))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM agent_steps WHERE run_id=?',(run,)).fetchone()[0],0)

    def test_huge_wire_cost_exponent_retains_unknown_without_expansion_or_new_dispatch(self):
        run=self.start()
        raw=json.dumps(self.reply).replace('"cost": 0','"cost": 1e1000000000').encode()
        def reply(request,*,timeout):self.calls.append(request);return io.BytesIO(raw)
        self.app.provider_completion_transport=reply
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.ledger()[0][:4],('received',0,None,0))

    def test_complete_http_error_retains_safe_usage_and_generation_before_semantic_rejection(self):
        from urllib.error import HTTPError
        run=self.start()
        def reply(request,*,timeout):
            self.calls.append(request)
            raise HTTPError(request.full_url,400,'authored error',{},io.BytesIO(json.dumps({'id':'gen-error','error':{'message':self.key},'usage':{'cost':0}}).encode()))
        self.app.provider_completion_transport=reply
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertNotEqual(response.status_code,200)
        self.assertEqual(self.ledger()[0][:4],('settled',0,'0',0))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT generation_id FROM inference_ledger').fetchone()[0],'gen-error')
            self.assertNotIn(self.key,'\n'.join(db.iterdump()))


    def test_escaped_nested_key_echo_retains_cost_but_no_semantic_secret_or_redispatch(self):
        from campaign_agent.recovery import backup_store
        run=self.start()
        escaped=''.join('\\u%04x'%ord(c) for c in self.key)
        self.reply['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"topic":"'+escaped+'"}'
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(len(self.calls),1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT state,actual_cost FROM inference_ledger').fetchone(),('settled','0'))
            self.assertNotIn(self.key,'\n'.join(db.iterdump()))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM agent_steps WHERE run_id=?',(run,)).fetchone()[0],0)
            receipt=json.loads(db.execute('SELECT receipt FROM inference_ledger').fetchone()[0])
            self.assertIsNone(receipt['message'])
        before=len(self.calls)
        self.assertNotEqual(self.post('/api/agent/run',{'run_id':run},key=False).status_code,200)
        self.assertEqual(len(self.calls),before)
        backup_store(self.path,self.path.with_suffix('.assets'),self.path.parent/'echo-backup')
        with closing(sqlite3.connect(self.path.parent/'echo-backup/state.sqlite3')) as db:
            self.assertNotIn(self.key,'\n'.join(db.iterdump()))
        self.reply['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"topic":"'+''.join('\\u%04x'%ord(c) for c in 'campaign_summary')+'"}'
        run=self.start()
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['status'],'answered')
        self.assertEqual(len(self.calls),2)

    def test_known_header_key_in_command_data_is_denied_before_any_start_mutation(self):
        from campaign_agent.recovery import backup_store
        def snapshot():
            with closing(sqlite3.connect(self.path)) as db:return '\n'.join(db.iterdump())
        before=snapshot()
        data=dict(request='My connection key is '+self.key,model='fixture/tool-model',session_id=uuid4().hex,
                  run_id=uuid4().hex,catalog_id=self.catalog,provider_selection_id=self.selection['selection_id'])
        for text in (data['request'],'Quoted key: '+json.dumps(self.key),
                     '{"key":"'+''.join('\\u%04x'%ord(c) for c in self.key)+'"}'):
            response=self.post('/api/agent/placements',{**data,'request':text})
            self.assertEqual(response.status_code,400,response.text)
            self.assertNotIn(self.key,response.text)
            self.assertEqual(snapshot(),before)
        self.assertEqual(self.calls,[])
        backup_store(self.path,self.path.with_suffix('.assets'),self.path.parent/'input-backup')
        with closing(sqlite3.connect(self.path.parent/'input-backup/state.sqlite3')) as db:self.assertNotIn(self.key,'\n'.join(db.iterdump()))
        # Ordinary escaped text remains a valid user request.
        data['request']='Summarise the campaign: {"note":"a \\"quoted\\" title"}'
        response=self.post('/api/agent/placements',data);self.assertEqual(response.status_code,200,response.text)
        response=self.post('/api/agent/run',{'run_id':data['run_id']});self.assertEqual(response.status_code,200,response.text)

    def test_profile_expiry_during_authority_renewal_or_marker_fences_new_dispatch_only(self):
        from dataclasses import replace
        from time import time
        from campaign_agent.inference_ledger import InferenceLedger
        initial=time();now=[initial]
        self.app.provider_sessions.clock=lambda:now[0]
        profile=replace(self.meta.profiles[0],expires_at=initial+10)
        self.app.provider_sessions.profiles=(profile,);self.selection=self.select()
        run=self.start();self.meta.requests.clear()
        def expire_after_endpoint(result):
            if 'endpoints' in self.meta.requests:now[0]=initial+11
            return result
        self.app.client.result_filter=expire_after_endpoint
        response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(response.json()['code'],'route_unqualified')
        self.assertEqual(self.calls,[]);self.assertEqual(self.ledger(),[])
        self.app.client.result_filter=lambda result:result
        now[0]=initial
        reserve=InferenceLedger.reserve
        def expire_after_reserve(ledger,*args,**kwargs):
            result=reserve(ledger,*args,**kwargs);now[0]=initial+11;return result
        with patch.object(InferenceLedger,'reserve',expire_after_reserve):
            response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(self.calls,[])
        # An expiry inside the reservation transaction rolls back admission.
        self.assertEqual(self.ledger(),[])
        now[0]=initial
        dispatch=InferenceLedger.dispatch
        def expire_before_marker(ledger,*args,**kwargs):
            now[0]=initial+11
            return dispatch(ledger,*args,**kwargs)
        with patch.object(InferenceLedger,'dispatch',expire_before_marker):
            response=self.post('/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(self.ledger()[0][:4],('released_unsent',0,None,0))
        self.assertEqual(self.calls,[])
        now[0]=initial
        # Receipt-only recovery after expiry still consumes its original result.
        from campaign_agent.agent.planner import PlacementAgent
        with patch.object(PlacementAgent,'_tool',side_effect=sqlite3.OperationalError('before semantic save')):
            self.assertNotEqual(self.post('/api/agent/run',{'run_id':run}).status_code,200)
        self.assertEqual(len(self.calls),1)
        now[0]=initial+11;self.meta.requests.clear()
        response=self.post('/api/agent/run',{'run_id':run},key=False)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.meta.requests,[]);self.assertEqual(len(self.calls),1)


    def test_unsupported_deep_or_repeated_embedded_json_fails_closed(self):
        from campaign_agent.ports.inference import ForegroundCredential,ProviderError
        credential=ForegroundCredential(self.key)
        deep='ordinary text'
        for _ in range(66):deep=[deep]
        with self.assertRaises(ProviderError):self.app.provider_sessions._safe(deep,credential)
        encoded='ordinary text'
        for _ in range(10):encoded=json.dumps(encoded)
        with self.assertRaises(ProviderError):self.app.provider_sessions._safe({'arguments':encoded},credential)
        ordinary={'arguments':json.dumps({'topic':'campaign_summary','note':'a "quoted" title'})}
        self.assertEqual(self.app.provider_sessions._safe(ordinary,credential),ordinary)


class LocalForegroundTests(unittest.TestCase):
    def test_local_handler_uses_same_planner_and_three_structured_commands(self):
        self.run_local_foreground_journey(bootstrapped=False)

    def test_bootstrapped_handler_keeps_foreground_admission_and_cache(self):
        self.run_local_foreground_journey(bootstrapped=True)

    def run_local_foreground_journey(self, *, bootstrapped):
        from contextlib import ExitStack,redirect_stdout
        from email.message import Message
        from unittest.mock import Mock
        from scripts import placement_review
        from campaign_agent.adapters.fixture_access import AuthoredProviderMetadata
        from campaign_agent.bootstrap.runtime import create_runtime as AgentRuntime
        from campaign_agent.bootstrap.planner import create_local_planner, _provider_sessions
        from campaign_agent.handoff import package_fingerprint
        with TemporaryDirectory() as directory,ExitStack() as stack:
            path=Path(directory)/'local.sqlite';servers=[];runtimes=[];metadata=AuthoredProviderMetadata();calls=[]
            output={'finish_reason':'tool_calls','message':{'tool_calls':[{'id':'local-call','type':'function','function':{'name':'read_campaign','arguments':'{}'}}]}}
            def complete(request,*,timeout):
                calls.append(request)
                return io.BytesIO(json.dumps({'id':'gen-local-authored','model':'fixture/tool-model','usage':{'cost':0,'prompt_tokens':100,'completion_tokens':10},'choices':[output]}).encode())
            def server(address,handler):
                value=Mock(server_port=address[1]);value.__enter__=Mock(return_value=value);value.__exit__=Mock(return_value=False)
                value.handler=handler;servers.append(value);return value
            def runtime(*args, **kwargs):
                create_runtime = create_local_planner if bootstrapped else AgentRuntime
                value = create_runtime(*args, **kwargs)
                runtimes.append(value)
                return value
            stack.enter_context(patch.object(placement_review,'ThreadingHTTPServer',side_effect=server))
            stack.enter_context(patch.object(placement_review.Thread,'start'));stack.enter_context(patch.object(placement_review.Thread,'join'))
            stack.enter_context(patch.object(placement_review.secrets,'token_urlsafe',return_value='authored-local-operator'))
            stack.enter_context(redirect_stdout(io.StringIO()))
            options = {"runtime_factory": runtime}
            if bootstrapped:
                create_local_planner(path)
                options.update(runtime_factory=runtime, provider_sessions_factory=_provider_sessions, initialize=False)
            placement_review.serve(18981, False, draft_path=path, viewer_port=18982, provider_metadata=metadata,
                                   provider_profiles=metadata.profiles, provider_completion_transport=complete, **options)
            handler=servers[0].handler.__new__(servers[0].handler);handler.server=servers[0];handler.send=Mock()
            def post(route,data,key=True,expected=200):
                body=json.dumps(data).encode();headers=Message()
                for k,v in {'Host':'127.0.0.1:18981','X-Local-Operator':'authored-local-operator','Origin':'http://127.0.0.1:18981','Content-Type':'application/json','Content-Length':str(len(body))}.items():headers[k]=v
                if key:headers['X-OpenRouter-Key']=metadata.keys[0]
                handler.path=route;handler.headers=headers;handler.rfile=io.BytesIO(body)
                handler.do_POST();status,result=handler.send.call_args.args
                self.assertEqual(status,expected,result);return result
            tab=uuid4().hex
            connection=post('/api/openrouter/connect',{'operation_id':uuid4().hex,'tab_id':tab})['connection_id']
            catalogue=post('/api/openrouter/models',{'connection_id':connection,'tab_id':tab,'search':'','cursor':None})
            def select(profile):
                return post('/api/openrouter/select',{'operation_id':uuid4().hex,'connection_id':connection,'tab_id':tab,'model_id':'fixture/tool-model','catalogue_revision':catalogue['catalogue_revision'],'profile':profile,'max_run_cost_usd':'0'})
            planner=select('planner');owner=runtimes[0];run=uuid4().hex
            with closing(sqlite3.connect(path)) as db:before='\n'.join(db.iterdump())
            denied=post('/api/agent/placements',{'request':'My key is '+metadata.keys[0],
                'model':'fixture/tool-model','session_id':uuid4().hex,'run_id':uuid4().hex,
                'catalog_id':owner.planner.catalogs.list()[0]['id'],'provider_selection_id':planner['selection_id']},expected=400)
            self.assertNotIn(metadata.keys[0],json.dumps(denied))
            with closing(sqlite3.connect(path)) as db:self.assertEqual('\n'.join(db.iterdump()),before)
            self.assertEqual(calls,[])
            post('/api/agent/placements',{'request':'Prepare contextual placements','model':'fixture/tool-model','session_id':uuid4().hex,'run_id':run,'catalog_id':owner.planner.catalogs.list()[0]['id'],'provider_selection_id':planner['selection_id'],'draft_permission':'placements'})
            for name,args in (('read_campaign',{}),('classify_catalog',{}),('save_placement_draft',{'contexts':['video-editing','audiobook']})):
                output['message']['tool_calls'][0]['function']={'name':name,'arguments':json.dumps(args)}
                result=post('/api/agent/run',{'run_id':run})
            self.assertEqual(result['status'],'ready_for_review')
            fingerprint=owner.drafts.review_package(owner.drafts.campaign_id,2)['fingerprint']
            package=owner.drafts.approve_package(owner.drafts.campaign_id,2,fingerprint)['package']
            for _ in range(3):owner.performance.viewer.open_example(owner.drafts.examples[0].creative_ref,content_fingerprint=package_fingerprint(package['groups'][0]['content']))
            review=owner.performance.review(owner.drafts.campaign_id,2,fingerprint,'balanced')
            owner.performance.save_correction(owner.drafts.campaign_id,2,fingerprint,review['id'],'keep_takes','Keep these takes.',uuid4().hex)
            review=owner.performance.review(owner.drafts.campaign_id,2,fingerprint,'balanced')
            structured=select('structured_review')
            def structured_start(route,data,reply):
                output.clear();output.update(finish_reason='stop',message={'content':json.dumps(reply)})
                result=post(route,{**data,'mode':'openrouter','operation_id':uuid4().hex,'provider_selection_id':structured['selection_id']})
                for _ in range(4):
                    result=post('/api/agent/run',{'run_id':result['run_id']})
                    if result['status']!='running':break
                return result
            result=structured_start('/api/agent/next-test',{'campaign_id':owner.drafts.campaign_id,'revision':2,'fingerprint':fingerprint,'review_id':review['id']},{'playback':'both_in_full','focus':'delivery','choice':'scene_fit'})
            self.assertEqual(result['status'],'ready_for_review')
            fingerprint=owner.drafts.review_package(owner.drafts.campaign_id,3)['fingerprint'];owner.drafts.approve_package(owner.drafts.campaign_id,3,fingerprint)
            test=owner.instruction_tests.start(owner.drafts.campaign_id,3,fingerprint)
            for arm in ('original','revised'):
                for _ in range(20):
                    with patch('campaign_agent.instruction_tests.secrets.choice',return_value=arm):owner.instruction_tests.open(test['id'],uuid4().hex,source='participant')
            result=structured_start('/api/agent/instruction-review',{'test_id':test['id']},{'reason_code':'revised_not_higher'})
            self.assertEqual(result['status'],'ready_for_review')
            review=owner.instruction_tests.read(owner.drafts.campaign_id,3,fingerprint)['review']
            result=structured_start('/api/agent/experiment-next-test',{'test_id':test['id'],'review_id':review['id']},{'playback':'take_order','focus':'pacing','choice':'moment_fit'})
            self.assertEqual(result['status'],'ready_for_review');self.assertEqual(owner.drafts.read()['revision'],4)
            self.assertEqual(len(calls),6)
            self.assertTrue(all(r.foreground is None for r in runtimes))
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM inference_ledger').fetchone()[0],6)
                self.assertNotIn(metadata.keys[0],'\n'.join(db.iterdump()))
