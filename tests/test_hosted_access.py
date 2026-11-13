"""HTTP -> native state -> current authority -> effect checks, all synthetic."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from starlette.testclient import TestClient

from campaign_agent.adapters.fixture_access import offline_fixture
from campaign_agent.adapters.gateplane import GateplaneAccess, timestamp
from campaign_agent.hosted import HostedApplication
from campaign_agent.ports.access import AccessRequest, AccessUnavailable


class HostedAccessTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / 'shared.sqlite3'
        self.app = offline_fixture(self.path)
        self.authority = self.app.client
        self.buyer = self.client('buyer-a')
        self.reviewer = self.client('reviewer-a')
        self.other = self.client('buyer-b')
        self.admin = self.client('admin-a')
        self.public = self.enterContext(TestClient(self.app.viewer, base_url=self.app.viewer_origin))

    def client(self, profile):
        c = self.enterContext(TestClient(self.app.staff, base_url=self.app.staff_origin))
        response = c.post('/fixture', json={'profile': profile}, headers={'Origin': self.app.staff_origin})
        self.assertEqual(response.status_code, 200, response.text)
        c.headers.update({'Origin': self.app.staff_origin, 'X-CSRF-Token': c.get('/api/session').headers['x-csrf-token']})
        return c

    def post(self, client, path, data, status=200):
        response = client.post(path, json=data)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def prepare(self):
        config = self.buyer.get('/api/config').json()
        operation = uuid4().hex
        self.post(self.buyer, '/api/agent/placements', dict(request='Prepare a YouTube test for ElevenLabs Text to Speech.',
            model='simulated', session_id=uuid4().hex, run_id=operation,
            catalog_id=config['agentPlanner']['catalogs'][0]['id'], draft_permission='placements'))
        for _ in range(4):
            run = self.post(self.buyer, '/api/agent/run', {'run_id': operation})
            if run['status'] != 'running':
                break
        self.assertEqual(run['status'], 'ready_for_review')
        review = self.buyer.get('/api/campaign/package?revision=2').json()
        return dict(campaign_id='campaign-a', revision=2, fingerprint=review['fingerprint'])

    def test_buyer_draft_separate_review_export_setup_and_public_completion(self):
        args = self.prepare()
        self.post(self.buyer, '/api/campaign/approve', args, 403)
        self.post(self.admin, '/api/campaign/approve', args, 403)
        self.post(self.reviewer, '/api/campaign/export', args, 409)
        self.post(self.reviewer, '/api/campaign/approve', args)
        self.post(self.buyer, '/api/campaign/export', args, 403)
        exported = self.post(self.reviewer, '/api/campaign/export', args)
        links = exported['public_comparisons']
        self.assertEqual(len(links), 2)
        self.assertEqual(exported['approval']['actor_id'], 'gp-reviewer-a')
        plan = self.post(self.reviewer, '/api/campaign/setup/validate', args)
        setup = self.post(self.reviewer, '/api/campaign/setup/create', {**args, 'setup_id': plan['id']})
        self.assertEqual(setup['status'], 'verified')
        token = next(link['path'] for link in links if link['creative_ref'] == 'editing-voiceover-v1').split('attribution=')[1]
        response = self.public.post('/api/viewer/open', json={'attribution': token, 'visit_id': None},
                                    headers={'Origin': self.app.viewer_origin})
        self.assertEqual(response.status_code, 200, response.text)
        visit = response.json()
        for take in ('a', 'b'):
            for kind in ('start', 'finish'):
                result = self.public.post('/api/viewer/event', json=dict(creative_ref=visit['creative_ref'],
                    example_ref=visit['example']['ref'], visit_id=visit['visit_id'], event_id=uuid4().hex,
                    kind=kind, take=take), headers={'Origin': self.app.viewer_origin})
                self.assertEqual(result.status_code, 200, result.text)
        response = self.public.post('/api/viewer/event', json=dict(creative_ref=visit['creative_ref'],
                    example_ref=visit['example']['ref'], visit_id=visit['visit_id'], event_id=uuid4().hex,
                    kind='choose', take='a'), headers={'Origin': self.app.viewer_origin})
        self.assertTrue(response.json()['complete'])
        self.assertEqual(self.public.get(visit['example']['takes'][0]['url']).status_code, 200)
        delivery = self.post(self.buyer, '/api/campaign/google-ads-delivery', args)
        self.assertEqual(delivery['groups'][0]['viewer_activity'], {'arrivals': 1, 'completions': 1})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT campaign_id FROM viewer_visits WHERE id=?', (visit['visit_id'],)).fetchone()[0], 'campaign-a')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM viewer_completions').fetchone()[0], 1)

    def test_client_brand_campaign_and_session_selectors_cannot_grant_access(self):
        args = self.prepare()
        self.post(self.other, '/api/campaign/approve', args, 403)
        self.post(self.other, '/api/session/context', {'campaign_id': 'campaign-a'}, 403)
        self.assertEqual(self.other.get('/api/session').json()['campaign_id'], 'campaign-b')
        self.post(self.buyer, '/api/session/context', {'campaign_id': 'campaign-a-brand2'})
        self.assertEqual(self.buyer.get('/api/session').json()['brand_id'], 'brand2')
        self.post(self.buyer, '/api/session/context', {'campaign_id': 'campaign-a'})
        self.authority.campaigns['buyer-a'] = {'campaign-a'}
        for candidate in ('campaign-a-sibling', 'campaign-a-brand2', 'campaign-b'):
            self.post(self.buyer, '/api/session/context', {'campaign_id': candidate}, 403)
        self.assertEqual(self.buyer.get('/api/campaign').json()['revision'], 2)
        self.assertEqual(self.other.get('/api/campaign').json()['revision'], 1)
        self.post(self.buyer, '/api/campaign/approve', {**args, 'actor_id': 'gp-reviewer-a'}, 400)
        self.assertIsNone(self.buyer.get('/api/campaign/package?revision=2').json()['approval'])

    def test_csrf_origin_session_cookie_and_local_token_boundary(self):
        c = self.enterContext(TestClient(self.app.staff, base_url=self.app.staff_origin))
        self.assertEqual(c.get('/api/campaign', headers={'X-Local-Operator': 'anything'}).status_code, 401)
        self.assertEqual(self.buyer.post('/api/campaign', json={}, headers={'X-CSRF-Token': ''}).status_code, 403)
        self.assertEqual(self.buyer.post('/api/campaign', json={}, headers={'Origin': self.app.viewer_origin}).status_code, 403)
        self.assertEqual(self.buyer.get('/api/campaign', headers={'Sec-Fetch-Site': 'same-site'}).status_code, 403)
        self.assertEqual(self.buyer.get('/api/campaign', headers={'Host': 'attacker.test'}).status_code, 403)
        cookie = self.buyer.cookies.get(self.app.cookie)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertNotEqual(db.execute('SELECT token_hash FROM staff_sessions LIMIT 1').fetchone()[0], cookie)
        self.post(self.buyer, '/api/session/end', {})
        self.assertEqual(self.buyer.get('/api/campaign').status_code, 401)

    def test_logout_remains_possible_during_an_authority_outage(self):
        self.authority.unavailable = True
        self.post(self.buyer, '/api/session/end', {})
        self.authority.unavailable = False
        self.assertEqual(self.buyer.get('/api/campaign').status_code, 401)

    def test_permission_and_draft_mandate_are_independent_and_denied_setup_does_not_dispatch(self):
        config = self.buyer.get('/api/mode').json()
        operation = uuid4().hex
        self.post(self.buyer, '/api/agent/placements', dict(request='Prepare a YouTube test for ElevenLabs Text to Speech.',
            model='simulated', session_id=uuid4().hex, run_id=operation,
            catalog_id=config['agentPlanner']['catalogs'][0]['id']))
        for _ in range(4):
            result = self.post(self.buyer, '/api/agent/run', {'run_id': operation})
            if result['status'] != 'running':
                break
        self.assertEqual(self.buyer.get('/api/campaign').json()['revision'], 1)
        args = self.prepare()
        self.post(self.reviewer, '/api/campaign/approve', args)
        self.post(self.reviewer, '/api/campaign/export', args)
        plan = self.post(self.reviewer, '/api/campaign/setup/validate', args)
        from campaign_agent.adapters.simulated_setup import SimulatedCampaignSetup
        with patch.object(SimulatedCampaignSetup, 'create_paused') as dispatch:
            self.post(self.buyer, '/api/campaign/setup/create', {**args, 'setup_id': plan['id']}, 403)
            dispatch.assert_not_called()

    def test_access_approval_required_is_a_denial_and_delay_cannot_extend_a_decision(self):
        self.authority.result_filter = lambda r: {**r, 'outcome': 'approval_required', 'reason': 'approval_required',
                    'valid_for_ms': 0, 'obligations': ['access.human_approval.v1']}
        self.assertEqual(self.buyer.get('/api/campaign').status_code, 403)
        self.authority.result_filter = lambda r: r
        ticks = [0.0]
        access = GateplaneAccess(self.path, self.app.sessions, self.buyer.cookies.get(self.app.cookie),
            self.authority, application_id='youtube', command={'path': '/api/campaign'}, monotonic_clock=lambda: ticks[0])
        decide = self.authority.decide
        def delayed(wire):
            response = decide(wire)
            ticks[0] += 5.001
            return response
        with patch.object(self.authority, 'decide', side_effect=delayed), self.assertRaises(AccessUnavailable):
            access.decide(AccessRequest('gp-buyer-a','tenant-a','brand','workspace-a','install-a',
                                       'youtube:campaign.read','campaign-a'))
        from campaign_agent.adapters import gateplane
        native = gateplane.native_campaign
        decision_returned = [False]
        ticks[0] = 0.0
        def issued(wire):
            response = decide(wire)
            decision_returned[0] = True
            return response
        def slow_native_check(*args):
            result = native(*args)
            if decision_returned[0]:
                ticks[0] += 5.001
            return result
        with patch.object(self.authority, 'decide', side_effect=issued), \
                patch.object(gateplane, 'native_campaign', side_effect=slow_native_check), self.assertRaises(AccessUnavailable):
            access.decide(AccessRequest('gp-buyer-a','tenant-a','brand','workspace-a','install-a',
                                       'youtube:campaign.read','campaign-a'))

    def test_wrong_identity_profile_and_revocation_do_not_allow_private_reads(self):
        token = self.authority.references['credential-buyer-a']
        original = self.authority.identities[token]
        changes = [dict(issuer='https://other.test/realm'), dict(audiences=frozenset({'other-api'})),
                   dict(client_id='another-client'), dict(kind='service'), dict(token_type='id_token'),
                   dict(expires_at=time()-1), dict(session_id='changed-session'), dict(active=False)]
        for change in changes:
            with self.subTest(change=change):
                self.authority.identities[token] = replace(original, **change)
                self.assertEqual(self.buyer.get('/api/campaign').status_code, 401)
        self.authority.identities[token] = original
        self.authority.unavailable = True
        self.assertEqual(self.buyer.get('/api/campaign').status_code, 503)
        self.authority.unavailable = False
        self.authority.revoked.add('buyer-a')
        self.assertEqual(self.buyer.get('/api/campaign').status_code, 401)

    def test_decisions_are_current_exact_and_cannot_elevate_an_app_or_actor(self):
        mutations = [lambda r: {**r, 'application_id': 'acquisition'},
            lambda r: {**r, 'actor': {**r['actor'], 'principal_id': 'gp-reviewer-a'}},
            lambda r: {**r, 'tenant_id': 'tenant-b'}, lambda r: {**r, 'workspace_id': 'workspace-b'},
            lambda r: {**r, 'input_hash': 'sha256:'+'0'*64},
            lambda r: {**r, 'subject_hash': 'sha256:'+'0'*64},
            lambda r: {**r, 'target': {**r['target'], 'id': 'campaign-b'}},
            lambda r: {**r, 'valid_until': timestamp(time()-1)},
            lambda r: {**r, 'obligations': ['product.reserve_budget.v1']},
            lambda r: {**r, 'obligations': ['unknown.obligation.v1']}, lambda r: {**r, 'schema_version': 2}]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.authority.result_filter = mutate
                self.assertEqual(self.buyer.get('/api/campaign').status_code, 503)
        self.authority.result_filter = lambda r: r
        self.assertEqual(self.buyer.get('/api/campaign').status_code, 200)
        self.authority.permissions['buyer-a'].remove('youtube:campaign.read')
        self.assertEqual(self.buyer.get('/api/campaign').status_code, 403)

    def test_public_links_have_no_staff_or_arbitrary_asset_authority_even_during_outage(self):
        args = self.prepare()
        self.post(self.reviewer, '/api/campaign/approve', args)
        links = self.post(self.reviewer, '/api/campaign/export', args)['public_comparisons']
        token = links[0]['path'].split('attribution=')[1]
        self.authority.unavailable = True
        self.assertEqual(self.public.get(links[0]['path']).status_code, 200)
        for path in ('/api/campaign', '/api/session', '/api/config', '/api/agent/conversations',
                     '/viewer/media/editing-voiceover-v1/editing-comparison-v1/a', '/published/'+token+'/../../README.md'):
            self.assertEqual(self.public.get(path, headers={'Cookie': self.app.cookie + '=' + self.buyer.cookies.get(self.app.cookie)}).status_code, 404)
        self.assertEqual(self.public.get('/viewer?ad=editing-voiceover-v1').status_code, 404)
        opened = self.public.post('/api/viewer/open', json={'attribution': token, 'visit_id': None}, headers={'Origin': self.app.viewer_origin})
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(self.buyer.get('/api/campaign').status_code, 503)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE public_comparisons SET active=0 WHERE id=?', (token,))
        self.assertEqual(self.public.get(links[0]['path']).status_code, 404)
        self.assertEqual(self.public.get(opened.json()['example']['takes'][0]['url']).status_code, 404)

    def test_expired_or_revoked_publications_fail_export_atomically_with_recovery_guidance(self):
        args = self.prepare()
        self.post(self.reviewer, '/api/campaign/approve', args)
        links = self.post(self.reviewer, '/api/campaign/export', args)['public_comparisons']
        self.assertEqual(len(links), 2)
        # An acknowledged export retry keeps the existing live destinations.
        self.assertEqual(self.post(self.reviewer, '/api/campaign/export', args)['public_comparisons'], links)
        with closing(sqlite3.connect(self.path)) as db:
            original = db.execute('SELECT * FROM public_comparisons ORDER BY id').fetchall()
        token = links[0]['path'].split('attribution=')[1]
        for unavailable, missing_sibling in (('expired', False), ('revoked', False), ('expired', True), ('revoked', True)):
            with self.subTest(unavailable=unavailable, missing_sibling=missing_sibling):
                with closing(sqlite3.connect(self.path)) as db, db:
                    db.execute('DELETE FROM public_comparisons')
                    db.executemany('INSERT INTO public_comparisons VALUES(?,?,?,?,?,?,?,?,?,?)', original)
                    if unavailable == 'revoked':
                        db.execute('UPDATE public_comparisons SET active=0 WHERE id=?', (token,))
                    if missing_sibling:
                        # A missing sibling must not be published when this package export fails.
                        db.execute('DELETE FROM public_comparisons WHERE id<>?', (token,))
                    before = db.execute('SELECT * FROM public_comparisons').fetchall()
                self.app.publications.clock = (lambda: max(row[8] for row in original)) if unavailable == 'expired' else time
                self.assertEqual(self.public.get(links[0]['path']).status_code, 404)
                for _ in range(2):
                    failed = self.post(self.reviewer, '/api/campaign/export', args, 409)
                    self.assertIn('new package revision', failed['error'])
                    self.assertIn('renewal', failed['error'])
                failed_setup = self.post(self.reviewer, '/api/campaign/setup/validate', args, 409)
                self.assertIn('new package revision', failed_setup['error'])
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(db.execute('SELECT * FROM public_comparisons').fetchall(), before)

    def test_validated_setup_rechecks_public_destinations_before_dispatch(self):
        from campaign_agent.adapters.simulated_setup import SimulatedCampaignSetup
        args = self.prepare()
        self.post(self.reviewer, '/api/campaign/approve', args)
        self.post(self.reviewer, '/api/campaign/export', args)
        plan = self.post(self.reviewer, '/api/campaign/setup/validate', args)
        with closing(sqlite3.connect(self.path)) as db:
            snapshot = db.execute('SELECT snapshot FROM campaign_setups').fetchone()[0]
            publications = db.execute('SELECT * FROM public_comparisons').fetchall()
            expiry = max(row[8] for row in publications)
        decide = self.authority.decide
        create = SimulatedCampaignSetup.create_paused
        for timing, unavailable in (('after_validation', 'expired'), ('after_validation', 'revoked'),
                                    ('after_validation', 'replaced'), ('after_reservation', 'expired'),
                                    ('after_reservation', 'revoked'), ('after_reservation', 'replaced')):
            with self.subTest(timing=timing, unavailable=unavailable):
                self.app.publications.clock = time
                with closing(sqlite3.connect(self.path)) as db, db:
                    db.execute('UPDATE campaign_setups SET snapshot=?', (snapshot,))
                    db.execute('DELETE FROM public_comparisons')
                    db.executemany('INSERT INTO public_comparisons VALUES(?,?,?,?,?,?,?,?,?,?)', publications)
                    db.execute('DELETE FROM simulated_campaigns')
                invalidated = []
                def invalidate():
                    invalidated.append(True)
                    if unavailable == 'expired':
                        self.app.publications.clock = lambda: expiry
                    else:
                        with closing(sqlite3.connect(self.path)) as db, db:
                            if unavailable == 'revoked':
                                db.execute('UPDATE public_comparisons SET active=0')
                            else:
                                db.execute("UPDATE public_comparisons SET id=? WHERE creative_ref='editing-voiceover-v1'", (uuid4().hex + 'replacement',))
                def current_decision(wire):
                    # Simulate expiry/revocation while the final access check is in flight,
                    # after the creation reservation has committed but before dispatch.
                    with closing(sqlite3.connect(self.path)) as db:
                        creating = db.execute("SELECT 1 FROM campaign_setups WHERE json_extract(snapshot, '$.status')='creating'").fetchone()
                    if creating and not invalidated:
                        invalidate()
                    return decide(wire)
                if timing == 'after_validation':
                    invalidate()
                    failed = self.post(self.reviewer, '/api/campaign/setup/validate', args, 409)
                    self.assertIn('new package revision', failed['error'])
                else:
                    self.assertEqual(self.post(self.reviewer, '/api/campaign/setup/validate', args), plan)
                with patch.object(self.authority, 'decide', side_effect=current_decision), \
                        patch.object(SimulatedCampaignSetup, 'create_paused', autospec=True, side_effect=create) as dispatch:
                    failed = self.post(self.reviewer, '/api/campaign/setup/create', {**args, 'setup_id': plan['id']}, 409)
                    self.assertIn('new package revision', failed['error'])
                    dispatch.assert_not_called()
                self.assertTrue(invalidated)
                saved = self.reviewer.get('/api/campaign/setup', params={k: args[k] for k in ('revision', 'fingerprint')}).json()
                self.assertEqual(saved, plan)
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM simulated_campaigns').fetchone()[0], 0)

    def test_publication_expiry_during_provider_validation_cannot_save_a_validated_setup(self):
        from campaign_agent.adapters.simulated_setup import SimulatedCampaignSetup
        args = self.prepare()
        self.post(self.reviewer, '/api/campaign/approve', args)
        self.post(self.reviewer, '/api/campaign/export', args)
        with closing(sqlite3.connect(self.path)) as db:
            expiry = db.execute('SELECT MAX(expires_at) FROM public_comparisons').fetchone()[0]
        validate = SimulatedCampaignSetup.validate
        def expires_during_validation(provider, plan):
            validate(provider, plan)
            self.app.publications.clock = lambda: expiry
        for local in (True, False):
            with self.subTest(local_validation=local):
                self.app.publications.clock = time
                with patch.object(SimulatedCampaignSetup, 'local_validation', local), \
                        patch.object(SimulatedCampaignSetup, 'validate', autospec=True, side_effect=expires_during_validation):
                    failed = self.post(self.reviewer, '/api/campaign/setup/validate', args, 409)
                self.assertIn('new package revision', failed['error'])
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM campaign_setups').fetchone()[0], 0)

    def test_expiry_after_dispatch_preserves_receipt_recovery_without_redispatch(self):
        from campaign_agent.adapters.simulated_setup import SimulatedCampaignSetup
        from campaign_agent.campaign_setup import SetupProviderError
        args = self.prepare()
        self.post(self.reviewer, '/api/campaign/approve', args)
        self.post(self.reviewer, '/api/campaign/export', args)
        plan = self.post(self.reviewer, '/api/campaign/setup/validate', args)
        with closing(sqlite3.connect(self.path)) as db:
            expiry = db.execute('SELECT MAX(expires_at) FROM public_comparisons').fetchone()[0]
        create = SimulatedCampaignSetup.create_paused
        def lose_response(provider, operation, configuration):
            create(provider, operation, configuration)
            self.app.publications.clock = lambda: expiry
            raise SetupProviderError('Synthetic receipt loss after dispatch')
        with patch.object(SimulatedCampaignSetup, 'create_paused', autospec=True, side_effect=lose_response) as dispatch:
            unknown = self.post(self.reviewer, '/api/campaign/setup/create', {**args, 'setup_id': plan['id']})
            self.assertEqual(unknown['status'], 'unknown')
            self.assertEqual(self.post(self.reviewer, '/api/campaign/setup/create', {**args, 'setup_id': plan['id']}), unknown)
            recovered = self.post(self.reviewer, '/api/campaign/setup/reconcile', {**args, 'setup_id': plan['id']})
            self.assertEqual(recovered['status'], 'verified')
            self.assertEqual(recovered['plan'], plan['plan'])
            dispatch.assert_called_once()

    def test_unknown_or_mismatched_context_and_request_payload_are_rejected(self):
        for field, value in (('application_id', 'other-app'), ('installation_id', 'install-b'), ('workspace_id', 'workspace-b')):
            self.authority.context_filter = lambda r, field=field, value=value: {**r, field: value}
            self.assertEqual(self.buyer.get('/api/campaign').status_code, 503)
        self.authority.context_filter = lambda r: r
        response = self.buyer.post('/api/campaign', content='{"revision":1,"revision":2}', headers={'Content-Type':'application/json'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.buyer.post('/api/campaign', content='x'*800001, headers={'Content-Type':'application/json'}).status_code, 413)

    def test_synthetic_login_cannot_be_exposed_by_a_hosted_configuration(self):
        with self.assertRaisesRegex(ValueError, 'loopback'):
            HostedApplication(self.path, self.app.sessions, self.authority, self.app.assets,
                staff_origin='https://staff.example.test', viewer_origin='https://viewer.example.test', fixture_login=self.authority)
        hosted = HostedApplication(self.path, self.app.sessions, self.authority, self.app.assets,
                staff_origin='https://staff.example.test', viewer_origin='https://viewer.example.test')
        client = self.enterContext(TestClient(hosted.staff, base_url='https://staff.example.test'))
        self.assertEqual(client.post('/fixture', json={'profile':'reviewer-a'},
                                     headers={'Origin':'https://staff.example.test'}).status_code, 401)
        self.assertEqual(client.get('/api/campaign', headers={'Cookie': self.app.cookie+'='+self.buyer.cookies.get(self.app.cookie)}).status_code, 401)

    def test_restart_retains_native_state_but_requires_new_fixture_sign_in(self):
        self.prepare()
        old_token = self.buyer.cookies.get(self.app.cookie)
        reopened = offline_fixture(self.path)
        client = self.enterContext(TestClient(reopened.staff, base_url=reopened.staff_origin))
        client.cookies.set(reopened.cookie, old_token)
        self.assertEqual(client.get('/api/campaign').status_code, 401)
        response = client.post('/fixture', json={'profile':'buyer-a'}, headers={'Origin':reopened.staff_origin})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get('/api/campaign').json()['revision'], 2)

    def test_fixture_bootstrap_refuses_existing_nonfixture_product_data(self):
        other = self.path.parent / 'customer.sqlite3'
        with closing(sqlite3.connect(other)) as db, db:
            db.execute('CREATE TABLE customer_notes(note TEXT)')
            db.execute("INSERT INTO customer_notes VALUES('preserve')")
        with self.assertRaisesRegex(ValueError, 'fresh database'):
            offline_fixture(other)
        with closing(sqlite3.connect(other)) as db:
            self.assertEqual(db.execute('SELECT note FROM customer_notes').fetchall(), [('preserve',)])
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='campaign_owners'").fetchone())
