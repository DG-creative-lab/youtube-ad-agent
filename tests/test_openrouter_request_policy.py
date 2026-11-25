"""Pin versioned wire requests/receipts and retain the structured-adapter baseline."""
import hashlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from campaign_agent.bootstrap.runtime import create_runtime as AgentRuntime
from campaign_agent.agent.planning_models import planner_request_body
from campaign_agent.ports.inference import ProviderError


MODEL = 'fixture/campaign:free'
CHOICES = {'playback': 'both_in_full', 'focus': 'delivery', 'choice': 'scene_fit'}


def collect_request_identities():
    """Exercise the real runtime's three adapters without opening a network connection."""
    with TemporaryDirectory() as directory, patch.dict(os.environ, {'OPENROUTER_API_KEY': 'authored-test-key'}):
        requests = []

        def transport_for(message, finish_reason):
            def transport(request, *, timeout):
                requests.append((request.data, request.full_url, timeout))
                return io.BytesIO(json.dumps({
                    'id': 'authored-receipt', 'model': MODEL,
                    'choices': [{'finish_reason': finish_reason, 'message': message}],
                    'usage': {'prompt_tokens': 23, 'completion_tokens': 9, 'cost': 0},
                }).encode())
            return transport

        runtime = AgentRuntime(
            Path(directory) / 'state.sqlite3', main_models=(MODEL,), openrouter_models=(MODEL,),
            openrouter_draft_models=(MODEL,),
            main_transport=transport_for({'tool_calls': [{
                'id': 'tool-1', 'type': 'function',
                'function': {'name': 'read_campaign', 'arguments': '{}'},
            }]}, 'tool_calls'),
            review_transport=transport_for({'content': '{"reason_code":"insufficient_visits"}'}, 'stop'),
            draft_transport=transport_for({'content': json.dumps(CHOICES)}, 'stop'),
        )
        planner = runtime.planner.remote
        review = runtime.openrouter
        draft = runtime.openrouter_drafts
        context = {
            'request': 'Find placements for café videos.',
            'draft_permission': 'placements',
            'conversation': [{'id': 1, 'content': 'Keep the wording.', 'selection_id': 'internal-selection'}],
            'connection_id': 'internal-connection',
        }
        history = [{'call_id': 'previous-1', 'tool': 'inspect_catalog',
                    'arguments': {}, 'result': {'count': 2}}]
        comparison = {'title': 'Two takes', 'instruction': 'Pick one.', 'passage': 'Café',
                      'unused_field': 'outside-evidence'}
        correction = {'kind': 'keep_takes', 'label': 'Keep the takes', 'note': 'Use both.'}
        assessment_context = {
            'versions': [{'arm': arm, 'content': comparison} for arm in ('original', 'revised')],
            'rows': [{'arrivals': 2, 'completions': 1}, {'arrivals': 1, 'completions': 0}],
            'minimum_per_version': 20, 'correction': correction,
        }
        draft_context = {
            'comparison': comparison, 'correction': correction,
            'review': {'proposal': {'kind': 'comparison_test'}, 'sample_delivery': {'scenario': 'balanced'},
                       'local_viewer_activity': {'arrivals': 3}},
        }
        receipts = [
            planner.next_turn(context, history, planner.settings(MODEL)),
            review.assess_instruction_test(assessment_context, review.settings(MODEL)),
            draft.draft_instructions(draft_context, draft.settings(MODEL)),
            draft.draft_instructions({**draft_context, 'experiment_review': {'id': 'saved-experiment'}},
                                     draft.settings(MODEL)),
        ]
        return [
            (hashlib.sha256(request).hexdigest(), url, timeout,
             hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest())
            for (request, url, timeout), receipt in zip(requests, receipts, strict=True)
        ]


