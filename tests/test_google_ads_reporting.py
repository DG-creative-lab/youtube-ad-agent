from contextlib import nullcontext
import unittest
from unittest.mock import Mock
from uuid import uuid4

from campaign_agent.adapters.google_ads_reporting import GoogleAdsReporting
from campaign_agent.campaign_setup import SetupProviderError
from scripts.campaign_drafts import PackageConflict
import test_google_ads_sandbox as fixtures


GROUPS = ('201', '202')
CAMPAIGN = '101'
REQUEST = 'Review Google Ads delivery'


def row(group, impressions, placement=None):
    result = {'campaign': {'id': CAMPAIGN}, 'adGroup': {'id': group},
              'metrics': {'impressions': str(impressions), 'costMicros': '1000'}}
    if placement is not None:
        result['detailPlacementView'] = {'placement': placement, 'placementType': 'YOUTUBE_VIDEO'}
    return result


class GoogleAdsReportingTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = fixtures.GoogleAdsSandboxTests()
        self.sandbox.setUp()
        self.addCleanup(self.sandbox.doCleanups)
        self.reference = self.sandbox.reference
        self.totals, self.placements = [], []
        self.test_account = True
        self.after_fetch = None
        self.transport = Mock(side_effect=self.post)
        self.reporting = GoogleAdsReporting(fixtures.MANAGER, fixtures.ACCOUNT, lambda: nullcontext(self.transport))
        self.runtime = self.sandbox.case.reopen(reporting=self.reporting)
        self.delivery = self.runtime.delivery

    def verify_setup(self):
        plan = self.sandbox.setup.validate(*self.reference)
        verified = self.sandbox.setup.create(*self.reference, plan['id'])
        self.assertEqual(verified['status'], 'verified')
        return verified

    def post(self, account, endpoint, body):
        self.assertEqual(endpoint, 'googleAds:searchStream')
        query = body['query']
        if query.endswith('FROM customer') or 'FROM customer_client ' in query:
            self.sandbox.test_account = self.test_account
            return self.sandbox.post(account, endpoint, body)
        self.assertEqual(account, fixtures.ACCOUNT)
        self.assertIn('WHERE campaign.id = 101 AND ad_group.id IN (201, 202)', query)
        self.assertIn('segments.date BETWEEN', query)
        if 'FROM ad_group WHERE' in query:
            return [{'results': self.totals}], 'fixture'
        self.assertIn('FROM detail_placement_view WHERE', query)
        if self.after_fetch:
            self.after_fetch()
        if isinstance(self.placements, Exception):
            raise self.placements
        return [{'results': self.placements}], 'fixture'

    def test_preserves_configured_targets_and_coverage_of_observed_delivery(self):
        verified = self.verify_setup()
        self.assertIsNone(self.delivery.read(*self.reference)['report'])
        self.transport.assert_not_called()
        self.totals = [row('201', 10), row('202', 2)]
        self.placements = [row('201', 10, 'OTHER_VIDEO'), row('202', 2, fixtures.TARGETS[1])]
        complete = self.delivery.review(*self.reference)
        self.assertEqual((complete['coverage'], complete['placement_coverage']), ('complete', 'complete'))
        self.assertEqual(complete['binding']['setup_id'], verified['id'])
        self.assertEqual(complete['groups'][0]['configured_videos'], [fixtures.TARGETS[0]])
        self.assertEqual(complete['placements'][0]['placement'], 'OTHER_VIDEO')
        self.assertEqual(complete['groups'][0]['metrics'], {'impressions': 10, 'clicks': 0, 'cost_micros': 1000})

        self.totals = [row('201', 10)]
        self.placements = [row('201', 10, 'Other')]
        partial = self.delivery.review(*self.reference)
        self.assertEqual((partial['coverage'], partial['placement_coverage']), ('partial', 'partial'))
        self.assertIsNone(partial['groups'][1]['metrics'])
        self.assertEqual(partial['placements'][0]['kind'], 'other')
        self.assertEqual(self.sandbox.case.reopen(reporting=self.reporting).delivery.read(*self.reference)['report'], partial)

        self.placements = SetupProviderError('Fixture placement view unavailable')
        unavailable = self.delivery.review(*self.reference)
        self.assertEqual((unavailable['coverage'], unavailable['placement_coverage']), ('partial', 'unavailable'))
        self.assertEqual(unavailable['groups'][0]['metrics']['impressions'], 10)

    def test_chat_waits_on_empty_report_and_persists_the_same_workspace_snapshot(self):
        self.verify_setup()
        case = self.sandbox.case
        simulator = Mock()
        runtime = case.reopen(reporting=self.reporting, planner_simulator=simulator)
        session = uuid4().hex
        run = runtime.planner.start('Please review Google Ads delivery for this campaign.',
                                    'simulated', session, uuid4().hex, case.catalog,
                                    draft_permission='instruction_test')
        result = case.finish(run, runtime)
        report = runtime.delivery.read(*self.reference)['report']
        self.assertEqual([step['tool'] for step in result['steps']], ['review_google_ads_delivery'])
        self.assertEqual(result['result']['delivery_report_id'], report['id'])
        self.assertEqual((report['coverage'], report['placement_coverage']), ('empty', 'empty'))
        self.assertTrue(all(group['metrics'] is None for group in report['groups']))
        chat = runtime.planner.conversations.read(session)
        self.assertIn('No delivery data is available for this test campaign', chat['messages'][-1]['content'])
        self.totals = [{'campaign': {'id': CAMPAIGN}, 'adGroup': {'id': group}} for group in GROUPS]
        second = runtime.planner.start('Could you show me the placement report for the current campaign in Google Ads?',
                                       'simulated', session, uuid4().hex, case.catalog,
                                       after_message=chat['latest_message'])
        result = case.finish(second, runtime)
        report = runtime.delivery.read(*self.reference)['report']
        self.assertEqual((report['coverage'], report['placement_coverage']), ('complete', 'empty'))
        self.assertFalse(report['has_delivery'])
        self.assertIn('zero impressions, clicks and spend', result['result']['message'])
        self.assertIn('Wait for delivery evidence', result['result']['message'])
        simulator.next_turn.assert_not_called()
        self.assertEqual(runtime.drafts.read()['revision'], 2)

    def test_requires_verified_setup_and_rechecks_package_after_provider_reads(self):
        with self.assertRaises(PackageConflict):
            self.delivery.review(*self.reference)
        self.transport.assert_not_called()

        self.verify_setup()
        self.test_account = False
        self.assertEqual(self.delivery.review(*self.reference)['coverage'], 'unavailable')
        self.assertTrue(all(call.args[2]['query'].endswith('FROM customer') for call in self.transport.call_args_list))
        self.transport.reset_mock()
        self.test_account = True
        wrong_account = GoogleAdsReporting(fixtures.MANAGER, '3333333333', lambda: nullcontext(self.transport))
        with self.assertRaises(PackageConflict):
            self.sandbox.case.reopen(reporting=wrong_account).delivery.review(*self.reference)
        self.transport.assert_not_called()

        self.after_fetch = self.sandbox.edit_draft
        with self.assertRaisesRegex(PackageConflict, 'package has changed'):
            self.delivery.review(*self.reference)

    def test_offline_chat_reports_unavailable_without_using_sample_delivery(self):
        case = self.sandbox.case
        run = case.runtime.planner.start(REQUEST, 'simulated', uuid4().hex, uuid4().hex, case.catalog)
        result = case.finish(run)
        self.assertEqual(result['status'], 'needs_input')
        self.assertIsNone(result['result']['delivery_report_id'])
        self.assertEqual([step['tool'] for step in result['steps']], ['review_google_ads_delivery'])
        self.transport.assert_not_called()

    def test_chat_reports_only_on_an_explicit_current_campaign_request(self):
        self.verify_setup()
        case = self.sandbox.case
        for request in ('How is this campaign performing in Google Ads?',
                        'Can you check Google Ads performance, please?'):
            with self.subTest(request=request):
                run = self.runtime.planner.start(request, 'simulated', uuid4().hex, uuid4().hex, case.catalog)
                result = case.finish(run, self.runtime)
                self.assertEqual([step['tool'] for step in result['steps']], ['review_google_ads_delivery'])
                self.assertIsNotNone(result['result']['delivery_report_id'])
        self.transport.reset_mock()
        for request in ('Do not review Google Ads delivery.',
                        'What does "Review Google Ads delivery" mean?',
                        'Review Google Ads delivery for campaign 222.',
                        'Review campaign performance only.'):
            with self.subTest(request=request):
                run = self.runtime.planner.start(request, 'simulated', uuid4().hex, uuid4().hex, case.catalog)
                result = case.finish(run, self.runtime)
                self.assertNotIn('review_google_ads_delivery', [step['tool'] for step in result['steps']])
        self.transport.assert_not_called()
