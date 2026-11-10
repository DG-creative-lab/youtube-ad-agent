from pathlib import Path
from contextlib import closing
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from campaign_agent.access import LOCAL_BRAND, Operator
from campaign_agent.agent.run import AgentRuntime, DEMO_REQUEST, RecordedInference
from campaign_agent.creatives import EXAMPLES
from campaign_agent.handoff import package_fingerprint
from campaign_agent.measurement import ViewerNotFound
from scripts.campaign_drafts import PackageConflict


class InstructionTestTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.path = directory / "draft.sqlite"
        self.media = directory / "media"
        self.media.mkdir()
        for example in EXAMPLES:
            for name in {example.preview, *(take[2] for take in example.takes)}:
                (self.media / name).write_bytes(name.encode())
        self.runtime = AgentRuntime(self.path, media_dir=self.media)
        self.drafts = self.runtime.drafts
        self.viewer = self.runtime.performance.viewer
        self.tests = self.runtime.instruction_tests
        self.campaign = self.drafts.campaign_id
        self.runtime.resume(self.runtime.start(DEMO_REQUEST))
        fingerprint = self.drafts.review_package(self.campaign, 2)["fingerprint"]
        original = self.drafts.approve_package(self.campaign, 2, fingerprint)["package"]
        content = package_fingerprint(original["groups"][0]["content"])
        for _ in range(3):
            self.viewer.open_example(EXAMPLES[0].creative_ref, content_fingerprint=content)
        review = self.runtime.performance.review(self.campaign, 2, fingerprint, "balanced")
        self.runtime.performance.save_correction(
            self.campaign, 2, fingerprint, review["id"], "keep_takes", "Preserve these readings.", uuid4().hex,
        )
        review = self.runtime.performance.review(self.campaign, 2, fingerprint, "balanced")
        self.runtime.resume(self.runtime.start_next_test(self.campaign, 2, fingerprint, review["id"]))
        self.fingerprint = self.drafts.review_package(self.campaign, 3)["fingerprint"]

    def start(self):
        self.drafts.approve_package(self.campaign, 3, self.fingerprint)
        self.test = self.tests.start(self.campaign, 3, self.fingerprint)
        return self.test

    def open(self, arm, participant=None, **kwargs):
        with patch("campaign_agent.instruction_tests.secrets.choice", return_value=arm):
            return self.tests.open(self.test["id"], participant or uuid4().hex, **kwargs)

    def complete(self, result):
        for take in ("a", "b"):
            for kind in ("start", "finish"):
                self.viewer.record(result["creative_ref"], result["visit_id"], result["example"]["ref"],
                                   uuid4().hex, kind, take)
        self.viewer.record(result["creative_ref"], result["visit_id"], result["example"]["ref"],
                           uuid4().hex, "choose", "a")

    def read(self):
        return self.tests.read(self.campaign, 3, self.fingerprint)

    def test_learning_snapshot_is_cumulative_idempotent_and_separates_assignment_sources(self):
        test = self.start()
        ref = (self.campaign, 3, self.fingerprint)
        window = 300_000
        start = 1_800_000_000_000
        participant = uuid4().hex
        with patch("campaign_agent.measurement.time_ns", return_value=start * 1_000_000):
            completed = self.open("original", participant)
            late = self.open("original")
            self.open("revised")
            missing_time = self.open("revised")
            rehearsal = self.open("original", source="rehearsal")
            fixture = self.open("original", source="fixture")
            unknown = self.open("original")
            self.complete(rehearsal)
            self.complete(fixture)
            self.complete(unknown)
            self.complete(missing_time)
            self.viewer.open_example(test["creative_version"], content_fingerprint=test["versions"][0]["content_fingerprint"])
        with closing(self.viewer.connect()) as db, db:
            db.execute("UPDATE instruction_test_assignments SET source = NULL WHERE visit_id = ?", (unknown["visit_id"],))
            db.execute("UPDATE viewer_completions SET completed_ms = NULL WHERE visit_id = ?", (missing_time["visit_id"],))
        with patch("campaign_agent.measurement.time_ns", return_value=(start + 1) * 1_000_000):
            immature = self.open("revised")
        with patch("campaign_agent.measurement.time_ns", return_value=(start + window) * 1_000_000):
            self.complete(completed)
            self.complete(immature)
        with self.assertRaisesRegex(ValueError, "separate browser reference"):
            self.open("original", participant, source="rehearsal")

        operation = uuid4().hex
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(start + window) * 1_000_000):
            first = self.tests.save_evidence_snapshot(*ref, operation)
        self.assertEqual(first["cutoff_ms"], start + window)
        self.assertIsNone(first["supersedes"])
        self.assertEqual(first["protocol"]["observation_window_ms"], window)
        self.assertEqual(first["protocol"]["eligible_source"], "participant")
        self.assertEqual((first["client_id"], first["brand_id"], first["test_id"]),
                         (LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, test["id"]))
        self.assertEqual([row["content_fingerprint"] for row in first["rows"]],
                         [version["content_fingerprint"] for version in test["versions"]])
        original, revised = (row["cohorts"] for row in first["rows"])
        self.assertEqual(original["participant"], {"mature_arrivals": 2, "completions": 1, "unresolved": 0})
        for source in ("rehearsal", "fixture", "unknown"):
            self.assertEqual(original[source], {"mature_arrivals": 1, "completions": 1, "unresolved": 0})
        self.assertEqual(revised["participant"], {"mature_arrivals": 1, "completions": 0, "unresolved": 2})

        reopened = AgentRuntime(self.path, media_dir=self.media).instruction_tests
        self.assertEqual(reopened.open(test["id"], participant)["visit_id"], completed["visit_id"])
        with patch("campaign_agent.measurement.time_ns", return_value=(start + window + 1) * 1_000_000):
            self.complete(completed)
            self.complete(late)
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(start + 2 * window) * 1_000_000):
            second = reopened.save_evidence_snapshot(*ref, uuid4().hex)
            self.assertEqual(reopened.save_evidence_snapshot(*ref, operation), first)
        self.assertEqual(second["supersedes"], first["id"])
        self.assertEqual(second["rows"][0]["cohorts"], original)
        self.assertEqual(second["rows"][1]["cohorts"]["participant"],
                         {"mature_arrivals": 2, "completions": 1, "unresolved": 1})
        self.assertEqual(reopened.read(*ref)["evidence_snapshot"], second)
        with closing(self.viewer.connect()) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM instruction_test_evidence_snapshots").fetchone()[0], 2)
            db.execute("UPDATE instruction_tests SET brand_id = 'another-brand' WHERE id = ?", (test["id"],))
        with self.assertRaises(ViewerNotFound):
            reopened.save_evidence_snapshot(*ref, operation)

    def test_legacy_assignment_keeps_unknown_source_and_legacy_test_has_no_learning_protocol(self):
        test = self.start()
        participant = uuid4().hex
        visit = self.open("revised", participant)
        self.complete(visit)
        self.complete(self.open("original"))
        with closing(self.viewer.connect()) as db, db:
            db.execute("ALTER TABLE instruction_test_assignments DROP COLUMN source")
            db.execute("UPDATE instruction_tests SET snapshot = json_remove(snapshot, '$.evidence_protocol') WHERE id = ?",
                       (test["id"],))
        reopened = AgentRuntime(self.path, media_dir=self.media).instruction_tests
        self.assertEqual(reopened.open(test["id"], participant)["visit_id"], visit["visit_id"])
        with closing(self.viewer.connect()) as db:
            self.assertIsNone(db.execute("SELECT source FROM instruction_test_assignments").fetchone()[0])
        ref = (self.campaign, 3, self.fingerprint)
        current = reopened.read(*ref)
        self.assertIsNone(current["evidence_snapshot"])
        self.assertEqual(current["unknown_source_rows"], [
            {"arm": arm, "arrivals": 1, "completions": 1, "completion_rate": 1.0}
            for arm in ("original", "revised")
        ])
        self.assertEqual([row["arrivals"] for row in current["evidence"]["rows"]], [0, 0])
        self.assertEqual(current["evidence"], reopened.review_context(test["id"]))
        with self.assertRaisesRegex(PackageConflict, "pinned observation window"):
            reopened.save_evidence_snapshot(*ref, uuid4().hex)

    def test_assignment_survives_restart_and_excludes_other_visits(self):
        test = self.start()
        self.assertEqual(self.tests.start(self.campaign, 3, self.fingerprint), test)
        for version in test["versions"]:
            self.viewer.open_example(test["creative_version"], content_fingerprint=version["content_fingerprint"])
        participant = uuid4().hex
        original = self.open("original")
        revised = self.open("revised", participant)
        self.complete(revised)
        replay = self.viewer.record(revised["creative_ref"], revised["visit_id"], revised["example"]["ref"],
                                    "e" * 32, "choose", "b")
        self.assertTrue(replay["complete"])
        reopened = AgentRuntime(self.path, media_dir=self.media)
        with patch("campaign_agent.instruction_tests.secrets.choice", side_effect=AssertionError("Reassigned")):
            resumed = reopened.instruction_tests.open(test["id"], participant)
        self.assertEqual(resumed["visit_id"], revised["visit_id"])
        self.assertEqual(resumed["example"], revised["example"])
        self.assertTrue(resumed["complete"])
        self.assertNotEqual(original["example"]["instruction"], revised["example"]["instruction"])
        self.assertEqual(resumed["examples"], [{"ref": test["comparison_version"], "title": revised["example"]["title"]}])
        self.assertEqual(self.read()["evidence"]["rows"], [
            {"arm": "original", "arrivals": 1, "completions": 0, "completion_rate": 0.0},
            {"arm": "revised", "arrivals": 1, "completions": 1, "completion_rate": 1.0},
        ])

    def test_assignment_and_viewer_arrival_roll_back_together(self):
        self.start()
        open_example = self.viewer.open_example

        def interrupted(*args, **kwargs):
            open_example(*args, **kwargs)
            raise sqlite3.OperationalError("Interrupted assignment")

        with patch.object(self.viewer, "open_example", side_effect=interrupted):
            with self.assertRaises(sqlite3.OperationalError):
                self.open("original")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM instruction_test_assignments").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM viewer_visits").fetchone()[0], 3)
        self.open("original")
        self.assertEqual(self.read()["evidence"]["rows"][0]["arrivals"], 1)

    def test_start_requires_approval_matching_media_and_current_correction(self):
        with self.assertRaisesRegex(PackageConflict, "Approve this revision"):
            self.tests.start(self.campaign, 3, self.fingerprint)
        take = self.media / EXAMPLES[0].takes[1][2]
        original = take.read_bytes()
        take.write_bytes(b"Changed recordings")
        changed = self.drafts.review_package(self.campaign, 3)["fingerprint"]
        self.drafts.approve_package(self.campaign, 3, changed)
        with self.assertRaisesRegex(PackageConflict, "only the instructions"):
            self.tests.start(self.campaign, 3, changed)
        take.write_bytes(original)
        self.drafts.approve_package(self.campaign, 3, self.fingerprint)
        package = self.drafts.review_package(self.campaign, 3)["package"]
        for _ in range(3):
            self.viewer.open_example(EXAMPLES[0].creative_ref,
                                     content_fingerprint=package_fingerprint(package["groups"][0]["content"]))
        review = self.runtime.performance.review(self.campaign, 3, self.fingerprint, "balanced")
        self.runtime.performance.save_correction(
            self.campaign, 3, self.fingerprint, review["id"], "keep_comparison", "", uuid4().hex,
        )
        with self.assertRaisesRegex(PackageConflict, "correction changed"):
            self.tests.start(self.campaign, 3, self.fingerprint)
        with self.assertRaises(ValueError):
            self.tests.start("another-campaign", 3, self.fingerprint)
        self.assertIsNone(self.read())

    def test_missing_media_preserves_assignment_and_completed_progress(self):
        self.start()
        participant = uuid4().hex
        result = self.open("revised", participant)
        self.complete(result)
        take = self.media / EXAMPLES[0].takes[1][2]
        data = take.read_bytes()
        take.unlink()
        with patch("campaign_agent.instruction_tests.secrets.choice", side_effect=AssertionError("Reassigned")):
            with self.assertRaises(PackageConflict):
                self.tests.open(self.test["id"], participant)
        take.write_bytes(data)
        resumed = self.tests.open(self.test["id"], participant)
        self.assertEqual(resumed["visit_id"], result["visit_id"])
        self.assertTrue(resumed["complete"])
        self.assertEqual(self.read()["evidence"]["rows"][1]["arrivals"], 1)

    def test_agent_review_keeps_its_evidence_and_flags_later_activity(self):
        self.start()
        run_id = self.runtime.start_instruction_review(self.test["id"])
        self.runtime.resume(run_id, max_steps=2)
        self.open("original")
        reopened = AgentRuntime(self.path, media_dir=self.media)
        save_review = reopened.instruction_tests.save_review

        def interrupted(*args, **kwargs):
            save_review(*args, **kwargs)
            raise sqlite3.OperationalError("Interrupted review commit")

        with patch.object(reopened.instruction_tests, "save_review", side_effect=interrupted):
            with self.assertRaises(sqlite3.OperationalError):
                reopened.resume(run_id, max_steps=1)
        self.assertIsNone(self.read()["review"])
        self.assertEqual(len(reopened.read(run_id)["steps"]), 2)
        result = reopened.resume(run_id)
        self.assertEqual(result["status"], "ready_for_review")
        saved = self.read()
        self.assertEqual(saved["review"]["assessment"]["kind"], "insufficient_evidence")
        self.assertEqual([row["arrivals"] for row in saved["review"]["evidence"]["rows"]], [0, 0])
        self.assertTrue(saved["needs_review"])
        next_run = reopened.start_instruction_review(self.test["id"])
        self.assertNotEqual(next_run, run_id)
        reopened.resume(next_run)
        self.assertFalse(self.read()["needs_review"])
        self.assertEqual(reopened.start_instruction_review(self.test["id"]), next_run)
        self.assertEqual(reopened.resume(next_run), reopened.read(next_run))
        other = AgentRuntime(self.path, operator=Operator("another", frozenset({LOCAL_BRAND})), media_dir=self.media)
        with self.assertRaises(PermissionError):
            other.resume(next_run)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM instruction_test_reviews").fetchone()[0], 2)

    def test_review_enforces_sample_size_and_rechecks_correction(self):
        class PrematureChange(RecordedInference):
            def assess_instruction_test(self, context):
                return {"kind": "prepare_another_test", "title": "Change wording", "reason": "Proposed change"}

        self.start()
        run_id = self.runtime.start_instruction_review(self.test["id"])
        self.runtime.model = PrematureChange()
        with self.assertRaisesRegex(ValueError, "Collect more assigned"):
            self.runtime.resume(run_id)
        self.assertEqual(len(self.runtime.read(run_id)["steps"]), 1)
        self.runtime.model = RecordedInference()
        self.runtime.resume(run_id, max_steps=1)
        for _ in range(3):
            self.open("revised")
        review = self.runtime.performance.review(self.campaign, 3, self.fingerprint, "balanced")
        self.runtime.performance.save_correction(
            self.campaign, 3, self.fingerprint, review["id"], "keep_comparison", "", uuid4().hex,
        )
        with self.assertRaisesRegex(PackageConflict, "correction changed"):
            self.runtime.resume(run_id)
        self.assertIsNone(self.read()["review"])
        self.runtime.resume(self.runtime.start_instruction_review(self.test["id"]))
        self.assertEqual(self.read()["review"]["evidence"]["correction"]["kind"], "keep_comparison")

    def test_agent_compares_both_versions_and_respects_a_new_constraint(self):
        self.start()
        for arm, completions in (("original", 4), ("revised", 2)):
            for index in range(20):
                result = self.open(arm)
                if index < completions:
                    self.complete(result)
        self.runtime.resume(self.runtime.start_instruction_review(self.test["id"]))
        self.assertEqual(self.read()["review"]["assessment"]["kind"], "prepare_another_test")
        self.assertEqual([row["completion_rate"] for row in self.read()["evidence"]["rows"]], [0.2, 0.1])
        review = self.runtime.performance.review(self.campaign, 3, self.fingerprint, "balanced")
        self.runtime.performance.save_correction(
            self.campaign, 3, self.fingerprint, review["id"], "keep_comparison", "", uuid4().hex,
        )
        self.assertTrue(self.read()["needs_review"])
        self.runtime.resume(self.runtime.start_instruction_review(self.test["id"]))
        self.assertEqual(self.read()["review"]["assessment"]["kind"], "keep_collecting")