class OpenRouterRequestPolicyTests(unittest.TestCase):
    def test_adapter_uses_saved_settings_and_v9_measurement_definition_stays_pinned(self):
        from copy import deepcopy
        from campaign_agent.adapters.openrouter_reviews import OpenRouterPlanner
        from campaign_agent.domain.measurement import measurement_capabilities
        fixtures = json.loads((Path(__file__).parent / 'fixtures/planner_prompt_versions.json').read_text())
        self.assertEqual(measurement_capabilities(), fixtures['versions']['9']['context']['measurement_capabilities'])
        fixture = fixtures['versions']['8']
        context = deepcopy(fixture['context'])
        settings = context.pop('settings')
        expected = deepcopy(fixture['body'])
        projected = json.loads(expected['messages'][1]['content'])
        projected.pop('settings')
        expected['messages'][1]['content'] = json.dumps(projected)
        adapter = OpenRouterPlanner((), request_body=planner_request_body)
        _, body = adapter.prepare_turn(context, [], settings)
        self.assertEqual(json.dumps(body), json.dumps(expected))

    def test_unsupported_or_mismatched_pins_cannot_silently_use_the_latest_prompt(self):
        for version in ('campaign-planner-v99', None, []):
            with self.subTest(version=version), self.assertRaises(ProviderError) as raised:
                planner_request_body({'settings': {'charging_profile': 'preview-text-tools/test', 'prompt_version': version}}, [])
            self.assertEqual(raised.exception.code, 'prompt_version_unsupported')
        with self.assertRaises(ProviderError) as raised:
            planner_request_body({'settings': {'prompt_version': 'campaign-planner-v8'}}, [],
                                 {'mode': 'openrouter', 'prompt_version': 'campaign-planner-v9'})
        self.assertEqual(raised.exception.code, 'operation_conflict')

    def test_pinned_preview_versions_keep_their_historical_request_bytes(self):
        fixtures = json.loads((Path(__file__).parent / 'fixtures/planner_prompt_versions.json').read_text())
        for version, fixture in fixtures['versions'].items():
            with self.subTest(version=version):
                context = json.loads(json.dumps(fixture['context']))
                expected = fixture['body']
                if version in ('7', '8'):
                    context['measurement_capabilities'] = {'sentinel': 'v9-only facts'}
                if version == '7':
                    context['campaign_contexts'] = {'future-context': {'title': 'Not in v7'}}
                self.assertEqual(json.dumps(planner_request_body(context, [])).encode(), json.dumps(expected).encode())

    def test_old_preview_history_cannot_acquire_new_measurement_fields(self):
        fixtures = json.loads((Path(__file__).parent / 'fixtures/planner_prompt_versions.json').read_text())
        for version in ('7', '8'):
            with self.subTest(version=version):
                fixture = fixtures['versions'][version]
                history = [{'call_id': 'read-v8', 'tool': 'read_campaign', 'arguments': {},
                            'result': {'revision': 1, 'measurement_capabilities': {'sentinel': 'v9-only facts'}}}]
                body = planner_request_body(fixture['context'], history)
                self.assertEqual(json.loads(body['messages'][-1]['content']), {'revision': 1})

    def test_request_bytes_and_receipt_identity_match_the_recorded_contract(self):
        self.assertEqual(collect_request_identities(), EXPECTED)


# Structured requests retain the c1f92b2 baseline; the legacy planner wire keeps
# its v8 bytes. Only planner receipt provenance changes to v9 on 20 Nov 2026;
# measurement context/prompt additions are on the live foreground request path.
EXPECTED = [
    ('836b9e25bcd6b6b5042b7878d5333408288f2821b7f905467abc0c41aa76798a',
     'https://openrouter.ai/api/v1/chat/completions', 30,
     'e403a0197fb05b840c50c854c112be003b0409e62485b347b79146f63ae24900'),
    ('50fea33860a938d5d3b390f1d23524f3636a56df19792ec745f927d9c282d876',
     'https://openrouter.ai/api/v1/chat/completions', 30,
     'b6cc107b606c0f785ec431fb1a0e6107330ee9e6c8714ca32106e76bfa1c2077'),
    ('622a708c723031714fdb0689ca01e34569db1dea0be6dcaa13e1af2e55145e7b',
     'https://openrouter.ai/api/v1/chat/completions', 30,
     '19d4dcf2ac7b7299e771d9f93614869e1475409658b4326a9b27e8c86710cf1f'),
    ('6eb47a06a2fa8df947a1987fc78af6e83a136cf88b31be548dc4b086850a9270',
     'https://openrouter.ai/api/v1/chat/completions', 30,
     'b471dd54455795dfd625c4aa74115409ba4861ed2dbdf8c2dbc60a3b9c54fea6'),
]
