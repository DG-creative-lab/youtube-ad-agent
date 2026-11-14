"""Durability and captured-receipt compatibility across the foreground credential cutover."""
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import Mock,patch
from uuid import uuid4

from campaign_agent.agent.run import AgentRuntime
from campaign_agent.provider_sessions import ProviderSessions,ProviderContext
from campaign_agent.recovery import backup_store,restore_store
from campaign_agent.adapters.fixture_access import offline_fixture,AuthoredProviderMetadata
from campaign_agent.adapters.local_access import LocalDemoAccess
from campaign_agent.access import LOCAL_CONTEXT,LOCAL_OPERATOR
from campaign_agent.assets import AssetStore
from campaign_agent.creatives import EXAMPLES
from campaign_agent.handoff import DEMO_MEDIA_DIR
import test_openrouter_http as http_fixtures
import test_openrouter_reviews as review_fixtures
import test_openrouter_instructions as draft_fixtures
import test_placement_planner as planner_fixtures


class ProviderDurabilityTests(unittest.TestCase):
    def setUp(self):
        self.case=http_fixtures.OpenRouterHttpTests();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def test_reopen_keeps_fixed_expiry_and_backup_restore_revokes_only_authority_not_history(self):
        c=self.case;body={'operation_id':uuid4().hex,'tab_id':c.tab}
        first=c.post('connect',body);connection=first['connection_id']
        catalogue=c.models(connection);selection=c.post('select',c.selection(connection,catalogue['catalogue_revision']))
        c.app.provider_sessions=ProviderSessions(c.path,metadata=c.metadata,profiles=c.metadata.profiles)
        self.assertEqual(c.post('connect',body),first)
        parent=c.path.parent
        before=c.buyer.get('/api/campaign').json()
        backup_store(c.path,c.path.with_suffix('.assets'),parent/'backup')
        with closing(sqlite3.connect(parent/'backup/state.sqlite3')) as db:
            self.assertIsNotNone(db.execute('SELECT revoked_at FROM provider_connections').fetchone()[0])
            self.assertNotIn(c.key,'\n'.join(db.iterdump()))
        c.models(connection) # Taking the copy never revokes the live source.
        restored=restore_store(parent/'backup',parent/'restored')
        app=offline_fixture(restored['database'],asset_root=restored['assets'])
        with closing(sqlite3.connect(restored['database'])) as db:
            self.assertIsNotNone(db.execute('SELECT revoked_at FROM provider_connections').fetchone()[0])
            self.assertEqual(json.loads(db.execute('SELECT snapshot FROM provider_selections').fetchone()[0]),selection)
            self.assertNotIn(c.key,'\n'.join(db.iterdump()))
        self.assertEqual(c.buyer.get('/api/campaign').json(),before)

    def test_local_connections_are_revoked_in_backups_without_any_staff_session_dependency(self):
        c=self.case;path=c.path.parent/'local.sqlite3'
        runtime=AgentRuntime(path,media_dir=DEMO_MEDIA_DIR)
        metadata=AuthoredProviderMetadata();service=ProviderSessions(path,metadata=metadata,profiles=metadata.profiles)
        body={'operation_id':uuid4().hex,'tab_id':uuid4().hex}
        context=ProviderContext(LOCAL_OPERATOR.id,LOCAL_CONTEXT,runtime.drafts.campaign_id,'a'*64,__import__('time').time()+3600,
                               {'path':'/api/openrouter/connect','body':body},lambda:None)
        result=service.command('connect',body,[metadata.keys[0]],context,LocalDemoAccess())
        assets=path.parent/'local-assets';store=AssetStore(path,assets)
        store.import_catalog(LOCAL_CONTEXT,runtime.drafts.campaign_id,EXAMPLES,DEMO_MEDIA_DIR,operator=LOCAL_OPERATOR,access=LocalDemoAccess())
        backup_store(path,assets,path.parent/'local-backup')
        with closing(sqlite3.connect(path.parent/'local-backup/state.sqlite3')) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='staff_sessions'").fetchone())
            self.assertIsNotNone(db.execute('SELECT revoked_at FROM provider_connections WHERE id=?',(result['connection_id'],)).fetchone()[0])


