import unittest
from unittest.mock import patch
from uuid import uuid4

from campaign_agent.campaign_setup import SetupProviderError
from scripts.campaign_drafts import PackageConflict
import test_placement_planner as fixtures


class CampaignSetupTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.PlacementPlannerTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.runtime = self.case.runtime
        self.case.finish(self.case.start())
        self.drafts = self.runtime.drafts
        self.setup = self.runtime.setup
        review = self.drafts.review_package(self.drafts.campaign_id, 2)
        self.reference = self.drafts.campaign_id, 2, review['fingerprint']

    def validate(self):
        self.drafts.approve_package(*self.reference)
        return self.setup.validate(*self.reference)

    def test_chat_validates_then_buyer_creates_one_paused_campaign(self):
        with self.assertRaisesRegex(PackageConflict, 'Approve this revision'):
            self.setup.validate(*self.reference)
        self.drafts.approve_package(*self.reference)
        run_id = self.runtime.planner.start('Validate the campaign setup.', 'simulated', self.case.session,
                                            uuid4().hex, self.case.catalog)
        result = self.case.finish(run_id)
        plan = self.setup.read(*self.reference)
        self.assertEqual(result['result']['setup_id'], plan['id'])
        self.assertIsNone(plan['approval'])
        self.assertIsNone(self.setup.provider.readback(plan['id'], plan['plan']))
        self.assertEqual([group['placement_ids'] for group in plan['plan']['groups']], [['SAMPLE00001'], ['SAMPLE00002']])
        with self.assertRaisesRegex(PackageConflict, 'Approve creation'):
            self.setup.reconcile(*self.reference, plan['id'])

        provider = self.setup.provider
        original_create = provider.create_paused
        def overlapping_request(operation_id, configuration):
            duplicate = self.case.reopen().setup.create(*self.reference, plan['id'])
            self.assertEqual(duplicate['status'], 'creating')
            self.assertIsNone(provider.readback(plan['id'], plan['plan']))
            return original_create(operation_id, configuration)

        with patch.object(provider, 'create_paused', side_effect=overlapping_request) as create:
            verified = self.setup.create(*self.reference, plan['id'])
            create.assert_called_once_with(plan['id'], plan['plan'])
        self.assertEqual(verified['status'], 'verified')
        self.assertEqual(verified['readback']['configuration'], plan['plan'])
        self.assertEqual(verified['readback']['configuration']['status'], 'PAUSED')
        self.assertEqual(verified['approval']['actor_id'], self.runtime.operator.id)
        reopened = self.case.reopen().setup
        with patch.object(reopened.provider, 'create_paused') as create:
            self.assertEqual(reopened.create(*self.reference, plan['id']), verified)
            create.assert_not_called()

    def test_changed_package_or_setup_cannot_reach_provider(self):
        plan = self.validate()
        with patch.object(self.setup.provider, 'create_paused') as create:
            with self.assertRaisesRegex(PackageConflict, 'exact setup'):
                self.setup.create(*self.reference, 'a' * 64)
            draft = self.drafts.read()
            placements = draft['placements'][:1]
            self.drafts.save({'campaign_id': draft['campaign_id'], 'revision': 2, 'placements': placements})
            with self.assertRaisesRegex(PackageConflict, 'package has changed'):
                self.setup.create(*self.reference, plan['id'])
            create.assert_not_called()
        self.assertIsNone(self.setup.read(*self.reference)['approval'])

    def test_demo_delivery_stays_scoped_to_its_scenario_and_separate_from_viewer_counts(self):
        plan = self.validate()
        wait = self.case.reopen(demo_scenario='wait')
        self.assertFalse(wait.delivery.read(*self.reference)['available'])
        blocked_run = wait.planner.start('Review demo delivery.', 'simulated', uuid4().hex, uuid4().hex, self.case.catalog)
        self.setup.create(*self.reference, plan['id'])
        blocked = self.case.finish(blocked_run, wait)
        self.assertEqual(blocked['status'], 'needs_input')
        self.assertEqual(blocked['planner']['delivery_demo_scenario'], 'wait')
        self.assertIsNone(blocked['result']['delivery_report_id'])
        self.assertIsNone(wait.delivery.read(*self.reference)['report'])
        wait_report = wait.delivery.review(*self.reference)
        self.assertEqual(wait.delivery.recommend(*self.reference, wait_report['id'])['kind'], 'wait')

        run = wait.planner.start('Review demo delivery.', 'simulated', uuid4().hex, uuid4().hex, self.case.catalog)
        propose = self.case.reopen(demo_scenario='propose')
        self.assertEqual(self.case.finish(run, propose)['status'], 'needs_input')
        self.assertIsNone(propose.delivery.read(*self.reference)['report'])
        with self.assertRaises(PackageConflict):
            propose.delivery.recommend(*self.reference, wait_report['id'])

        run = propose.planner.start('Review demo delivery.', 'simulated', uuid4().hex, uuid4().hex, self.case.catalog)
        result = self.case.finish(run, propose)
        self.assertEqual(result['planner']['execution'], 'application')
        self.assertEqual(result['planner']['delivery_demo_scenario'], 'propose')
        self.assertEqual(result['planner']['turns'][0]['inference']['mode'], 'application')
        report = propose.delivery.read(*self.reference)['report']
        self.assertEqual(result['result']['delivery_report_id'], report['id'])
        self.assertIn('Authored delivery fixture', result['result']['message'])
        self.assertEqual(report['groups'][0]['fixture_activity'], {'arrivals': 4, 'completions': 1})
        self.assertEqual(report['groups'][0]['viewer_activity'], {'arrivals': 0, 'completions': 0})
        self.assertIsNone(report['groups'][0]['window_activity'])
        recommendation = propose.delivery.recommend(*self.reference, report['id'])
        self.assertEqual(recommendation['kind'], 'comparison_test')
        self.assertIn('authored fixture', recommendation['reason'])
        self.assertIsNone(self.runtime.delivery.read(*self.reference)['report'])
        self.assertEqual(self.case.reopen(demo_scenario='wait').delivery.read(*self.reference)['report'], wait_report)

    def test_lost_creation_receipt_is_resolved_through_readback(self):
        plan = self.validate()
        original_create = self.setup.provider.create_paused
        def lose_receipt(operation_id, configuration):
            original_create(operation_id, configuration)
            raise SetupProviderError('Timed out after creation')

        with patch.object(self.setup.provider, 'create_paused', side_effect=lose_receipt):
            unknown = self.setup.create(*self.reference, plan['id'])
        self.assertEqual(unknown['status'], 'unknown')
        self.assertIsNone(unknown['readback'])
        reopened = self.case.reopen().setup
        with patch.object(reopened.provider, 'create_paused') as create:
            self.assertEqual(reopened.create(*self.reference, plan['id']), unknown)
            observed = reopened.provider.readback(plan['id'], plan['plan'])
            for invalid in ('', '   ', None, 42):
                with self.subTest(campaign_id=invalid):
                    with patch.object(reopened.provider, 'readback', return_value={**observed, 'campaign_id': invalid}):
                        self.assertEqual(reopened.reconcile(*self.reference, plan['id']), unknown)
                    self.assertEqual(reopened.read(*self.reference), unknown)
            for field in ('ad_group_id', 'ad_id'):
                for invalid in ('', '   ', 'two words', 42, None):
                    with self.subTest(field=field, value=invalid):
                        group = dict(observed['groups'][1])
                        if invalid is None:
                            del group[field]
                        else:
                            group[field] = invalid
                        readback = {**observed, 'groups': [observed['groups'][0], group]}
                        with patch.object(reopened.provider, 'readback', return_value=readback):
                            self.assertEqual(reopened.reconcile(*self.reference, plan['id']), unknown)
                        self.assertEqual(reopened.read(*self.reference), unknown)
            verified = reopened.reconcile(*self.reference, plan['id'])
            create.assert_not_called()
        self.assertEqual(verified['status'], 'verified')
        self.assertEqual(verified['readback']['configuration'], plan['plan'])

    def test_readback_with_different_placements_is_not_verified(self):
        plan = self.validate()
        original_readback = self.setup.provider.readback
        def different_placements(operation_id, configuration):
            observed = original_readback(operation_id, configuration)
            observed['configuration']['groups'][1]['placement_ids'] = ['OTHER000001']
            return observed

        with patch.object(self.setup.provider, 'readback', side_effect=different_placements):
            result = self.setup.create(*self.reference, plan['id'])
        self.assertEqual(result['status'], 'mismatch')
        self.assertEqual(result['plan']['groups'][1]['placement_ids'], ['SAMPLE00002'])
        self.assertEqual(result['readback']['configuration']['groups'][1]['placement_ids'], ['OTHER000001'])
