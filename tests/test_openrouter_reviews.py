from contextlib import closing
import io
import json
import os
import sqlite3
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from uuid import uuid4

from campaign_agent.access import LOCAL_BRAND, Operator
from campaign_agent.adapters.openrouter_reviews import ENDPOINT, ReviewInferenceError
from campaign_agent.agent.run import AgentRuntime, REVIEW_TEST_REQUEST
from campaign_agent.handoff import package_fingerprint
from scripts.campaign_drafts import PackageConflict
import test_instruction_tests as fixtures


MODEL = "example/reviewer:free"
FAKE_KEY = "authored-test-only-key"


class OpenRouterReviewTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.InstructionTestTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.start()
        self.enterContext(patch.dict(os.environ, {"OPENROUTER_API_KEY": FAKE_KEY}))
        self.response = {
            "id": "gen-authored-review", "model": MODEL,
            "usage": {"prompt_tokens": 321, "completion_tokens": 42, "cost": 0},
            "choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"reason_code": "insufficient_visits"}),
            }}],
        }
        self.transport = Mock(side_effect=self.reply)
        self.runtime = self.runtime_with_transport(self.transport)

    def reply(self, _request, *, timeout):
        return io.BytesIO(json.dumps(self.response).encode())

    def runtime_with_transport(self, transport, models=(MODEL,), operator=None):
        options = {"operator": operator} if operator else {}
        return AgentRuntime(self.case.path, media_dir=self.case.media, openrouter_models=models,
                            review_transport=transport, **options)

    def start(self, operation=None):
        return self.runtime.start_instruction_review(self.case.test["id"], mode="openrouter",
                                                     model=MODEL, operation_id=operation or uuid4().hex)

    def test_offline_default_and_dispatch_gates_make_zero_provider_calls(self):
        run_id = self.runtime.start_instruction_review(self.case.test["id"])
        self.runtime.resume(run_id)
        self.assertEqual(self.case.read()["review"]["inference"]["mode"], "offline")
        self.transport.assert_not_called()
        disabled = self.runtime_with_transport(self.transport, models=())
        with self.assertRaises(ValueError):
            disabled.start_instruction_review(self.case.test["id"], mode="openrouter",
                                               model=MODEL, operation_id=uuid4().hex)
        with self.assertRaises(ValueError):
            self.runtime.start_instruction_review(self.case.test["id"], mode="openrouter",
                                                  model="example/paid-model", operation_id=uuid4().hex)
        run_id = self.start()
        self.runtime.resume(run_id, max_steps=1)
        with self.assertRaises(ValueError):
            disabled.resume(run_id, max_steps=1)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            with self.assertRaises(ReviewInferenceError):
                self.runtime.resume(run_id, max_steps=1)
        self.assertEqual(self.runtime.read(run_id)["inference"]["state"], "pending")
        other = self.runtime_with_transport(self.transport, operator=Operator("another", frozenset({LOCAL_BRAND})))
        with self.assertRaises(PermissionError):
            other.resume(run_id)
        self.transport.assert_not_called()
        self.runtime.resume(run_id)
        self.assertEqual(self.transport.call_count, 1)

    def test_response_receipt_survives_restart_without_another_provider_call(self):
        operation = uuid4().hex
        run_id = self.start(operation)
        self.runtime.resume(run_id, max_steps=1)
        with patch.object(self.runtime.instruction_tests, "validate_assessment",
                          side_effect=sqlite3.OperationalError("Interrupted step commit")):
            with self.assertRaises(sqlite3.OperationalError):
                self.runtime.resume(run_id, max_steps=1)
        self.assertEqual(self.transport.call_count, 1)
        captured = self.runtime.read(run_id)
        self.assertEqual(len(captured["steps"]), 1)
        self.assertEqual(captured["inference"]["state"], "received")
        unused_transport = Mock(side_effect=AssertionError("Repeated inference"))
        reopened = self.runtime_with_transport(unused_transport, models=())
        result = reopened.resume(run_id)
        self.assertEqual(result["status"], "ready_for_review")
        unused_transport.assert_not_called()
        review = self.case.read()["review"]
        self.assertEqual(review["assessment"]["title"], "Insufficient evidence")
        metadata = review["inference"]
        self.assertEqual(metadata["model"], MODEL)
        self.assertEqual(metadata["request_id"], "gen-authored-review")
        self.assertEqual(metadata["usage"], {"input_tokens": 321, "output_tokens": 42, "cost_usd": 0})
        self.assertEqual(metadata["evidence_id"], package_fingerprint(review["evidence"]))
        offline = self.runtime.start_instruction_review(self.case.test["id"], operation_id=uuid4().hex)
        self.runtime.resume(offline)
        self.assertEqual(self.case.read()["review"]["inference"]["mode"], "offline")
        self.case.open("original")
        self.assertEqual(self.start(operation), run_id)
        self.assertEqual(self.runtime.resume(run_id)["run_id"], run_id)
        self.assertEqual(self.transport.call_count, 1)
        request = self.transport.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, ENDPOINT)
        self.assertEqual(payload["model"], MODEL)
        self.assertEqual(payload["max_tokens"], 512)
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["provider"], {
            "require_parameters": True, "allow_fallbacks": False,
            "max_price": {"prompt": 0, "completion": 0, "request": 0},
        })
        self.assertEqual(payload["response_format"]["json_schema"]["schema"]["required"], ["reason_code"])
        self.assertNotIn(FAKE_KEY, request.data.decode())
        with closing(sqlite3.connect(self.case.path)) as db:
            self.assertNotIn(FAKE_KEY, "\n".join(db.iterdump()))

    def test_failures_consume_one_allowance_and_do_not_expose_provider_errors(self):
        cases = [
            ("http", HTTPError(ENDPOINT, 503, FAKE_KEY, {}, io.BytesIO(FAKE_KEY.encode()))),
            ("timeout", TimeoutError(FAKE_KEY)),
            ("bad_json", b"not-json-" + FAKE_KEY.encode()),
            ("truncated", {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}),
            ("bad_assessment", {"choices": [{"finish_reason": "stop", "message": {
                "content": '{"kind":"prepare_another_test","title":"Winner","reason":"Invented outcome"}',
            }}]}),
            ("unsupported_reason", {"choices": [{"finish_reason": "stop", "message": {
                "content": '{"reason_code":"revised_not_higher"}',
            }}]}),
            ("duplicate_field", {"choices": [{"finish_reason": "stop", "message": {
                "content": '{"kind":"insufficient_evidence","kind":"keep_collecting","title":"X","reason":"Y"}',
            }}]}),
            ("nonzero_cost", {"usage": {"cost": 0.01}}),
            ("output_limit", {"usage": {"completion_tokens": 513}}),
        ]
        for name, response in cases:
            with self.subTest(name=name):
                if isinstance(response, Exception):
                    self.transport.side_effect = response
                else:
                    data = response if isinstance(response, bytes) else json.dumps({**self.response, **response}).encode()
                    self.transport.side_effect = lambda *_args, **_kwargs: io.BytesIO(data)
                run_id = self.start()
                self.runtime.resume(run_id, max_steps=1)
                before = self.transport.call_count
                for _ in range(2):
                    with self.assertRaises(ReviewInferenceError) as error:
                        self.runtime.resume(run_id, max_steps=1)
                    self.assertNotIn(FAKE_KEY, str(error.exception))
                self.assertEqual(self.transport.call_count, before + 1)
                self.assertIsNone(self.case.read()["review"])

    def test_provider_call_releases_sqlite_and_rechecks_correction_before_accepting_result(self):
        def change_correction(request, *, timeout):
            for _ in range(3):
                self.case.open("revised")
            review = self.case.runtime.performance.review(self.case.campaign, 3, self.case.fingerprint, "balanced")
            self.case.runtime.performance.save_correction(
                self.case.campaign, 3, self.case.fingerprint, review["id"], "keep_comparison", "", uuid4().hex,
            )
            return self.reply(request, timeout=timeout)

        self.transport.side_effect = change_correction
        run_id = self.start()
        with self.assertRaises(PackageConflict):
            self.runtime.resume(run_id)
        self.assertEqual(self.transport.call_count, 1)
        self.assertEqual(self.runtime.read(run_id)["inference"]["state"], "received")
        self.assertIsNone(self.case.read()["review"])
        with self.assertRaises(PackageConflict):
            self.runtime.resume(run_id)
        self.assertEqual(self.transport.call_count, 1)

    def test_simultaneous_resume_cannot_dispatch_a_second_request(self):
        second_transport = Mock(side_effect=AssertionError("Second request"))
        second = self.runtime_with_transport(second_transport)
        run_id = self.start()

        def concurrent_resume(request, *, timeout):
            with self.assertRaises(ReviewInferenceError):
                second.resume(run_id, max_steps=1)
            return self.reply(request, timeout=timeout)

        self.transport.side_effect = concurrent_resume
        self.runtime.resume(run_id)
        self.assertEqual(self.transport.call_count, 1)
        second_transport.assert_not_called()
        self.assertEqual(len(self.runtime.read(run_id)["steps"]), 4)

    def test_missing_usage_is_recorded_as_unknown(self):
        self.response.pop("usage")
        self.runtime.resume(self.start())
        self.assertEqual(self.case.read()["review"]["inference"]["usage"],
                         {"input_tokens": None, "output_tokens": None, "cost_usd": None})

    def test_assessment_claims_are_generated_from_evidence(self):
        invented = "The revised version converted 100% of 500 visitors."
        self.response["choices"][0]["message"]["content"] = json.dumps({
            "kind": "insufficient_evidence", "title": "Revised version converted 100%",
            "reason": invented,
        })
        self.runtime.resume(self.start())
        review = self.case.read()["review"]
        self.assertNotIn("500", review["assessment"]["reason"])
        self.assertNotIn("100%", review["assessment"]["title"])
        self.assertIn("0 completed comparisons from 0 assigned visits", review["assessment"]["reason"])
        with closing(sqlite3.connect(self.case.path)) as db:
            stored = json.loads(db.execute("SELECT snapshot FROM instruction_test_reviews WHERE id = ?",
                                           (review["id"],)).fetchone()[0])
        self.assertEqual(stored["assessment"], review["assessment"])
        self.assertEqual(review["assessment"]["reason_code"], "insufficient_visits")
        self.assertTrue(review["assessment_verified"])

        # Earlier saved records remain auditable, but their prose is never displayed as findings.
        for kind in ("insufficient_evidence", "prepare_another_test"):
            legacy = {**stored, "assessment": {"kind": kind, "title": "100% conversion", "reason": invented}}
            legacy_id = package_fingerprint(legacy)
            with closing(sqlite3.connect(self.case.path)) as db, db:
                db.execute("INSERT INTO instruction_test_reviews VALUES (?, ?, ?, ?, ?)",
                           (legacy_id, self.case.test["id"], "local-operator", "2026-11-07T11:00:00+00:00",
                            json.dumps(legacy)))
            restored = self.case.read()
            self.assertEqual(restored["review"]["id"], legacy_id)
            self.assertEqual(restored["review"]["assessment"], review["assessment"])
            self.assertFalse(restored["review"]["assessment_verified"])
            self.assertTrue(restored["needs_review"])
            with closing(sqlite3.connect(self.case.path)) as db:
                self.assertEqual(json.loads(db.execute(
                    "SELECT snapshot FROM instruction_test_reviews WHERE id = ?", (legacy_id,),
                ).fetchone()[0]), legacy)

    def test_legacy_default_review_can_be_reverified_without_new_evidence(self):
        test_id = self.case.test["id"]
        context = self.runtime.instruction_tests.review_context(test_id)
        legacy_run = package_fingerprint({
            "actor": "local-operator", "request": REVIEW_TEST_REQUEST, "context": context,
        })[:32]
        # Reconstruct the pre-contract run identity and saved prose in the same database.
        initial_run = self.runtime.start_instruction_review(test_id)
        self.runtime.resume(initial_run)
        review_id = self.case.read()["review"]["id"]
        with closing(sqlite3.connect(self.case.path)) as db, db:
            legacy = json.loads(db.execute(
                "SELECT snapshot FROM instruction_test_reviews WHERE id = ?", (review_id,),
            ).fetchone()[0])
            legacy["assessment"] = {"kind": "insufficient_evidence", "title": "Wait",
                                    "reason": "Collect more visits."}
            legacy["inference"]["run_id"] = legacy_run
            legacy_id = package_fingerprint(legacy)
            db.execute("UPDATE instruction_test_reviews SET id = ?, snapshot = ? WHERE id = ?",
                       (legacy_id, json.dumps(legacy), review_id))
            db.execute("UPDATE agent_runs SET id = ? WHERE id = ?", (legacy_run, initial_run))
            for table in ("agent_steps", "agent_test_sources", "agent_review_inference"):
                db.execute(f"UPDATE {table} SET run_id = ? WHERE run_id = ?", (legacy_run, initial_run))
        self.assertFalse(self.case.read()["review"]["assessment_verified"])
        self.assertTrue(self.case.read()["needs_review"])

        fresh_run = self.runtime.start_instruction_review(test_id)
        self.assertNotEqual(fresh_run, legacy_run)
        self.runtime.resume(fresh_run, max_steps=2)
        reopened = self.runtime_with_transport(self.transport)
        self.assertEqual(reopened.start_instruction_review(test_id), fresh_run)
        reopened.resume(fresh_run)
        result = self.case.read()
        self.assertTrue(result["review"]["assessment_verified"])
        self.assertFalse(result["needs_review"])
        self.assertEqual(result["review"]["evidence"], context)
        self.assertEqual(reopened.start_instruction_review(test_id), fresh_run)
        reopened.resume(fresh_run)
        with closing(sqlite3.connect(self.case.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM instruction_test_reviews").fetchone()[0], 2)
            self.assertEqual(json.loads(db.execute(
                "SELECT snapshot FROM instruction_test_reviews WHERE id = ?", (legacy_id,),
            ).fetchone()[0]), legacy)
        self.assertEqual(reopened.read(legacy_run)["status"], "ready_for_review")
        self.transport.assert_not_called()

    def test_reason_codes_match_the_observed_counts(self):
        context = self.runtime.instruction_tests.review_context(self.case.test["id"])
        context["rows"] = [
            {"arm": "original", "arrivals": 20, "completions": 2, "completion_rate": 0.1},
            {"arm": "revised", "arrivals": 20, "completions": 4, "completion_rate": 0.2},
        ]
        for code in ("insufficient_visits", "revised_not_higher", "invented_winner"):
            with self.subTest(reason=code):
                with self.assertRaises(ValueError):
                    self.runtime.instruction_tests.validate_assessment(context, {"reason_code": code})
        valid = self.runtime.instruction_tests.validate_assessment(context, {"reason_code": "continue_observation"})
        self.assertEqual(valid["kind"], "keep_collecting")
        self.assertIn("2 completed comparisons from 20 assigned visits", valid["reason"])
        self.assertIn("4 completed comparisons from 20 assigned visits", valid["reason"])
        context["minimum_per_version"] = 30
        limited = self.runtime.instruction_tests.validate_assessment(context, {"reason_code": "insufficient_visits"})
        self.assertIn("Collect at least 30 assigned visits per version", limited["reason"])
