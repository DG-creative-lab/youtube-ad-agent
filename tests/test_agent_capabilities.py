"""Capability visibility is advisory; native scope and dispatch remain authoritative."""
from collections import Counter
from contextlib import ExitStack, closing, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from starlette.testclient import TestClient

from campaign_agent.access import LOCAL_OPERATOR, Operator
from campaign_agent.adapters.fixture_access import offline_fixture
from campaign_agent.agent.capabilities import CAPABILITIES
from campaign_agent.agent.planning_models import TOOLS
from campaign_agent.agent.run import AgentRuntime
from campaign_agent.ports.access import AccessUnavailable
from scripts import placement_review


class Decisions:
    def __init__(self):
        self.denied = set()
        self.unavailable = None
        self.requests = []

    def decide(self, request):
        self.requests.append(request)
        if request.capability == self.unavailable:
            return 'unavailable'
        return 'deny' if request.capability in self.denied else 'allow'


def entries(response):
    return {item['id']: item for item in response['capabilities']}


def dump(path):
    with closing(sqlite3.connect(path)) as db:
        return tuple(db.iterdump())


class CapabilityCommandTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / 'campaign.sqlite3'
        self.policy = Decisions()
        self.runtime = AgentRuntime(self.path, access=self.policy)
        self.policy.requests.clear()

    def test_registry_covers_real_model_tools_and_keeps_other_entrypoints_distinct(self):
        before = json.dumps(TOOLS, sort_keys=True)
        response = self.runtime.capabilities()
        self.assertEqual(response['schema_version'], 1)
        self.assertEqual(response['availability_scope'], 'current_access_and_configuration')
        self.assertEqual(response['prerequisites_checked_at'], 'dispatch')
        model_names = {item['id'] for item in response['capabilities'] if item['kind'] == 'model_tool'}
        self.assertEqual(model_names, {item['function']['name'] for item in TOOLS})
        self.assertEqual(len(model_names), 11)
        rows = entries(response)
        for name in ('review_google_ads_delivery', 'recommend_delivery_next_test'):
            self.assertEqual(rows[name]['kind'], 'application_request')
            self.assertEqual(rows[name]['tool_names'], [])
        self.assertEqual(rows['apply_instruction_finding']['kind'], 'workspace_action')
        self.assertNotIn('youtube:learning.manage', rows['apply_instruction_finding']['required_capabilities'])
        self.assertEqual(rows['generate_contextual_voiceover']['state'], 'planned')
        self.assertEqual(rows['generate_contextual_voiceover']['reason_codes'], ['not_implemented'])
        self.assertEqual(rows['classify_catalog']['effects'], ['compute', 'derived_record_write'])
        self.assertEqual(rows['validate_campaign_setup']['effects'], ['compute', 'derived_record_write'])
        self.assertEqual(rows['read_campaign']['state'], 'available')
        for name, permission in (('save_placement_draft', 'placements'),
                                 ('prepare_next_test', 'instruction_test'),
                                 ('apply_instruction_finding', 'instruction_test')):
            self.assertEqual(rows[name]['state'], 'blocked')
            self.assertEqual(rows[name]['required_draft_permission'], permission)
            self.assertIn('request_draft_permission_required', rows[name]['reason_codes'])
        response['capabilities'][0]['required_capabilities'].append('made-up')
        self.assertNotIn('made-up', self.runtime.capabilities()['capabilities'][0]['required_capabilities'])
        self.assertEqual(before, json.dumps(TOOLS, sort_keys=True))
        self.assertEqual(len(CAPABILITIES), len({item.id for item in CAPABILITIES}))

    def test_current_access_is_checked_once_per_distinct_grant_and_refreshed_next_read(self):
        first = entries(self.runtime.capabilities())
        counts = Counter(request.capability for request in self.policy.requests)
        self.assertTrue(counts)
        self.assertEqual(set(counts.values()), {1})
        self.assertEqual(first['review_performance']['state'], 'offline_only')
        self.policy.denied.add('youtube:review.write')
        self.policy.requests.clear()
        rows = entries(self.runtime.capabilities())
        self.assertEqual(rows['review_performance']['state'], 'blocked')
        self.assertIn('permission_denied', rows['assess_instruction_experiment']['reason_codes'])
        self.assertEqual(set(Counter(r.capability for r in self.policy.requests).values()), {1})
        self.policy.denied.clear()
        self.policy.unavailable = 'youtube:review.write'
        with self.assertRaises(AccessUnavailable):
            self.runtime.capabilities()

    def test_read_scope_actor_and_unavailable_authority_fail_before_projection(self):
        self.policy.denied.add('youtube:campaign.read')
        with self.assertRaises(PermissionError):
            self.runtime.capabilities()
        self.assertEqual(len(self.policy.requests), 1)
        self.policy.denied.clear()
        self.policy.unavailable = 'youtube:campaign.read'
        with self.assertRaises(AccessUnavailable):
            self.runtime.capabilities()
        self.policy.unavailable = None
        self.runtime.drafts.campaign_id = 'foreign-campaign'
        with self.assertRaises(PermissionError):
            self.runtime.capabilities()
        self.runtime.drafts.campaign_id = 'tts-sample'
        self.runtime.operator = Operator('different-actor', LOCAL_OPERATOR.grants)
        with self.assertRaises(PermissionError):
            self.runtime.capabilities()

    def test_read_never_runs_provider_readiness_or_domain_effects_and_labels_components(self):
        reporting = Mock()
        self.runtime.delivery.reporting = reporting
        self.runtime.planner.remote.models = ('example/main:free',)
        before = dump(self.path)
        with ExitStack() as stack:
            guards = [stack.enter_context(patch.object(obj, name, side_effect=AssertionError(name)))
                      for obj, name in ((self.runtime.setup, 'validate'),
                                        (self.runtime.performance, 'capture_review'),
                                        (self.runtime.planner.remote, 'next_turn'),
                                        (self.runtime.planner.classifier, 'classify'),
                                        (self.runtime.drafts, '_package_review'),
                                        (self.runtime.delivery, 'capture'))]
            rows = entries(self.runtime.capabilities())
            for guard in guards:
                guard.assert_not_called()
        reporting.snapshot.assert_not_called()
        self.assertEqual(dump(self.path), before)
        self.assertEqual(rows['classify_catalog']['execution_modes'], ['simulated_specialist'])
        self.assertEqual(rows['classify_catalog']['state'], 'offline_only')
        self.assertEqual(rows['validate_campaign_setup']['execution_modes'], ['simulated_setup'])
        self.assertEqual(rows['review_performance']['execution_modes'], ['sample_delivery', 'local_viewer_activity'])
        self.assertEqual(rows['review_google_ads_delivery']['state'], 'available')
        self.assertEqual(rows['review_google_ads_delivery']['execution_modes'],
                         ['configured_reporting', 'local_viewer_activity'])
        self.assertIn('external_read', rows['review_google_ads_delivery']['effects'])
        self.assertEqual(rows['recommend_delivery_next_test']['execution_modes'], ['application'])
        self.assertNotIn('external_read', rows['recommend_delivery_next_test']['effects'])
        self.runtime.delivery.reporting = None
        rows = entries(self.runtime.capabilities())
        self.assertEqual(rows['review_google_ads_delivery']['state'], 'offline_only')
        self.assertEqual(rows['review_google_ads_delivery']['reason_codes'],
                         ['offline_implementation', 'delivery_metrics_unavailable'])
        self.assertEqual(rows['review_google_ads_delivery']['execution_modes'],
                         ['offline_rehearsal', 'local_viewer_activity'])
        self.assertNotIn('external_read', rows['review_google_ads_delivery']['effects'])
        self.assertEqual(rows['recommend_delivery_next_test']['state'], 'available')
        self.runtime.delivery.demo_scenario = 'wait'
        self.assertEqual(entries(self.runtime.capabilities())['review_google_ads_delivery']['execution_modes'],
                         ['authored_delivery', 'local_viewer_activity'])

    def test_catalogue_cannot_grant_write_or_replay_new_authority_and_unknown_calls_still_fail(self):
        catalog = self.runtime.planner.catalogs.register('Authored test', [
            {'video_id': 'SAMPLE00001', 'description': 'Video editing voiceover tutorial', 'source': 'synthetic'}])
        visible = entries(self.runtime.capabilities())
        visible['save_placement_draft']['state'] = 'available'
        operation, session = uuid4().hex, uuid4().hex
        arguments = dict(request='Find placements for video editing.', model='simulated', session_id=session,
                         run_id=operation, catalog_id=catalog, draft_permission='none')
        self.runtime.planner.start(**arguments)
        for _ in range(8):
            result = self.runtime.resume(operation)
            if result['status'] != 'running':
                break
        self.assertEqual(result['result']['reply_code'], 'placement_draft_not_authorized')
        self.assertEqual(self.runtime.drafts.read()['revision'], 1)
        self.assertEqual(self.runtime.planner.start(**arguments), operation)
        with self.assertRaises(ValueError):
            self.runtime.planner.start(**{**arguments, 'draft_permission': 'placements'})
        self.assertEqual(self.runtime.drafts.read()['revision'], 1)
        unknown = Mock()
        unknown.next_turn.side_effect = lambda *args: {
            'call_id': uuid4().hex, 'tool': 'generate_contextual_voiceover', 'arguments': {},
            'inference': {'mode': 'simulated', 'usage': None}}
        self.runtime.planner.simulator = unknown
        operation = uuid4().hex
        self.runtime.planner.start(**{**arguments, 'session_id': uuid4().hex, 'run_id': operation})
        for _ in range(8):
            result = self.runtime.resume(operation)
        self.assertTrue(any('error' in step['result'] for step in result['steps']))
        self.assertEqual(self.runtime.drafts.read()['revision'], 1)


class CapabilityHttpTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / 'staff.sqlite3'
        self.app = offline_fixture(self.path)
        self.buyer = self.client('buyer-a')
        self.other = self.client('buyer-b')
        self.reviewer = self.client('reviewer-a')
        self.public = self.enterContext(TestClient(self.app.viewer, base_url=self.app.viewer_origin))

    def client(self, profile):
        client = self.enterContext(TestClient(self.app.staff, base_url=self.app.staff_origin))
        result = client.post('/fixture', json={'profile': profile}, headers={'Origin': self.app.staff_origin})
        self.assertEqual(result.status_code, 200)
        return client

    def test_hosted_catalogue_is_scoped_generic_and_has_no_domain_or_provider_effect(self):
        before = dump(self.path)
        with patch('campaign_agent.agent.planning_models.OpenRouterPlanner.next_turn',
                   side_effect=AssertionError('Unexpected inference')) as inference:
            response = self.buyer.get('/api/agent/capabilities')
            other = self.other.get('/api/agent/capabilities')
            reviewer = self.reviewer.get('/api/agent/capabilities')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(other.status_code, 200, other.text)
        self.assertEqual(reviewer.status_code, 200, reviewer.text)
        self.assertEqual(response.json(), other.json())
        self.assertEqual(entries(reviewer.json())['read_campaign']['state'], 'blocked')
        serialized = response.text
        for private in ('tenant-a', 'campaign-a', 'workspace-a', 'buyer-a', 'gp-buyer', 'source_reference', 'fingerprint'):
            self.assertNotIn(private, serialized)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        inference.assert_not_called()
        self.assertEqual(dump(self.path), before)

    def test_hosted_selector_public_revocation_and_outage_boundaries(self):
        for query in ('campaign_id=campaign-b', 'draft_permission=placements', 'model=simulated', 'id=x',
                      'campaign_id=', 'id=x&id=y'):
            with self.subTest(query=query):
                self.assertEqual(self.buyer.get('/api/agent/capabilities?' + query).status_code, 400)
        self.assertEqual(self.public.get('/api/agent/capabilities').status_code, 404)
        anonymous = self.enterContext(TestClient(self.app.staff, base_url=self.app.staff_origin))
        self.assertEqual(anonymous.get('/api/agent/capabilities').status_code, 401)
        authority = self.app.client
        authority.permissions['buyer-a'].remove('youtube:campaign.read')
        self.assertEqual(self.buyer.get('/api/agent/capabilities').status_code, 403)
        authority.permissions['buyer-a'].add('youtube:campaign.read')
        authority.revoked.add('buyer-a')
        self.assertEqual(self.buyer.get('/api/agent/capabilities').status_code, 401)
        authority.revoked.clear()
        authority.unavailable = True
        self.assertEqual(self.buyer.get('/api/agent/capabilities').status_code, 503)


