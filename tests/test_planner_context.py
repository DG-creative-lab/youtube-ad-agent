"""Real nonempty planner context reads match the legacy authored workflow."""
from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4

from campaign_agent.adapters.local_media import LocalMedia
from campaign_agent.adapters.sqlite_drafts import SQLiteDraftRepository
from campaign_agent.adapters.sqlite_planner_context import SQLitePlannerContext
from campaign_agent.application.planner_context import PlannerContext, package_fingerprint
from campaign_agent.creatives import EXAMPLES
from campaign_agent.handoff import example_content
import test_placement_planner as fixtures


class PlannerContextTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.PlacementPlannerTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.runtime = self.case.runtime
        self.drafts = self.runtime.drafts
        self.media = LocalMedia(self.case.media)

    def service(self):
        return PlannerContext(self.drafts, self.drafts.examples, self.media.capture(self.drafts.examples))

    def approve_and_review(self):
        self.drafts.save({'campaign_id': 'tts-sample', 'revision': 1, 'placements': [
            {'id': 'SAMPLE00001', 'title': 'Editing', 'creative': 'video-editing', 'source': 'synthetic'},
            {'id': 'SAMPLE00002', 'title': 'Audiobook', 'creative': 'audiobook', 'source': 'synthetic'}]})
        review = self.drafts.review_package('tts-sample', 2)
        approved = self.drafts.approve_package('tts-sample', 2, review['fingerprint'])
        content = package_fingerprint(approved['package']['groups'][0]['content'])
        for _ in range(3):
            self.runtime.performance.viewer.open_example(EXAMPLES[0].creative_ref, content_fingerprint=content)
        initial = self.runtime.performance.review('tts-sample', 2, review['fingerprint'], 'balanced')
        correction = self.runtime.performance.save_correction(
            'tts-sample', 2, review['fingerprint'], initial['id'], 'keep_takes',
            'Keep the authored audio.', uuid4().hex)
        saved = self.runtime.performance.review('tts-sample', 2, review['fingerprint'], 'balanced')
        return review['fingerprint'], saved, correction

    def test_empty_context_and_package_bytes_match_without_media_io_inside_service(self):
        service = self.service()
        source = {'draft_permission': 'placements'}
        with closing(sqlite3.connect(self.case.path)) as db:
            expected = self.drafts._package_review(db, 'tts-sample', 1)[0]
            expected_pin = self.runtime.planner.review_tools.pin(db, self.drafts._read(db))
            expected_campaign = self.runtime.planner._tool(db, 'unused', source, [],
                {'tool': 'read_campaign', 'arguments': {}}, None)[0]
            records, drafts = SQLitePlannerContext(db), SQLiteDraftRepository(db)
            with patch.object(LocalMedia, '_read_asset', side_effect=AssertionError('No media I/O in core')):
                actual = service.package_review(records, drafts, 1)
                self.assertEqual(actual, expected)
                self.assertEqual(json.dumps(actual), json.dumps(expected))
                self.assertEqual(service.pin(records, drafts, self.drafts.read_from(drafts)), expected_pin)
                self.assertEqual(service.read_campaign(records, drafts, source), expected_campaign)

    def test_actual_saved_review_correction_and_started_experiment_are_not_skipped(self):
        fingerprint, saved, _ = self.approve_and_review()
        service = self.service()
        with closing(sqlite3.connect(self.case.path)) as db:
            records, drafts = SQLitePlannerContext(db), SQLiteDraftRepository(db)
            self.assertEqual(service.saved_review(records, 2, fingerprint)['id'], saved['id'])
            draft = self.drafts.read_from(drafts)
            self.assertEqual(service.pin(records, drafts, draft), self.runtime.planner.review_tools.pin(db, draft))
            expected = self.runtime.planner._tool(db, 'unused', {}, [],
                {'tool': 'read_campaign', 'arguments': {}}, None)[0]
            actual = service.read_campaign(records, drafts, {})
            self.assertEqual(actual, expected)
            self.assertEqual(actual['buyer_corrections'][0]['kind'], 'keep_takes')
            self.assertTrue(actual['package_approved'])
        run = self.runtime.start_next_test('tts-sample', 2, fingerprint, saved['id'])
        self.runtime.resume(run)
        current = self.drafts.review_package('tts-sample', 3)
        self.drafts.approve_package('tts-sample', 3, current['fingerprint'])
        started = self.runtime.instruction_tests.start('tts-sample', 3, current['fingerprint'])
        with closing(sqlite3.connect(self.case.path)) as db:
            records, drafts = SQLitePlannerContext(db), SQLiteDraftRepository(db)
            actual = self.service().pin(records, drafts, self.drafts.read_from(drafts))
            self.assertEqual(actual, self.runtime.planner.review_tools.pin(db, self.drafts._read(db)))
            self.assertEqual(actual['instruction_test_id'], started['id'])

    def test_newest_keep_comparison_cannot_resurrect_older_keep_takes(self):
        fingerprint, saved, _ = self.approve_and_review()
        self.runtime.performance.save_correction('tts-sample', 2, fingerprint, saved['id'],
                                                 'keep_comparison', 'Keep it all.', uuid4().hex)
        with closing(sqlite3.connect(self.case.path)) as db:
            records, drafts = SQLitePlannerContext(db), SQLiteDraftRepository(db)
            package = self.service().package_review(records, drafts, 2)['package']
            creative = package['groups'][0]['creative_version']
            self.assertEqual(self.service().correction_for_comparison(records, package, creative)['kind'], 'keep_comparison')
            changed = deepcopy(package)
            changed['groups'][0]['content']['instruction'] = 'Authored changed instruction.'
            self.assertIsNone(self.runtime.performance.correction_for_comparison(db, changed, creative))
            self.assertIsNone(self.service().correction_for_comparison(records, changed, creative))

    def test_scoped_attribution_filter_and_uncommitted_approval_use_callers_store(self):
        fingerprint, saved, _ = self.approve_and_review()
        with closing(sqlite3.connect(self.case.path)) as db, db:
            original = db.execute('SELECT * FROM campaign_performance_reviews WHERE id=?', (saved['id'],)).fetchone()
            wrong_attribution = list(original)
            wrong_attribution[0] = 'z' * 32
            wrong_attribution[7] = '9999-01-01'
            evidence = json.loads(wrong_attribution[8])
            evidence['local_viewer_activity']['attribution'] = 'unverified'
            wrong_attribution[8] = json.dumps(evidence)
            db.execute('INSERT INTO campaign_performance_reviews VALUES(?,?,?,?,?,?,?,?,?)', wrong_attribution)
            foreign = list(original)
            foreign[0], foreign[1], foreign[7] = 'y' * 32, 'foreign-client', '9999-01-01'
            db.execute('INSERT INTO campaign_performance_reviews VALUES(?,?,?,?,?,?,?,?,?)', foreign)
        with self.drafts.write_unit() as db:
            db.execute('UPDATE campaign_package_approvals SET actor_id=? WHERE campaign_id=? AND revision=?',
                       ('authored-uncommitted-reviewer', 'tts-sample', 2))
            records, drafts = SQLitePlannerContext(db), SQLiteDraftRepository(db)
            self.assertEqual(self.service().saved_review(records, 2, fingerprint)['id'], saved['id'])
            self.assertEqual(self.service().package_review(records, drafts, 2)['approval']['actor_id'],
                             'authored-uncommitted-reviewer')
            with closing(sqlite3.connect(self.case.path)) as observer:
                expected = self.service().package_review(SQLitePlannerContext(observer), SQLiteDraftRepository(observer), 2)
                self.assertNotEqual(expected['approval']['actor_id'], 'authored-uncommitted-reviewer')
            self.assertIsNone(records.approval_row('foreign', 'tts-demo', 'tts-sample', 2, fingerprint))
            self.assertIsNone(records.saved_review_row('foreign', 'tts-demo', 'tts-sample', 2, fingerprint,
                                                       'campaign_comparison_content_v1'))

    def test_missing_logical_media_matches_legacy_blockers_and_captured_facts_are_immutable(self):
        example = EXAMPLES[0]
        captured = self.media.capture(self.drafts.examples)
        first = captured.content(example)
        first['takes'][0]['sha256'] = 'modified by caller'
        self.assertNotEqual(captured.content(example)['takes'][0]['sha256'], 'modified by caller')
        (self.case.media / example.takes[1][2]).unlink()
        self.assertEqual(self.media.content(example), example_content(example, self.case.media))
        with closing(sqlite3.connect(self.case.path)) as db:
            actual = self.service().package_review(SQLitePlannerContext(db), SQLiteDraftRepository(db), 1)
            self.assertEqual(actual, self.drafts._package_review(db, 'tts-sample', 1)[0])
            self.assertTrue(any('media' in blocker for blocker in actual['blockers']))
