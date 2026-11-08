from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from campaign_agent.access import LOCAL_BRAND, LOCAL_OPERATOR, Operator
from campaign_agent.adapters.openrouter_reviews import ReviewInferenceError
from campaign_agent.agent.run import AgentRuntime
from campaign_agent.agent.planning_models import SimulatedPlanner
from campaign_agent.creatives import EXAMPLES
from campaign_agent.handoff import package_fingerprint, sample_package
from scripts.campaign_drafts import PackageConflict


MODEL = 'example/planner:free'
CATALOG = [
    {'video_id': 'SAMPLE00001', 'source': 'synthetic', 'description': 'A video editing voiceover timing tutorial.'},
    {'video_id': 'SAMPLE00002', 'source': 'synthetic', 'description': 'Audiobook fiction narration and character voices.'},
    {'video_id': 'SAMPLE00003', 'source': 'synthetic', 'description': 'Video editing and audiobook production together.'},
]


class PlacementPlannerTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.path, self.media = self.directory / 'campaign.sqlite', self.directory / 'media'
        self.media.mkdir()
        for example in EXAMPLES:
            for name in {example.preview, *(take[2] for take in example.takes)}:
                (self.media / name).write_bytes(name.encode())
        self.runtime = self.reopen()
        self.catalog = self.runtime.planner.catalogs.register('Authored catalog', CATALOG)
        self.session = uuid4().hex

    def reopen(self, **options):
        return AgentRuntime(self.path, media_dir=self.media, **options)

    def start(self, runtime=None, model='simulated', catalog=None, session=None, run_id=None):
        return (runtime or self.runtime).planner.start('Find placements for the saved campaign.', model,
            session or self.session, run_id or uuid4().hex, catalog or self.catalog)

    def finish(self, run_id, runtime=None):
        runtime = runtime or self.runtime
        for _ in range(10):
            result = runtime.resume(run_id, max_steps=1)
            if result['status'] != 'running':
                return result
        self.fail('Run did not stop within its allowance')

    def reply(self, tool, arguments=None):
        return io.BytesIO(json.dumps({'id': 'gen-simulated', 'model': MODEL,
            'usage': {'prompt_tokens': 100, 'completion_tokens': 30, 'cost': 0},
            'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
                'tool_calls': [{'id': uuid4().hex, 'type': 'function', 'function': {
                    'name': tool, 'arguments': json.dumps(arguments or {})}}]}}]}).encode())

    def test_models_choose_different_orders_and_catalogs_change_the_saved_proposal(self):
        first = self.finish(self.start())
        self.assertEqual([step['tool'] for step in first['steps']],
                         ['read_campaign', 'classify_catalog', 'save_placement_draft'])
        self.assertEqual(first['result']['revision'], 2)
        self.assertEqual([row['id'] for row in first['result']['ambiguous']], ['SAMPLE00003'])
        self.assertIsNone(self.runtime.drafts.review_package('tts-sample', 2)['approval'])
        alternative = [{**row, 'video_id': row['video_id'].replace('0000', '0001')} for row in CATALOG]
        catalog = self.runtime.planner.catalogs.register('Different catalog', alternative)
        second = self.finish(self.start(model='simulated-inspect', session=uuid4().hex, catalog=catalog))
        self.assertEqual(second['steps'][0]['tool'], 'inspect_catalog')
        self.assertEqual(second['result']['revision'], 3)
        self.assertEqual([row['id'] for row in self.runtime.drafts.read()['placements']],
                         ['SAMPLE00001', 'SAMPLE00002', 'SAMPLE00011', 'SAMPLE00012'])
        self.assertEqual(second['planner']['settings']['model'], 'simulated-inspect')
        self.assertEqual(second['planner']['routing']['classifier'], 'simulated_decision')

    def test_overlapping_catalog_adds_videos_without_replacing_saved_placements(self):
        self.finish(self.start())
        original = self.runtime.drafts.read()['placements']
        review = self.runtime.drafts.review_package('tts-sample', 2)
        self.runtime.drafts.approve_package('tts-sample', 2, review['fingerprint'])
        overlap = {**CATALOG[0], 'source': 'licensed', 'source_reference': 'license:overlap',
                   'description': 'Audiobook narration for a different context.'}
        extra = {**CATALOG[1], 'video_id': 'SAMPLE00004'}
        catalog = self.runtime.planner.catalogs.register('Overlapping catalog', [overlap, extra])
        result = self.finish(self.start(catalog=catalog, session=uuid4().hex))
        self.assertEqual(result['result']['revision'], 3)
        self.assertEqual(self.runtime.drafts.read()['placements'][:2], original)
        self.assertEqual(self.runtime.drafts.read()['placements'][2]['id'], 'SAMPLE00004')
        self.assertIsNone(self.runtime.drafts.review_package('tts-sample', 3)['approval'])
        self.assertEqual(self.runtime.drafts.read_approved_package('tts-sample', 2,
            review['fingerprint'])['package'], review['package'])
        repeated = self.finish(self.start(catalog=catalog, session=uuid4().hex))
        self.assertEqual(repeated['result']['revision'], 3)
        self.assertIsNone(self.runtime.drafts.read(4))

    def test_bulk_context_selection_uses_the_same_classified_source_facts(self):
        rows = [{**CATALOG[index % 2], 'video_id': f'CAT{index:08d}'} for index in range(200)]
        catalog = self.runtime.planner.catalogs.register('Large authored catalog', rows)
        class BulkModel(SimulatedPlanner):
            def next_turn(self, context, history, settings):
                if any(step['tool'] == 'classify_catalog' for step in history):
                    return {'call_id': 'bulk-save', 'tool': 'save_placement_draft',
                            'arguments': {'contexts': ['video-editing', 'audiobook']}, 'inference': {}}
                return super().next_turn(context, history, settings)
        runtime = self.reopen(planner_simulator=BulkModel())
        result = self.finish(self.start(runtime, catalog=catalog), runtime)
        self.assertEqual(result['result']['revision'], 2)
        self.assertEqual(len(runtime.drafts.read()['placements']), 200)
        self.assertEqual(len(result['steps']), 3)

    def test_sessions_pin_model_actor_and_repeat_starts(self):
        run_id = self.start()
        self.assertEqual(self.start(run_id=run_id), run_id)
        with self.assertRaises(PermissionError):
            self.start(model='simulated-inspect')
        other = self.reopen(operator=Operator('another', frozenset({LOCAL_BRAND})))
        with self.assertRaises(PermissionError):
            other.resume(run_id)
        with self.assertRaises(PermissionError):
            self.start(runtime=other)
        with self.assertRaises(ValueError):
            self.runtime.planner.start('Changed request', 'simulated', self.session, run_id, self.catalog)
        self.assertEqual(self.finish(run_id)['planner']['settings']['model'], 'simulated')
        self.assertEqual(self.reopen().read(run_id)['result']['revision'], 2)
        self.assertEqual(self.start(run_id=run_id), run_id)

    def test_receipt_and_tool_write_roll_back_without_repeating_model_or_specialist(self):
        simulator = Mock(wraps=SimulatedPlanner())
        runtime = self.reopen(planner_simulator=simulator)
        run_id = self.start(runtime=runtime)
        runtime.resume(run_id, max_steps=2)
        self.assertEqual(simulator.next_turn.call_count, 2)
        save = runtime.planner.catalogs.save

        def interrupted(*args, **kwargs):
            save(*args, **kwargs)
            raise sqlite3.OperationalError('Interrupted write')

        with patch.object(runtime.planner.catalogs, 'save', side_effect=interrupted):
            with self.assertRaises(sqlite3.OperationalError):
                runtime.resume(run_id, max_steps=1)
        self.assertEqual(self.runtime.drafts.read()['revision'], 1)
        self.assertEqual(simulator.next_turn.call_count, 3)
        no_model = Mock()
        no_model.next_turn.side_effect = AssertionError('Must reuse receipt')
        reopened = self.reopen(planner_simulator=no_model)
        result = reopened.resume(run_id, max_steps=1)
        self.assertEqual(result['result']['revision'], 2)
        no_model.next_turn.assert_not_called()
        self.assertEqual(reopened.resume(run_id), result)
        self.assertIsNone(self.runtime.drafts.read(3))

    def test_recoverable_tool_error_rolls_back_any_partial_draft_write(self):
        run_id = self.start()
        self.runtime.resume(run_id, max_steps=2)
        save = self.runtime.planner.catalogs.save
        def rejected_after_write(*args, **kwargs):
            save(*args, **kwargs)
            raise ValueError('Rejected after partial tool work')
        with patch.object(self.runtime.planner.catalogs, 'save', side_effect=rejected_after_write):
            result = self.runtime.resume(run_id, max_steps=1)
        self.assertIn('error', result['steps'][-1]['result'])
        self.assertEqual(self.runtime.drafts.read()['revision'], 1)
        self.assertEqual(self.finish(run_id)['result']['revision'], 2)
        self.assertIsNone(self.runtime.drafts.read(3))

    def test_openrouter_sees_tool_results_and_routes_the_classifier_automatically(self):
        calls = []
        def transport(request, *, timeout):
            payload = json.loads(request.data)
            calls.append(payload)
            observations = [json.loads(message['content']) for message in payload['messages'] if message['role'] == 'tool']
            if not observations:
                return self.reply('classify_catalog')
            if len(observations) == 1:
                self.assertEqual(observations[0]['route'], 'simulated_decision')
                return self.reply('read_campaign')
            return self.reply('save_placement_draft', {'video_ids': ['SAMPLE00002']})
        runtime = self.reopen(main_models=(MODEL,), main_transport=transport)
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'authored-key'}):
            result = self.finish(self.start(runtime, model=MODEL), runtime)
        self.assertEqual([step['tool'] for step in result['steps']],
                         ['classify_catalog', 'read_campaign', 'save_placement_draft'])
        self.assertEqual([row['id'] for row in runtime.drafts.read()['placements']], ['SAMPLE00002'])
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]['tool_choice'], 'required')
        self.assertEqual(calls[0]['max_tokens'], 512)
        self.assertFalse(calls[0]['parallel_tool_calls'])
        self.assertEqual(calls[0]['provider']['max_price'], {'prompt': 0, 'completion': 0, 'request': 0})
        self.assertNotIn('authored-key', json.dumps(calls))

    def test_denied_tools_and_invented_ids_are_observations_and_exhaustion_stops(self):
        class UnsafeModel:
            def next_turn(self, context, history, settings):
                return {'call_id': str(len(history)), 'tool': 'approve_package', 'arguments': {}, 'inference': {}}
        result = self.finish(self.start(runtime=self.reopen(planner_simulator=UnsafeModel())),
                             self.reopen(planner_simulator=UnsafeModel()))
        self.assertEqual(result['status'], 'needs_input')
        self.assertEqual(len(result['steps']), 8)
        self.assertTrue(all('error' in step['result'] for step in result['steps']))
        self.assertEqual(self.runtime.drafts.read()['revision'], 1)
        class InventingModel(SimulatedPlanner):
            def next_turn(self, context, history, settings):
                if len(history) == 2:
                    return {'call_id': 'invented', 'tool': 'save_placement_draft',
                            'arguments': {'video_ids': ['NONEXIST001']}, 'inference': {}}
                return super().next_turn(context, history, settings)
        runtime = self.reopen(planner_simulator=InventingModel())
        result = self.finish(self.start(runtime, session=uuid4().hex), runtime)
        self.assertIn('error', result['steps'][2]['result'])
        self.assertEqual(result['result']['revision'], 2)
        self.assertNotIn('NONEXIST001', [row['id'] for row in runtime.drafts.read()['placements']])

    def test_irrelevant_catalog_asks_a_question_without_new_draft(self):
        catalog = self.runtime.planner.catalogs.register('Unrelated', [{**CATALOG[0], 'description': 'Gardening and kitchen repairs.'}])
        result = self.finish(self.start(catalog=catalog))
        self.assertEqual(result['status'], 'needs_input')
        self.assertIn('No unambiguous placements', result['result']['message'])
        self.assertEqual(self.runtime.drafts.read()['revision'], 1)

    def test_stale_revision_and_revoked_grant_block_dispatch(self):
        run_id = self.start()
        self.runtime.resume(run_id, max_steps=1)
        self.runtime.drafts.save({'campaign_id': 'tts-sample', 'revision': 1, 'placements': [
            {'id': 'OTHER000001', 'title': 'Independent edit', 'creative': 'video-editing', 'source': 'synthetic'}]})
        with self.assertRaises(PackageConflict):
            self.runtime.resume(run_id)
        current = self.start(session=uuid4().hex)
        self.runtime.operator = Operator('local-operator', frozenset())
        with self.assertRaises(PermissionError):
            self.runtime.resume(current)
        self.assertEqual(self.runtime.drafts.read()['revision'], 2)

    def test_unknown_provider_outcome_and_concurrent_resume_do_not_repeat_request(self):
        transport = Mock()
        runtime = self.reopen(main_models=(MODEL,), main_transport=transport)
        run_id = self.start(runtime, model=MODEL)
        def uncertain(*args, **kwargs):
            with self.assertRaises(ReviewInferenceError):
                self.reopen(main_models=(MODEL,), main_transport=transport).resume(run_id)
            raise TimeoutError('authored-key must not leak')
        transport.side_effect = uncertain
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'authored-key'}):
            with self.assertRaises(ReviewInferenceError):
                runtime.resume(run_id)
            with self.assertRaises(ReviewInferenceError):
                runtime.resume(run_id)
        self.assertEqual(transport.call_count, 1)
        self.assertNotIn('authored-key', json.dumps(runtime.read(run_id)))
        self.assertEqual(self.runtime.drafts.read()['revision'], 1)

    def test_classifier_receipt_is_validated_and_cannot_override_catalog_facts(self):
        classifier = Mock(route='simulated_decision')
        classifier.classify.return_value = [{'id': 'NONEXIST001', 'context': 'video-editing'} for _ in CATALOG]
        runtime = self.reopen(placement_classifier=classifier)
        run_id = self.start(runtime)
        runtime.resume(run_id, max_steps=1)
        with self.assertRaises(ReviewInferenceError):
            runtime.resume(run_id)
        with self.assertRaises(ReviewInferenceError):
            runtime.resume(run_id)
        self.assertEqual(classifier.classify.call_count, 1)
        self.assertEqual(self.runtime.drafts.read()['revision'], 1)

    def test_independent_catalog_provenance_survives_export_and_scope_substitution_is_denied(self):
        rows = [{**row, 'source': 'licensed', 'source_reference': f'license:fixture-{index}'}
                for index, row in enumerate(CATALOG)]
        catalog = self.runtime.planner.catalogs.register('Supplied fixture', rows)
        result = self.finish(self.start(catalog=catalog))
        package = self.runtime.drafts.review_package('tts-sample', result['result']['revision'])
        self.assertIn('Catalog candidates', package['package']['data_label'])
        self.runtime.drafts.approve_package('tts-sample', 2, package['fingerprint'])
        exported = self.runtime.drafts.export_setup('tts-sample', 2, package['fingerprint'])
        self.assertTrue(all(row['label'].startswith('Catalog candidate') for group in exported['groups'] for row in group['placements']))
        saved = self.runtime.drafts.read()['placements']
        expected = {'SAMPLE00001': 'license:fixture-0', 'SAMPLE00002': 'license:fixture-1'}
        self.assertEqual({row['id']: row.get('source_reference') for row in saved}, expected)
        self.assertEqual({row['demo_id']: row.get('source_reference') for group in exported['groups']
                          for row in group['placements']}, expected)
        reopened = self.reopen()
        self.assertEqual(reopened.drafts.read_approved_package('tts-sample', 2,
            package['fingerprint'])['package'], package['package'])
        with self.assertRaises(ValueError):
            self.runtime.drafts.save({'campaign_id': 'tts-sample', 'revision': 2,
                'placements': [{**saved[0], 'source_reference': 'license:forged'}, saved[1]]})
        bad = [{**saved[0], 'title': 'Model invented title'}, saved[1]]
        with self.assertRaises(ValueError):
            self.runtime.drafts.save({'campaign_id': 'tts-sample', 'revision': 2, 'placements': bad})
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE placement_catalog_entries SET brand_id=? WHERE ref=?', ('other-brand', saved[0]['catalog_ref']))
        with self.assertRaises(ValueError):
            self.runtime.drafts.save({'campaign_id': 'tts-sample', 'revision': 2, 'placements': saved})
        self.assertIsNone(self.runtime.drafts.read(3))
        self.assertEqual(self.runtime.drafts.read_approved_package('tts-sample', 2,
            package['fingerprint'])['package'], package['package'])

    def test_pre_reference_catalog_schema_recovers_provenance_without_rewriting_drafts(self):
        rows = [{**row, 'source': 'licensed', 'source_reference': 'license:fixture-123'} for row in CATALOG]
        catalog = self.runtime.planner.catalogs.register('Pre-reference catalog', rows)
        self.finish(self.start(catalog=catalog))
        legacy = self.runtime.drafts.read()
        for row in legacy['placements']:
            del row['source_reference']
        old_package = sample_package(legacy, self.media)
        old_fingerprint = package_fingerprint(old_package)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE campaign_revisions SET snapshot=? WHERE campaign_id=? AND revision=2',
                       (json.dumps(legacy), 'tts-sample'))
            db.execute('ALTER TABLE placement_catalog_entries RENAME TO old_entries')
            db.execute('''CREATE TABLE placement_catalog_entries AS
                          SELECT ref,client_id,brand_id,campaign_id,video_id,title,source FROM old_entries''')
            db.execute('DROP TABLE old_entries')
            db.execute('INSERT INTO campaign_package_approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                       (LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, 'tts-sample', 2, old_fingerprint,
                        LOCAL_OPERATOR.id, '2026-11-08T00:00:00+00:00', json.dumps(old_package)))
        reopened = self.reopen()
        self.assertEqual(reopened.drafts.read(), legacy)
        package = reopened.drafts.review_package('tts-sample', 2)
        self.assertNotEqual(package['fingerprint'], old_fingerprint)
        self.assertIsNone(package['approval'])
        self.assertEqual(reopened.drafts.read_approved_package('tts-sample', 2, old_fingerprint)['package'], old_package)
        with self.assertRaises(PackageConflict):
            reopened.drafts.export_setup('tts-sample', 2, old_fingerprint)
        reopened.drafts.approve_package('tts-sample', 2, package['fingerprint'])
        exported = reopened.drafts.export_setup('tts-sample', 2, package['fingerprint'])
        self.assertEqual([row['source_reference'] for group in exported['groups'] for row in group['placements']],
                         ['license:fixture-123', 'license:fixture-123'])
        self.assertEqual(reopened.drafts.read(), legacy)
