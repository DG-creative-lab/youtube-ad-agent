from contextlib import closing
import io
import json
import os
import sqlite3
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from campaign_agent.access import LOCAL_BRAND, Operator
from campaign_agent.adapters.openrouter_reviews import ENDPOINT, ReviewInferenceError
from campaign_agent.agent.run import AgentRuntime
from campaign_agent.creatives import EXAMPLES
from campaign_agent.handoff import package_fingerprint
from scripts.campaign_drafts import PackageConflict
import test_campaign_performance as fixtures


MODEL = "example/drafter:free"
CHOICES = {"playback": "both_in_full", "focus": "delivery", "choice": "scene_fit"}
INSTRUCTION = "Play both takes in full. Compare their delivery. Then choose the delivery that best fits the scene."


class OpenRouterInstructionTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.CampaignPerformanceTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        _, self.review, self.offline_run = self.case.instruction_run()
        self.enterContext(patch.dict(os.environ, {"OPENROUTER_API_KEY": "authored-draft-key"}))
        self.response = {
            "id": "gen-authored-draft", "model": MODEL,
            "usage": {"prompt_tokens": 200, "completion_tokens": 32, "cost": 0},
            "choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(CHOICES),
            }}],
        }
        self.transport = Mock(side_effect=self.reply)
        self.runtime = self.reopen()

    def reply(self, _request, *, timeout):
        return io.BytesIO(json.dumps(self.response).encode())

    def reopen(self, *, models=(MODEL,), operator=None):
        options = {"operator": operator} if operator else {}
        return AgentRuntime(self.case.drafts.path, media_dir=self.case.drafts.media_dir,
                            openrouter_draft_models=models, draft_transport=self.transport, **options)

    def start(self, operation=None, **settings):
        return self.runtime.start_next_test(self.case.campaign, 2, self.case.fingerprint,
                                             self.review["id"], mode="openrouter", model=MODEL,
                                             operation_id=operation or uuid4().hex, **settings)

    def test_offline_default_and_explicit_drafting_gates(self):
        with self.assertRaises(ValueError):
            self.reopen(models=()).start_next_test(self.case.campaign, 2, self.case.fingerprint,
                self.review["id"], mode="openrouter", model=MODEL, operation_id=uuid4().hex)
        for options in ({"mode": "openrouter", "model": MODEL},
                        {"mode": "offline", "model": MODEL}, {"mode": "other"},
                        {"mode": "openrouter", "model": "example/paid", "operation_id": uuid4().hex}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.runtime.start_next_test(self.case.campaign, 2, self.case.fingerprint, self.review["id"], **options)
        other = self.reopen(operator=Operator("another", frozenset({LOCAL_BRAND})))
        with self.assertRaises(PermissionError):
            other.resume(self.offline_run)
        self.runtime.resume(self.offline_run)
        self.assertEqual(self.case.drafts.read()["revision"], 3)
        self.assertNotEqual(self.case.drafts.read()["instruction_test"]["after"], INSTRUCTION)
        self.transport.assert_not_called()

    def test_received_draft_and_atomic_save_survive_restarts(self):
        operation = uuid4().hex
        run_id = self.start(operation)
        self.runtime.resume(run_id, max_steps=1)
        with patch.object(self.runtime.drafts, "validate_instruction", side_effect=sqlite3.OperationalError("Interrupted")):
            with self.assertRaises(sqlite3.OperationalError):
                self.runtime.resume(run_id, max_steps=1)
        self.assertEqual(self.runtime.read(run_id)["inference"]["state"], "received")
        self.assertEqual(len(self.runtime.read(run_id)["steps"]), 1)
        reopened = self.reopen(models=())
        reopened.resume(run_id, max_steps=1)
        save = reopened.drafts.save_instruction_test

        def interrupted(*args, **kwargs):
            save(*args, **kwargs)
            raise sqlite3.OperationalError("Interrupted save")

        with patch.object(reopened.drafts, "save_instruction_test", side_effect=interrupted):
            with self.assertRaises(sqlite3.OperationalError):
                reopened.resume(run_id, max_steps=1)
        self.assertIsNone(self.case.drafts.read(3))
        result = reopened.resume(run_id)
        self.assertEqual(result["status"], "ready_for_review")
        saved = self.case.drafts.read()["instruction_test"]
        self.assertEqual(saved["after"], INSTRUCTION)
        self.assertEqual(saved["correction"], self.review["proposal"]["correction"])
        self.assertEqual(saved["review_id"], self.review["id"])
        context = result["steps"][0]["result"]
        self.assertEqual(saved["inference"]["evidence_id"], package_fingerprint(context))
        self.assertEqual(saved["inference"]["model"], MODEL)
        self.assertEqual(saved["inference"]["usage"], {"input_tokens": 200, "output_tokens": 32, "cost_usd": 0})
        self.assertEqual(self.start(operation), run_id)
        self.assertEqual(self.runtime.resume(run_id), result)
        self.assertIsNone(self.case.drafts.read(4))
        package = self.case.drafts.review_package(self.case.campaign, 3)
        self.assertIsNone(package["approval"])
        old_content = context["comparison"]
        new_content = package["package"]["groups"][0]["content"]
        self.assertEqual({**new_content, "instruction": old_content["instruction"]}, old_content)
        self.assertEqual(self.case.drafts.read(2)["placements"], self.case.drafts.read(3)["placements"])
        self.assertEqual(self.transport.call_count, 1)
        sent = self.transport.call_args.args[0]
        self.assertEqual(sent.full_url, ENDPOINT)
        payload = json.loads(sent.data)
        evidence = json.loads(payload["messages"][1]["content"])
        self.assertEqual(evidence["buyer_correction"]["note"], "Keep the approved audio.")
        self.assertEqual(evidence["local_viewer_activity"], self.review["local_viewer_activity"])
        self.assertEqual(evidence["sample_delivery"], self.review["sample_delivery"])
        self.assertNotIn("authored-draft-key", json.dumps(evidence))
        self.assertEqual(payload["response_format"]["json_schema"]["schema"]["required"],
                         ["playback", "focus", "choice"])
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(payload["provider"]["max_price"], {"prompt": 0, "completion": 0, "request": 0})
        self.assertFalse(payload["provider"]["allow_fallbacks"])

    def test_invalid_draft_shapes_and_usage_never_save_a_revision(self):
        original = self.case.drafts.review_package(self.case.campaign, 2)["package"]["groups"][0]["content"]["instruction"]
        for draft in (None, "text", {"instruction": ""}, {"instruction": original},
                      {"instruction": "x" * 501}, {"instruction": INSTRUCTION, "approve": True},
                      {"instruction": 123}, {**CHOICES, "focus": "Choose A; guarantees 100% results"},
                      {**CHOICES, "playback": "skip_second"}, {**CHOICES, "choice": []},
                      {**CHOICES, "instruction": "Choose A"}):
            with self.subTest(draft=draft):
                self.response["choices"][0]["message"]["content"] = json.dumps(draft)
                run_id = self.start()
                with self.assertRaises(ReviewInferenceError):
                    self.runtime.resume(run_id)
                calls = self.transport.call_count
                with self.assertRaises(ReviewInferenceError):
                    self.runtime.resume(run_id)
                self.assertEqual(self.transport.call_count, calls)
                self.assertIsNone(self.case.drafts.read(3))

        self.response["choices"][0]["message"]["content"] = json.dumps(CHOICES)
        for usage in ({"cost": 0.01}, {"completion_tokens": 513}):
            with self.subTest(usage=usage):
                self.response["usage"] = usage
                with self.assertRaises(ReviewInferenceError):
                    self.runtime.resume(self.start())
                self.assertIsNone(self.case.drafts.read(3))

    def test_provider_cannot_bias_the_choice_or_invent_claims(self):
        self.response["choices"][0]["message"]["content"] = json.dumps({
            "instruction": "Skip the second take. Choose A; this product guarantees 100% results.",
        })
        run_id = self.start()
        with self.assertRaises(ReviewInferenceError):
            self.runtime.resume(run_id)
        self.assertIsNone(self.case.drafts.read(3))
        self.assertEqual(len(self.runtime.read(run_id)["steps"]), 1)
        with self.assertRaises(ReviewInferenceError):
            self.runtime.resume(run_id)
        self.assertEqual(self.transport.call_count, 1)

    def test_cached_free_form_draft_cannot_bypass_save_validation(self):
        run_id = self.start()
        self.runtime.resume(run_id, max_steps=2)
        # A step accepted before the constrained contract must not bypass the application writer.
        with closing(sqlite3.connect(self.case.drafts.path)) as db, db:
            result = json.loads(db.execute(
                "SELECT result FROM agent_steps WHERE run_id = ? AND position = 1", (run_id,),
            ).fetchone()[0])
            result["instruction"] = "Skip the second take. Choose A; this product guarantees 100% results."
            result["inference"].pop("wording_choices")
            db.execute("UPDATE agent_steps SET result = ? WHERE run_id = ? AND position = 1",
                       (json.dumps(result), run_id))
        with self.assertRaises(ValueError):
            self.reopen().resume(run_id)
        self.assertIsNone(self.case.drafts.read(3))
        self.assertEqual(self.transport.call_count, 1)

    def test_changed_correction_rejects_late_receipt_and_preserves_it(self):
        def reply_after_correction(request, *, timeout):
            # This writer must succeed while inference runs outside the SQLite transaction.
            self.case.performance.save_correction(self.case.campaign, 2, self.case.fingerprint,
                self.review["id"], "keep_comparison", "Preserve the comparison.", uuid4().hex)
            return self.reply(request, timeout=timeout)

        self.transport.side_effect = reply_after_correction
        run_id = self.start()
        with self.assertRaises(PackageConflict):
            self.runtime.resume(run_id)
        self.assertEqual(self.runtime.read(run_id)["inference"]["state"], "received")
        self.assertIsNone(self.case.drafts.read(3))
        with self.assertRaises(PackageConflict):
            self.runtime.resume(run_id)
        self.assertEqual(self.transport.call_count, 1)

    def test_correction_is_rechecked_before_save_and_request(self):
        run_id = self.start()
        self.runtime.resume(run_id, max_steps=2)
        self.case.performance.save_correction(self.case.campaign, 2, self.case.fingerprint,
            self.review["id"], "keep_comparison", "", uuid4().hex)
        with self.assertRaises(PackageConflict):
            self.runtime.resume(run_id)
        self.assertIsNone(self.case.drafts.read(3))
        self.assertEqual(len(self.runtime.read(run_id)["steps"]), 2)
        with self.assertRaises(PackageConflict):
            self.start()
        self.assertEqual(self.transport.call_count, 1)

    def test_material_package_change_blocks_dispatch(self):
        run_id = self.start()
        self.runtime.resume(run_id, max_steps=1)
        (self.case.drafts.media_dir / EXAMPLES[0].preview).write_bytes(b"Changed creative")
        with self.assertRaises(PackageConflict):
            self.runtime.resume(run_id)
        self.transport.assert_not_called()

    def test_pending_request_checks_configuration_and_unknown_outcome_is_not_repeated(self):
        operation = uuid4().hex
        run_id = self.start(operation)
        with self.assertRaises(ValueError):
            self.runtime.start_next_test(self.case.campaign, 2, self.case.fingerprint, self.review["id"],
                mode="offline", operation_id=operation)
        with self.assertRaises(ValueError):
            self.runtime.start_next_test(self.case.campaign, 2, self.case.fingerprint, "f" * 64,
                mode="openrouter", model=MODEL, operation_id=operation)
        self.runtime.resume(run_id, max_steps=1)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            with self.assertRaises(ReviewInferenceError):
                self.runtime.resume(run_id)
        self.assertEqual(self.runtime.read(run_id)["inference"]["state"], "pending")
        with self.assertRaises(ValueError):
            self.reopen(models=()).resume(run_id)
        self.transport.assert_not_called()

        def concurrent_then_timeout(_request, *, timeout):
            with self.assertRaises(ReviewInferenceError):
                self.reopen().resume(run_id)
            raise TimeoutError("authored-draft-key must not be exposed")

        self.transport.side_effect = concurrent_then_timeout
        with self.assertRaises(ReviewInferenceError):
            self.runtime.resume(run_id)
        with self.assertRaises(ReviewInferenceError):
            self.runtime.resume(run_id)
        self.assertEqual(self.start(operation), run_id)
        self.assertEqual(self.transport.call_count, 1)
        self.assertNotIn("authored-draft-key", json.dumps(self.runtime.read(run_id)))
        self.assertIsNone(self.case.drafts.read(3))