class CapabilityLocalRouteTests(unittest.TestCase):
    def test_actual_local_handler_requires_operator_rejects_selectors_and_keeps_viewer_isolated(self):
        with TemporaryDirectory() as directory, ExitStack() as stack:
            servers = []
            runtimes = []
            def server(address, handler):
                result = Mock(server_port=address[1])
                result.__enter__ = Mock(return_value=result)
                result.__exit__ = Mock(return_value=False)
                result.handler = handler
                servers.append(result)
                return result
            def runtime(*args, **kwargs):
                result = AgentRuntime(*args, **kwargs)
                runtimes.append(result)
                return result
            stack.enter_context(patch.object(placement_review, 'ThreadingHTTPServer', side_effect=server))
            stack.enter_context(patch.object(placement_review, 'Thread'))
            stack.enter_context(patch.object(placement_review.secrets, 'token_urlsafe', return_value='authored-operator'))
            stack.enter_context(patch.object(placement_review, 'AgentRuntime', side_effect=runtime))
            stack.enter_context(redirect_stdout(io.StringIO()))
            placement_review.serve(18981, live=False, viewer_port=18982,
                                   draft_path=Path(directory) / 'local.sqlite3')
            handler = servers[0].handler.__new__(servers[0].handler)
            handler.server = servers[0]
            handler.path = '/api/agent/capabilities'
            handler.headers = {'Host': '127.0.0.1:18981', 'X-Local-Operator': 'authored-operator'}
            handler.send = Mock()
            handler.do_GET()
            self.assertEqual(handler.send.call_args.args[0], 200)
            self.assertEqual(handler.send.call_args.args[1], runtimes[0].capabilities())
            for path in ('/api/agent/capabilities?draft_permission=placements', '/api/agent/capabilities?id='):
                handler.path = path
                handler.do_GET()
                self.assertEqual(handler.send.call_args.args[0], 400)
            handler.path = '/api/agent/capabilities'
            handler.headers['X-Local-Operator'] = 'wrong'
            handler.do_GET()
            self.assertEqual(handler.send.call_args.args[0], 403)
            handler.server = servers[1]
            handler.headers['Host'] = '127.0.0.1:18982'
            handler.do_GET()
            self.assertEqual(handler.send.call_args.args[0], 404)
