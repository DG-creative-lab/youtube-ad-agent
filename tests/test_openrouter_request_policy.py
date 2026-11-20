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
    def test_request_bytes_and_receipt_identity_match_the_recorded_contract(self):
        self.assertEqual(collect_request_identities(), EXPECTED)


# Structured requests retain the c1f92b2 baseline. Only the planner pair changes
# for the intentional v8 advice/tool-contract prompt and provenance, 20 Nov 2026.
EXPECTED = [
    ('836b9e25bcd6b6b5042b7878d5333408288f2821b7f905467abc0c41aa76798a',
     'https://openrouter.ai/api/v1/chat/completions', 30,
     '498ffee54bb39aebde0d88ddf24315c822a88117cf755fd9c55ff0274d344575'),
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