class CapturedReceiptCompatibilityTests(unittest.TestCase):
    def test_main_model_received_turn_recovers_without_a_web_provider_request(self):
        case=planner_fixtures.PlacementPlannerTests();case.setUp();self.addCleanup(case.doCleanups)
        transport=Mock(side_effect=lambda *a,**k:case.reply('respond',{'topic':'campaign_summary'}))
        runtime=case.reopen(main_models=(planner_fixtures.MODEL,),main_transport=transport)
        with patch.dict('os.environ',{'OPENROUTER_API_KEY':'authored-legacy-key'}):
            run=case.start(runtime=runtime,model=planner_fixtures.MODEL)
            with patch.object(runtime.planner,'_tool',side_effect=sqlite3.OperationalError('Authored interrupted tool commit')):
                with self.assertRaises(sqlite3.OperationalError):runtime.resume(run,max_steps=1)
        blocked=Mock(side_effect=AssertionError('No new completion'))
        reopened=case.reopen(main_models=(planner_fixtures.MODEL,),main_transport=blocked,web=True)
        self.assertEqual(case.start(runtime=reopened,model=planner_fixtures.MODEL,run_id=run),run)
        self.assertEqual(reopened.resume(run,max_steps=1)['status'],'answered')
        blocked.assert_not_called();self.assertEqual(transport.call_count,1)

    def test_structured_review_received_receipt_recovers_under_web_disabled_composition(self):
        case=review_fixtures.OpenRouterReviewTests();case.setUp();self.addCleanup(case.doCleanups)
        op=uuid4().hex;run=case.start(op);case.runtime.resume(run,max_steps=1)
        with patch.object(case.runtime.instruction_tests,'validate_assessment',side_effect=sqlite3.OperationalError('Authored interrupted receipt')):
            with self.assertRaises(sqlite3.OperationalError):case.runtime.resume(run,max_steps=1)
        self.assertEqual(case.runtime.read(run)['inference']['state'],'received')
        blocked=Mock(side_effect=AssertionError('No new completion'))
        reopened=AgentRuntime(case.case.path,media_dir=case.case.media,openrouter_models=(review_fixtures.MODEL,),review_transport=blocked,web=True)
        self.assertEqual(reopened.start_instruction_review(case.case.test['id'],mode='openrouter',model=review_fixtures.MODEL,operation_id=op),run)
        reopened.resume(run);blocked.assert_not_called();self.assertEqual(case.transport.call_count,1)

    def test_structured_draft_received_receipt_recovers_under_web_disabled_composition(self):
        case=draft_fixtures.OpenRouterInstructionTests();case.setUp();self.addCleanup(case.doCleanups)
        op=uuid4().hex;run=case.start(op);case.runtime.resume(run,max_steps=1)
        with patch.object(case.runtime.drafts,'validate_instruction',side_effect=sqlite3.OperationalError('Authored interrupted receipt')):
            with self.assertRaises(sqlite3.OperationalError):case.runtime.resume(run,max_steps=1)
        blocked=Mock(side_effect=AssertionError('No new completion'))
        reopened=AgentRuntime(case.case.drafts.path,media_dir=case.case.drafts.media_dir,
            openrouter_draft_models=(draft_fixtures.MODEL,),draft_transport=blocked,web=True)
        self.assertEqual(reopened.start_next_test(case.case.campaign,2,case.case.fingerprint,case.review['id'],
            mode='openrouter',model=draft_fixtures.MODEL,operation_id=op),run)
        reopened.resume(run);blocked.assert_not_called();self.assertEqual(case.transport.call_count,1)

