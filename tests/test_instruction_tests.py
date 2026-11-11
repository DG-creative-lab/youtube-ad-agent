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
from scripts.campaign_drafts import POLICY, PackageConflict


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

    def start(self, **options):
        self.drafts.approve_package(self.campaign, 3, self.fingerprint)
        self.test = self.tests.start(self.campaign, 3, self.fingerprint, **options)
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

    def test_offline_comparison_projection_matches_application_snapshot_and_native_counts(self):
        from scripts.compare_instruction_policies import evidence_at, load_spec

        self.start()
        visits = [
            {"arm": "original", "source": "participant", "arrived_ms": 0, "completed_ms": 2000},
            {"arm": "revised", "source": "participant", "arrived_ms": 0, "completed_ms": 301000},
            {"arm": "original", "source": "participant", "arrived_ms": 1000, "completed_ms": None},
            {"arm": "revised", "source": "participant", "arrived_ms": None, "completed_ms": 2000},
            {"arm": "revised", "source": "rehearsal", "arrived_ms": 0, "completed_ms": 2000},
            {"arm": "revised", "source": "fixture", "arrived_ms": 0, "completed_ms": 2000},
            {"arm": "original", "source": "unknown", "arrived_ms": 0, "completed_ms": None},
        ]
        epoch = 1_700_000_000_000
        for index, event in enumerate(visits):
            event.update(id=index, admitted_ms=event["arrived_ms"] or 0, batch=0)
            with patch("campaign_agent.measurement.time_ns", return_value=(epoch + event["admitted_ms"]) * 1_000_000):
                source = event["source"] if event["source"] != "unknown" else "participant"
                visit = self.open(event["arm"], source=source)
            if event["completed_ms"] is not None:
                with patch("campaign_agent.measurement.time_ns", return_value=(epoch + event["completed_ms"]) * 1_000_000):
                    self.complete(visit)
                    self.complete(visit)
            with closing(self.viewer.connect()) as db, db:
                if event["arrived_ms"] is None:
                    db.execute("UPDATE viewer_visits SET arrived_ms = NULL WHERE id = ?", (visit["visit_id"],))
                if event["source"] == "unknown":
                    db.execute("UPDATE instruction_test_assignments SET source = NULL WHERE visit_id = ?", (visit["visit_id"],))
        cutoff = 650000
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(epoch + cutoff) * 1_000_000):
            saved = self.tests.save_evidence_snapshot(self.campaign, 3, self.fingerprint, uuid4().hex)
        projected, native = evidence_at(load_spec(), visits, cutoff)
        self.assertEqual([row["cohorts"] for row in saved["rows"]], [row["cohorts"] for row in projected["rows"]])
        actual = [{key: row[key] for key in ("arm", "arrivals", "completions")} for row in self.read()["evidence"]["rows"]]
        self.assertEqual(actual, native)

    def save_reuse_finding(self):
        self.start(allow_additional_batch=True)
        arrival = 1_800_000_000_000
        with patch("campaign_agent.measurement.time_ns", return_value=arrival * 1_000_000):
            for arm, completions in (("original", 2), ("revised", 18)):
                for index in range(20):
                    visit = self.open(arm)
                    if index < completions:
                        self.complete(visit)
        self.source_ref = (self.campaign, 3, self.fingerprint)
        self.finding_cutoff = arrival + 300_000
        with patch("campaign_agent.instruction_tests.time_ns", return_value=self.finding_cutoff * 1_000_000):
            snapshot = self.tests.save_evidence_snapshot(*self.source_ref, uuid4().hex)
        return self.runtime.instruction_findings.save(*self.source_ref, snapshot_id=snapshot["id"])

    def fresh_brief(self, context="video-editing"):
        current = self.drafts.read()
        review = self.drafts.review_package(self.campaign, current["revision"])
        brief = self.drafts.start_brief(
            self.campaign, current["revision"], review["fingerprint"],
            title="Fresh narration brief", goal="Evaluate the next narration campaign.", context=context,
        )
        fingerprint = self.drafts.review_package(self.campaign, brief["revision"])["fingerprint"]
        return self.campaign, brief["revision"], fingerprint

    def test_finding_reuses_exact_tested_wording_after_restart_and_requires_package_approval(self):
        finding = self.save_reuse_finding()
        self.assertEqual(self.runtime.instruction_findings.save(*self.source_ref, snapshot_id=finding["snapshot_id"]),
                         finding)
        target = self.fresh_brief()
        reopened = AgentRuntime(self.path, media_dir=self.media)
        eligible = reopened.instruction_findings.read(*target)
        self.assertEqual(eligible["finding"], finding)
        self.assertEqual([(arm["completions"], arm["mature_arrivals"]) for arm in finding["decision"]["arms"]],
                         [(2, 20), (18, 20)])
        old = reopened.drafts.review_package(*target[:2])["package"]
        self.assertNotEqual(old["brief"], finding["source_brief"])
        self.assertEqual(old["groups"][0]["content"]["instruction"], finding["before"])
        request = {"finding_id": finding["id"], "correction_id": eligible["correction"]["id"],
                   "draft_permission": "instruction_test"}
        saved = reopened.instruction_findings.apply(*target, **request)
        reviewed = reopened.drafts.review_package(self.campaign, saved["revision"])
        self.assertEqual(saved["revision"], target[1] + 1)
        self.assertEqual(reviewed["package"]["instruction_reuse"], eligible)
        self.assertEqual(reviewed["package"]["groups"][0]["content"],
                         {**old["groups"][0]["content"], "instruction": finding["after"]})
        self.assertEqual(saved["placements"], self.drafts.read(target[1])["placements"])
        self.assertIsNone(reviewed["approval"])
        with self.assertRaisesRegex(PackageConflict, "Approve this revision"):
            reopened.drafts.export_setup(self.campaign, saved["revision"], reviewed["fingerprint"])
        with self.assertRaisesRegex(PackageConflict, "package has changed"):
            reopened.instruction_findings.apply(*target, **request)
        self.assertIsNone(self.drafts.read(saved["revision"] + 1))

    def test_matching_brief_denies_writes_without_instruction_permission_or_current_policy(self):
        finding = self.save_reuse_finding()
        target = self.fresh_brief()
        service = self.runtime.instruction_findings
        correction_id = service.read(*target)["correction"]["id"]
        request = {"finding_id": finding["id"], "correction_id": correction_id}
        with self.assertRaises(PermissionError):
            service.apply(*target, **request)
        with self.assertRaises(PermissionError):
            service.apply(*target, **request, draft_permission="placements")
        with patch("campaign_agent.learning.POLICY", {**POLICY, "revision": POLICY["revision"] + 1}):
            self.assertIsNone(service.read(*target))
            with self.assertRaises(PackageConflict):
                service.apply(*target, **request, draft_permission="instruction_test")
        self.drafts.approve_package(*target)
        review = self.runtime.performance.review(*target, "balanced")
        self.runtime.performance.save_correction(
            *target, review["id"], "keep_comparison", "Preserve the full comparison.", uuid4().hex,
        )
        self.assertIsNone(service.read(*target))
        with self.assertRaises(PackageConflict):
            service.apply(*target, **request, draft_permission="instruction_test")
        self.assertIsNone(self.drafts.read(target[1] + 1))

    def test_matching_brief_rejects_a_finding_after_new_participant_evidence(self):
        finding = self.save_reuse_finding()
        target = self.fresh_brief()
        service = self.runtime.instruction_findings
        correction_id = service.read(*target)["correction"]["id"]
        self.open("original", source="rehearsal")
        self.assertIsNotNone(service.read(*target))
        self.open("original")
        self.assertEqual(self.read()["evidence_decision"]["action"], "refresh_snapshot")
        self.assertIsNone(service.read(*target))
        with self.assertRaises(PackageConflict):
            service.apply(*target, finding_id=finding["id"], correction_id=correction_id,
                          draft_permission="instruction_test")
        self.assertIsNone(self.drafts.read(target[1] + 1))

    def test_mismatched_context_and_brand_cannot_retrieve_or_apply_finding(self):
        finding = self.save_reuse_finding()
        editing = self.fresh_brief()
        service = self.runtime.instruction_findings
        correction_id = service.read(*editing)["correction"]["id"]
        audiobook = self.fresh_brief("audiobook")
        request = {"finding_id": finding["id"], "correction_id": correction_id, "draft_permission": "instruction_test"}
        self.assertIsNone(service.read(*audiobook))
        with self.assertRaises(PackageConflict):
            service.apply(*audiobook, **request)
        self.assertIsNone(self.drafts.read(audiobook[1] + 1))
        editing = self.fresh_brief()
        preview = self.media / EXAMPLES[0].preview
        original_media = preview.read_bytes()
        preview.write_bytes(b"different preview")
        changed = (*editing[:2], self.drafts.review_package(*editing[:2])["fingerprint"])
        self.assertIsNone(service.read(*changed))
        with self.assertRaises(PackageConflict):
            service.apply(*changed, **request)
        preview.write_bytes(original_media)
        self.assertEqual(service.read(*editing)["finding"], finding)
        with closing(self.viewer.connect()) as db, db:
            db.execute("UPDATE instruction_findings SET brand_id = 'another-brand' WHERE id = ?", (finding["id"],))
        self.assertIsNone(service.read(*editing))
        with self.assertRaises(PackageConflict):
            service.apply(*editing, **request)
        self.assertIsNone(self.drafts.read(editing[1] + 1))

    def test_superseded_and_retired_findings_do_not_revive(self):
        old = self.save_reuse_finding()
        service = self.runtime.instruction_findings
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(self.finding_cutoff + 1) * 1_000_000):
            new_snapshot = self.tests.save_evidence_snapshot(*self.source_ref, uuid4().hex)
        with self.assertRaisesRegex(PackageConflict, "current snapshot"):
            service.save(*self.source_ref, snapshot_id=old["snapshot_id"])
        new = service.save(*self.source_ref, snapshot_id=new_snapshot["id"])
        target = self.fresh_brief()
        eligible = service.read(*target)
        self.assertEqual(eligible["finding"]["id"], new["id"])
        request = {"correction_id": eligible["correction"]["id"], "draft_permission": "instruction_test"}
        with self.assertRaises(PackageConflict):
            service.apply(*target, finding_id=old["id"], **request)
        service.retire(*target, finding_id=new["id"])
        reopened = AgentRuntime(self.path, media_dir=self.media).instruction_findings
        self.assertIsNone(reopened.read(*target))
        for finding_id in (old["id"], new["id"]):
            with self.assertRaises(PackageConflict):
                reopened.apply(*target, finding_id=finding_id, **request)
        self.assertIsNone(self.drafts.read(target[1] + 1))

    def test_saved_decision_uses_pinned_allowance_and_stops_at_sample_cap(self):
        test = self.start(allow_additional_batch=True)
        ref = (self.campaign, 3, self.fingerprint)
        self.assertEqual(self.tests.start(*ref, allow_additional_batch=True), test)
        with self.assertRaisesRegex(PackageConflict, "pinned batch allowance"):
            self.tests.start(*ref, allow_additional_batch=False)
        self.assertIsNone(self.read()["evidence_decision"])

        start = 1_800_000_000_000
        with patch("campaign_agent.measurement.time_ns", return_value=start * 1_000_000):
            for arm, completions in (("original", 6), ("revised", 10)):
                for index in range(20):
                    visit = self.open(arm)
                    if index < completions:
                        self.complete(visit)
                self.complete(self.open(arm, source="fixture"))
        cutoff = start + 300_000
        operation = uuid4().hex
        with patch("campaign_agent.instruction_tests.time_ns", return_value=cutoff * 1_000_000):
            first = self.tests.save_evidence_snapshot(*ref, operation)
        recommendation = self.read()["evidence_decision"]
        self.assertEqual(recommendation["snapshot_id"], first["id"])
        self.assertEqual((recommendation["action"], recommendation["assigned"], recommendation["sample_cap"]),
                         ("collect", 40, 50))
        self.assertGreater(recommendation["batch_gain"], recommendation["policy"]["batch_cost"])
        reopened = AgentRuntime(self.path, media_dir=self.media).instruction_tests
        self.assertEqual(reopened.save_evidence_snapshot(*ref, operation), first)
        self.assertEqual(reopened.read(*ref)["evidence_decision"], recommendation)
        with patch("campaign_agent.instruction_tests.time_ns", return_value=cutoff * 1_000_000):
            second = reopened.save_evidence_snapshot(*ref, uuid4().hex)
        self.assertEqual(reopened.read(*ref)["evidence_decision"], {**recommendation, "snapshot_id": second["id"]})

        with patch("campaign_agent.measurement.time_ns", return_value=(cutoff + 1) * 1_000_000):
            self.open("original")
        self.assertEqual(reopened.read(*ref)["evidence_decision"]["action"], "refresh_snapshot")
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(cutoff + 2) * 1_000_000):
            reopened.save_evidence_snapshot(*ref, uuid4().hex)
        after = reopened.read(*ref)["evidence_decision"]
        self.assertEqual((after["action"], after["assigned"], after["batch_remaining"]), ("continue_batch", 41, 9))
        self.assertIsNone(after["batch_gain"])
        self.assertEqual(after["batch_checkpoint_id"], second["id"])

        batch_arrival = cutoff + 3
        with patch("campaign_agent.measurement.time_ns", return_value=batch_arrival * 1_000_000):
            for _ in range(9):
                self.open("revised")
        self.assertEqual(reopened.read(*ref)["evidence_decision"]["action"], "refresh_snapshot")
        with patch("campaign_agent.instruction_tests.time_ns", return_value=batch_arrival * 1_000_000):
            reopened.save_evidence_snapshot(*ref, uuid4().hex)
        pending = reopened.read(*ref)["evidence_decision"]
        self.assertEqual((pending["action"], pending["assigned"], pending["batch_remaining"]), ("wait_batch", 50, 0))
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(batch_arrival + 300_000) * 1_000_000):
            reopened.save_evidence_snapshot(*ref, uuid4().hex)
        final = reopened.read(*ref)["evidence_decision"]
        self.assertEqual((final["action"], final["batch_status"]), ("keep", "sample_cap"))
        self.assertIsNone(final["batch_gain"])
        self.assertIsNone(self.drafts.read(4))

    def test_arrivals_before_initial_outcomes_resolve_do_not_start_batch(self):
        self.start(allow_additional_batch=True)
        ref = (self.campaign, 3, self.fingerprint)
        arrival = 1_800_000_000_000
        with patch("campaign_agent.measurement.time_ns", return_value=arrival * 1_000_000):
            for arm, completions in (("original", 6), ("revised", 10)):
                for index in range(20):
                    visit = self.open(arm)
                    if index < completions:
                        self.complete(visit)
        with patch("campaign_agent.instruction_tests.time_ns", return_value=arrival * 1_000_000):
            self.tests.save_evidence_snapshot(*ref, uuid4().hex)
        decision = self.read()["evidence_decision"]
        self.assertEqual((decision["action"], decision["assigned"]), ("wait_for_evidence", 40))
        with patch("campaign_agent.measurement.time_ns", return_value=(arrival + 1) * 1_000_000):
            self.open("original")
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(arrival + 1) * 1_000_000):
            self.tests.save_evidence_snapshot(*ref, uuid4().hex)
        decision = self.read()["evidence_decision"]
        self.assertEqual((decision["action"], decision["assigned"]), ("wait_for_evidence", 41))
        self.assertIsNone(decision["batch_remaining"])
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(arrival + 300_000) * 1_000_000):
            self.tests.save_evidence_snapshot(*ref, uuid4().hex)
        decision = self.read()["evidence_decision"]
        self.assertEqual((decision["action"], decision["batch_status"]), ("wait_for_evidence", "no_batch_recommendation"))
        self.assertIsNone(decision["batch_checkpoint_id"])
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(arrival + 300_001) * 1_000_000):
            self.tests.save_evidence_snapshot(*ref, uuid4().hex)
        self.assertEqual(self.read()["evidence_decision"]["action"], "keep")

    def test_arrivals_after_keep_decision_do_not_start_batch(self):
        self.start(allow_additional_batch=True)
        ref = (self.campaign, 3, self.fingerprint)
        arrival = 1_800_000_000_000
        with patch("campaign_agent.measurement.time_ns", return_value=arrival * 1_000_000):
            for arm in ("original", "revised"):
                for _ in range(20):
                    self.open(arm)
        cutoff = arrival + 300_000
        with patch("campaign_agent.instruction_tests.time_ns", return_value=cutoff * 1_000_000):
            self.tests.save_evidence_snapshot(*ref, uuid4().hex)
        decision = self.read()["evidence_decision"]
        self.assertEqual((decision["action"], decision["batch_status"]), ("keep", "evaluated"))
        with patch("campaign_agent.measurement.time_ns", return_value=(cutoff + 1) * 1_000_000):
            self.open("original")
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(cutoff + 2) * 1_000_000):
            self.tests.save_evidence_snapshot(*ref, uuid4().hex)
        decision = self.read()["evidence_decision"]
        self.assertEqual((decision["action"], decision["batch_status"]), ("wait_for_evidence", "no_batch_recommendation"))
        self.assertIsNone(decision["batch_remaining"])
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(cutoff + 300_001) * 1_000_000):
            self.tests.save_evidence_snapshot(*ref, uuid4().hex)
        self.assertEqual(self.read()["evidence_decision"]["action"], "keep")

    def test_first_snapshot_at_sample_cap_reports_missing_batch_checkpoint(self):
        self.start(allow_additional_batch=True)
        ref = (self.campaign, 3, self.fingerprint)
        arrival = 1_800_000_000_000
        with patch("campaign_agent.measurement.time_ns", return_value=arrival * 1_000_000):
            for arm, completions in (("original", 2), ("revised", 20)):
                for index in range(25):
                    visit = self.open(arm)
                    if index < completions:
                        self.complete(visit)
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(arrival + 300_000) * 1_000_000):
            snapshot = self.tests.save_evidence_snapshot(*ref, uuid4().hex)
        self.assertIsNone(snapshot["supersedes"])
        decision = self.read()["evidence_decision"]
        self.assertEqual((decision["assigned"], decision["sample_cap"]), (50, 50))
        self.assertEqual((decision["action"], decision["batch_status"]), ("reuse", "no_batch_recommendation"))
        self.assertIsNone(decision["batch_checkpoint_id"])
        self.assertIsNone(decision["batch_gain"])

    def test_snapshot_from_pre_policy_test_remains_readable_without_recommendation(self):
        test = self.start()
        with closing(self.viewer.connect()) as db, db:
            db.execute(
                "UPDATE instruction_tests SET snapshot = json_remove(snapshot, "
                "'$.evidence_protocol.decision_policy', '$.evidence_protocol.sample_cap') WHERE id = ?",
                (test["id"],),
            )
        self.complete(self.open("revised"))
        ref = (self.campaign, 3, self.fingerprint)
        snapshot = self.tests.save_evidence_snapshot(*ref, uuid4().hex)
        self.assertNotIn("decision_policy", snapshot["protocol"])
        reopened = AgentRuntime(self.path, media_dir=self.media).instruction_tests.read(*ref)
        self.assertEqual(reopened["evidence_snapshot"], snapshot)
        self.assertEqual(reopened["evidence_decision"], {
            "snapshot_id": snapshot["id"], "action": "unavailable", "reason": "unpinned_policy",
        })

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
