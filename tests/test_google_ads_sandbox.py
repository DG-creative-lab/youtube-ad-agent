from contextlib import closing
import sqlite3
import unittest

from campaign_agent.adapters.google_ads_sandbox import GoogleAdsSandbox
from campaign_agent.adapters.simulated_setup import SimulatedCampaignSetup
from campaign_agent.campaign_setup import CampaignSetup, SetupProviderError
from scripts.campaign_drafts import PackageConflict
import test_placement_planner as fixtures


MANAGER = '1111111111'
ACCOUNT = '2222222222'
TARGETS = ('EDIT_TARGET', 'BOOK_TARGET')
CREATIVE_VIDEOS = ('EDIT_AD0001', 'BOOK_AD0001')
CONTEXTS = ('video-editing', 'audiobook')
GROUP_NAMES = ('Video editing', 'Audiobook production')
LOGO = b'\x89PNG\r\n\x1a\nfixture'


class GoogleAdsSandboxTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.PlacementPlannerTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.drafts = self.case.runtime.drafts
        self.native_campaign = None
        self.mutations = []
        self.test_account = True
        self.manager_currency = 'GBP'
        self.client_currency = 'GBP'
        self.lose_receipt = False
        self.swap_targets = False
        self.edit_during_validation = False
        catalog = self.case.runtime.planner.catalogs.register('Approved test metadata', [
            {**row, 'video_id': target, 'source': 'creator_supplied', 'source_reference': 'Authored test fixture'}
            for row, target in zip(fixtures.CATALOG, TARGETS)
        ])
        self.case.finish(self.case.start(catalog=catalog))
        review = self.drafts.review_package(self.drafts.campaign_id, 2)
        self.reference = self.drafts.campaign_id, 2, review['fingerprint']
        self.drafts.approve_package(*self.reference)
        self.creatives = {
            group['creative_version']: {'video_id': video, 'destination': f'https://example.com/{context}',
                                        'headline': 'Sandbox video ad', 'long_headline': 'Sandbox validation video',
                                        'description': 'Test setup'}
            for group, video, context in zip(review['package']['groups'], CREATIVE_VIDEOS, CONTEXTS)
        }
        self.provider = GoogleAdsSandbox(MANAGER, ACCOUNT, self.creatives, LOGO, self.post)
        self.setup = CampaignSetup(self.drafts, self.provider)

    def post(self, account, endpoint, body):
        if endpoint == 'googleAds:mutate':
            self.assertEqual(account, ACCOUNT)
            self.mutations.append(body)
            if body['validateOnly']:
                if self.edit_during_validation:
                    self.edit_draft()
                return {}, 'validate-fixture'
            self.native_campaign = body['mutateOperations'][1]['campaignOperation']['create']['name']
            if self.lose_receipt:
                raise SetupProviderError('Lost the creation response')
            results = [{} for _ in body['mutateOperations']]
            results[1] = {'campaignResult': {'resourceName': f'customers/{ACCOUNT}/campaigns/101'}}
            return {'mutateOperationResponses': results}, 'create-fixture'
        self.assertEqual(endpoint, 'googleAds:searchStream')
        query = body['query']
        if 'FROM customer_client ' in query:
            self.assertEqual(account, MANAGER)
            rows = [{'customerClient': {'id': ACCOUNT, 'level': '1', 'testAccount': True}}]
        elif query.endswith('FROM customer'):
            rows = [{'customer': {'id': account, 'testAccount': self.test_account, 'manager': account == MANAGER,
                                  'currencyCode': self.manager_currency if account == MANAGER else self.client_currency}}]
        else:
            self.assertEqual(account, ACCOUNT)
            rows = self.campaign_rows(query)
        return [{'results': rows}], 'read-fixture'

    def campaign_rows(self, query):
        if 'FROM campaign ' in query:
            if self.native_campaign is None:
                return []
            self.assertIn(self.native_campaign, query)
            return [{'campaign': {'id': '101', 'name': self.native_campaign, 'status': 'PAUSED',
                                  'advertisingChannelType': 'DEMAND_GEN'},
                     'campaignBudget': {'amountMicros': '10000000'}, 'customer': {'currencyCode': 'GBP'}}]
        if 'FROM ad_group ' in query:
            return [{'adGroup': {'id': str(index), 'name': name, 'status': 'ENABLED',
                                 'demandGenAdGroupSettings': {'channelControls': {
                                     'selectedChannels': {'youtubeInStream': True, 'youtubeShorts': False},
                                 }}}} for index, name in enumerate(GROUP_NAMES, 201)]
        if 'FROM ad_group_ad ' in query:
            return [
                {'adGroup': {'id': str(index)}, 'adGroupAd': {'status': 'ENABLED', 'ad': {
                    'id': str(index + 100), 'finalUrls': [f'https://example.com/{context}'],
                    'demandGenVideoResponsiveAd': {
                        'videos': [{'asset': f'customers/{ACCOUNT}/assets/{index + 200}'}],
                        'logoImages': [{'asset': f'customers/{ACCOUNT}/assets/500'}],
                        'businessName': {'text': 'Campaign Setup Sandbox'},
                        'headlines': [{'text': 'Sandbox video ad'}], 'longHeadlines': [{'text': 'Sandbox validation video'}],
                        'descriptions': [{'text': 'Test setup'}],
                    },
                }}} for index, context in enumerate(CONTEXTS, 201)
            ]
        if 'FROM ad_group_criterion ' in query:
            placements = reversed(TARGETS) if self.swap_targets else TARGETS
            return [{'adGroup': {'id': str(index)}, 'adGroupCriterion': {'type': 'YOUTUBE_VIDEO', 'status': 'ENABLED',
                                                                       'youtubeVideo': {'videoId': video}}}
                    for index, video in enumerate(placements, 201)]
        if 'FROM asset ' in query:
            logo_name = self.mutations[0]['mutateOperations'][2]['assetOperation']['create']['name']
            return [{'asset': {'resourceName': f'customers/{ACCOUNT}/assets/500', 'name': logo_name, 'type': 'IMAGE'}},
                    *[{'asset': {'resourceName': f'customers/{ACCOUNT}/assets/{index}', 'type': 'YOUTUBE_VIDEO',
                                 'youtubeVideoAsset': {'youtubeVideoId': video}}}
                      for index, video in enumerate(CREATIVE_VIDEOS, 401)]]
        self.fail('Unexpected GAQL query: ' + query)

    def edit_draft(self):
        current = self.drafts.read()
        self.drafts.save({'campaign_id': current['campaign_id'], 'revision': current['revision'],
                          'placements': current['placements'][:1]})

    def test_approves_the_validated_payload_and_reads_back_both_groups(self):
        self.manager_currency = 'USD'
        preview = self.setup.validate(*self.reference)
        self.assertEqual(preview['validation_request_id'], 'validate-fixture')
        self.assertIsNone(self.case.runtime.setup.read(*self.reference))
        self.assertIsNone(preview['approval'])
        self.assertIsNone(self.native_campaign)
        self.assertEqual(len(self.mutations), 1)
        with self.assertRaises(PackageConflict):
            self.setup.create(*self.reference, '0' * 64)
        verified = self.setup.create(*self.reference, preview['id'])
        self.assertEqual(verified['status'], 'verified')
        self.assertEqual([row['ad_id'] for row in verified['readback']['groups']], ['301', '302'])
        validation, creation = self.mutations
        self.assertEqual(validation, {**creation, 'validateOnly': True})
        self.assertIs(creation['validateOnly'], False)
        self.assertIs(creation['partialFailure'], False)
        operations = creation['mutateOperations']
        self.assertEqual(operations[1]['campaignOperation']['create']['status'], 'PAUSED')
        placements = [op['adGroupCriterionOperation']['create'] for op in operations if 'adGroupCriterionOperation' in op]
        self.assertEqual([(row['adGroup'].rsplit('/', 1)[-1], row['youtubeVideo']['videoId'], row['negative'])
                          for row in placements], [('-4', TARGETS[0], False), ('-6', TARGETS[1], False)])
        self.assertEqual(self.setup.create(*self.reference, preview['id']), verified)
        self.assertEqual(len(self.mutations), 2)

    def test_migrates_existing_setup_and_keeps_provider_accounts_separate(self):
        simulator = self.case.runtime.setup
        preview = simulator.validate(*self.reference)
        verified = simulator.create(*self.reference, preview['id'])
        self.assertEqual(verified['status'], 'verified')

        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute('ALTER TABLE campaign_setups RENAME TO setup_fixture')
            db.execute('''CREATE TABLE campaign_setups (
                client_id TEXT NOT NULL, brand_id TEXT NOT NULL, campaign_id TEXT NOT NULL,
                revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, snapshot TEXT NOT NULL,
                PRIMARY KEY (client_id, brand_id, campaign_id, revision, fingerprint)
            )''')
            db.execute('''INSERT INTO campaign_setups
                          SELECT client_id, brand_id, campaign_id, revision, fingerprint, snapshot FROM setup_fixture''')
            db.execute('DROP TABLE setup_fixture')

        sandbox = CampaignSetup(self.drafts, self.provider)
        self.assertIsNone(sandbox.read(*self.reference))
        sandbox_preview = sandbox.validate(*self.reference)
        self.assertEqual(sandbox.read(*self.reference), sandbox_preview)
        with self.assertRaises(PackageConflict):
            sandbox.create(*self.reference, verified['id'])
        self.assertEqual(len(self.mutations), 1)

        other_provider = SimulatedCampaignSetup(self.drafts.path)
        other_provider.account_id = 'other-offline-account'
        other_setup = CampaignSetup(self.drafts, other_provider)
        self.assertIsNone(other_setup.read(*self.reference))
        other_preview = other_setup.validate(*self.reference)
        self.assertNotEqual(other_preview['id'], verified['id'])
        with self.assertRaises(PackageConflict):
            other_setup.create(*self.reference, verified['id'])
        self.assertEqual(other_setup.read(*self.reference), other_preview)
        self.assertEqual(simulator.create(*self.reference, verified['id']), verified)

    def test_target_account_must_use_gbp(self):
        self.client_currency = 'USD'
        with self.assertRaisesRegex(SetupProviderError, 'GBP'):
            self.setup.validate(*self.reference)
        self.assertEqual(self.mutations, [])
        self.assertIsNone(self.setup.read(*self.reference))

    def test_lost_receipt_recovers_by_name_and_detects_swapped_placements(self):
        preview = self.setup.validate(*self.reference)
        self.lose_receipt = True
        self.assertEqual(self.setup.create(*self.reference, preview['id'])['status'], 'unknown')
        reopened = CampaignSetup(self.case.reopen().drafts, self.provider)
        self.swap_targets = True
        observed = reopened.reconcile(*self.reference, preview['id'])
        self.assertEqual(observed['status'], 'mismatch')
        self.assertEqual(observed['readback']['campaign_id'], '101')
        self.assertEqual([group['placements'] for group in observed['readback']['configuration']['groups']],
                         [[TARGETS[1]], [TARGETS[0]]])
        self.assertEqual(len(self.mutations), 2)

    def test_test_account_flag_is_required_at_validation_and_dispatch(self):
        self.test_account = False
        with self.assertRaisesRegex(SetupProviderError, 'test account'):
            self.setup.validate(*self.reference)
        self.assertEqual(self.mutations, [])
        self.assertIsNone(self.setup.read(*self.reference))
        self.test_account = True
        preview = self.setup.validate(*self.reference)
        self.test_account = False
        self.assertEqual(self.setup.create(*self.reference, preview['id'])['status'], 'unknown')
        self.assertEqual(len(self.mutations), 1)
        self.assertIs(self.mutations[0]['validateOnly'], True)

    def test_edit_during_remote_validation_prevents_approval(self):
        self.edit_during_validation = True
        with self.assertRaisesRegex(PackageConflict, 'package has changed'):
            self.setup.validate(*self.reference)
        self.assertIsNone(self.setup.read(*self.reference))
        self.assertEqual(len(self.mutations), 1)
        self.assertIs(self.mutations[0]['validateOnly'], True)
