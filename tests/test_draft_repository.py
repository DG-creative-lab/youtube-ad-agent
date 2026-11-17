"""The actual draft policy can validate/write through authored records only."""
import json
import unittest
from unittest.mock import patch

from campaign_agent.domain.errors import StaleDraft
import test_placement_planner as fixtures


class DraftRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.PlacementPlannerTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.drafts = self.case.runtime.drafts
        initial = json.dumps(self.drafts.read())
        owner = ('local-client', 'tts-demo', 'local-workspace', 'youtube-local')

        class AuthoredRecords:
            def __init__(self):
                self.snapshots = [initial]
                self.owner = owner

            def owner_row(self, campaign):
                return self.owner

            def read_snapshot(self, campaign, revision=None):
                return self.snapshots[-1] if revision is None else self.snapshots[revision - 1]

            def append_snapshot(self, campaign, revision, snapshot):
                self.snapshots.append(snapshot)

            def placement_catalog_entry(self, client, brand, campaign, ref):
                if (client, brand, campaign, ref) == ('local-client', 'tts-demo', 'tts-sample', 'a' * 32):
                    return ('SAMPLE00001', 'Authored title', 'licensed', 'license:fixture')
                return None

            def live_catalog_entry(self, *args):
                raise AssertionError('No live catalogue in the authored offline command')

        self.records = AuthoredRecords()
        self.row = {'id': 'SAMPLE00001', 'title': 'Authored title', 'creative': 'video-editing',
                    'source': 'licensed', 'catalog_ref': 'a' * 32, 'source_reference': 'license:fixture'}
        self.payload = {'campaign_id': 'tts-sample', 'revision': 1, 'placements': [self.row]}

    def test_pure_draft_participant_keeps_provenance_replay_and_stale_rules(self):
        original = self.records.snapshots[0]
        with patch('campaign_agent.application.campaigns.SQLiteDraftStore', side_effect=AssertionError('No native store')), \
             patch('campaign_agent.application.campaigns.SQLiteDraftRepository', side_effect=AssertionError('No native repository')):
            saved = self.drafts.save(self.payload, repository=self.records)
            self.assertEqual(saved['revision'], 2)
            self.assertEqual(saved['placements'], [self.row])
            self.assertEqual(self.drafts.save(self.payload, repository=self.records), saved)
            with self.assertRaises(StaleDraft):
                self.drafts.save({**self.payload, 'placements': [{**self.row, 'creative': 'audiobook'}]}, repository=self.records)
            with self.assertRaises(ValueError):
                self.drafts.save({**self.payload, 'revision': 2, 'placements': [{**self.row, 'source_reference': 'forged'}]}, repository=self.records)
        self.assertEqual(self.records.snapshots[0], original)
        self.assertEqual(len(self.records.snapshots), 2)
        self.assertEqual(self.drafts.read()['revision'], 1)

    def test_owner_grant_and_mixed_sources_cannot_append(self):
        owner = self.records.owner
        for index in range(4):
            wrong = list(owner)
            wrong[index] = 'foreign'
            self.records.owner = tuple(wrong)
            with self.assertRaises(PermissionError):
                self.drafts.save(self.payload, repository=self.records)
        self.records.owner = owner
        require = self.drafts.require
        writes = 0

        def revoked(capability):
            nonlocal writes
            require(capability)
            if capability == 'youtube:campaign.draft':
                writes += 1
                if writes == 2:
                    raise PermissionError('Revoked before append')

        with patch.object(self.drafts, 'require', side_effect=revoked):
            with self.assertRaisesRegex(PermissionError, 'Revoked before append'):
                self.drafts.save(self.payload, repository=self.records)
        with self.assertRaises(ValueError):
            self.drafts.save(self.payload, connection=object(), repository=self.records)
        self.assertEqual(len(self.records.snapshots), 1)
