"""Pinned instruction experiments, stable assignments and evidence-backed assessments."""

from contextlib import closing
from datetime import datetime, timezone
import json
import re
import secrets
from time import time_ns

from .access import LOCAL_BRAND
from .handoff import package_fingerprint
from .instruction_policy import ADDITIONAL_BATCH_SIZE, POLICY_V1, SAMPLE_CAP, recommend_instruction_action
from .measurement import ViewerNotFound
from scripts.campaign_drafts import PackageConflict


MIN_TEST_ARRIVALS = 20
EVIDENCE_PROTOCOL = {
    "version": 1, "assignment_unit": "browser_visit",
    "metric": "completed_comparison_per_assigned_visit",
    "observation_window_ms": 5 * 60 * 1000, "additional_batch_size": None,
    "eligible_source": "participant",
}
ASSIGNMENT_SOURCES = ("participant", "rehearsal", "fixture")
# Bump when saved assessments need reverification under a changed acceptance contract.
ASSESSMENT_VERSION = "evidence-reasons-v2"
ASSESSMENT_REASONS = {
    "insufficient_visits": ("insufficient_evidence", "Insufficient evidence"),
    "continue_observation": ("keep_collecting", "Keep collecting evidence"),
    "revised_not_higher": ("prepare_another_test", "Consider another instruction test"),
}
LEGACY_REASON_CODES = {kind: code for code, (kind, _title) in ASSESSMENT_REASONS.items()}


def recorded_assessment(context):
    """Authored offline decision shared by the workspace and chat simulators."""
    original, revised = context["rows"]
    if any(row["arrivals"] < context["minimum_per_version"] for row in (original, revised)):
        return {"reason_code": "insufficient_visits"}
    if (revised["completions"] * original["arrivals"] <= original["completions"] * revised["arrivals"]
            and context["correction"] and context["correction"]["kind"] == "keep_takes"):
        return {"reason_code": "revised_not_higher"}
    return {"reason_code": "continue_observation"}


class InstructionTests:
    def __init__(self, drafts, viewer, performance):
        self.drafts = drafts
        self.viewer = viewer
        self.performance = performance
        with closing(viewer.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS instruction_tests (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                    started_at TEXT NOT NULL, snapshot TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS instruction_test_assignments (
                    test_id TEXT NOT NULL REFERENCES instruction_tests(id),
                    participant_id TEXT NOT NULL, arm TEXT NOT NULL CHECK (arm IN ('original', 'revised')),
                    visit_id TEXT NOT NULL UNIQUE REFERENCES viewer_visits(id),
                    source TEXT CHECK (source IN ('participant', 'rehearsal', 'fixture')),
                    PRIMARY KEY (test_id, participant_id)
                );
                CREATE TABLE IF NOT EXISTS instruction_test_reviews (
                    id TEXT PRIMARY KEY, test_id TEXT NOT NULL REFERENCES instruction_tests(id),
                    actor_id TEXT NOT NULL, created_at TEXT NOT NULL, snapshot TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS instruction_test_evidence_snapshots (
                    id TEXT PRIMARY KEY, test_id TEXT NOT NULL REFERENCES instruction_tests(id),
                    operation_id TEXT NOT NULL, snapshot TEXT NOT NULL,
                    UNIQUE (test_id, operation_id)
                );
            """)
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(instruction_test_assignments)")}
            if "source" not in columns:
                db.execute("ALTER TABLE instruction_test_assignments ADD COLUMN source TEXT "
                           "CHECK (source IN ('participant', 'rehearsal', 'fixture'))")

    @staticmethod
    def test_id(campaign_id, revision, fingerprint, scope=LOCAL_BRAND):
        return package_fingerprint({"scope": vars(scope), "campaign": campaign_id,
                                    "revision": revision, "fingerprint": fingerprint})[:32]

    def started_for_package(self, db, package):
        self.drafts._package_scope(package['campaign_id'], package['revision'])
        test_id = self.test_id(package['campaign_id'], package['revision'], package_fingerprint(package), self.drafts.scope)
        return test_id if db.execute('SELECT 1 FROM instruction_tests WHERE id=? AND client_id=? AND brand_id=?',
                                     (test_id, self.drafts.scope.client_id, self.drafts.scope.brand_id)).fetchone() else None

    def _test(self, db, test_id):
        if not isinstance(test_id, str) or not re.fullmatch(r"[0-9a-f]{32}", test_id):
            raise ValueError("Choose a valid instruction test.")
        row = db.execute(
            "SELECT snapshot FROM instruction_tests WHERE id = ? AND client_id = ? AND brand_id = ? "
            "AND campaign_id = ?",
            (test_id, self.drafts.scope.client_id, self.drafts.scope.brand_id, self.drafts.campaign_id),
        ).fetchone()
        if row is None:
            raise ViewerNotFound("This instruction test is unavailable.")
        return json.loads(row[0])

    def _verify_media(self, test):
        example = self.viewer.resolve(test["creative_version"], test["comparison_version"])[1]
        for arm in test["versions"]:
            content = self.drafts.comparison_content(example, arm["content_fingerprint"])
            if content != arm["content"] or any(not take["sha256"] for take in content["takes"]):
                raise PackageConflict("The test media has changed or is unavailable. Restore the reviewed media to continue.")

    def start(self, campaign_id, revision, fingerprint, *, allow_additional_batch=None):
        self.drafts.require("youtube:review.write")
        self.drafts._package_scope(campaign_id, revision)
        if allow_additional_batch is not None and type(allow_additional_batch) is not bool:
            raise ValueError("Choose whether to allow an additional batch.")
        test_id = self.test_id(campaign_id, revision, fingerprint, self.drafts.scope)
        with closing(self.viewer.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT id FROM instruction_tests WHERE id = ?", (test_id,)).fetchone()
            if existing:
                test = self._test(db, test_id)
                allowed = bool(test.get("evidence_protocol", {}).get("additional_batch_size"))
                if allow_additional_batch is not None and allowed != allow_additional_batch:
                    raise PackageConflict("This test already has a pinned batch allowance. Refresh the test results.")
                return test
            package = self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)["package"]
            prepared = package.get("instruction_test")
            if prepared is None:
                raise ValueError("Prepare and approve an instruction test first.")
            original = db.execute(
                "SELECT snapshot FROM campaign_package_approvals WHERE client_id = ? AND brand_id = ? "
                "AND campaign_id = ? AND revision = ? AND fingerprint = ? AND snapshot IS NOT NULL",
                (self.drafts.scope.client_id, self.drafts.scope.brand_id, campaign_id,
                 prepared["source_revision"], prepared["source_fingerprint"]),
            ).fetchone()
            if original is None:
                raise PackageConflict("The original approved comparison is unavailable.")
            creative = prepared["creative_version"]
            old = next(group for group in json.loads(original[0])["groups"] if group["creative_version"] == creative)
            new = next(group for group in package["groups"] if group["creative_version"] == creative)
            if (old["comparison_version"] != new["comparison_version"]
                    or old["content"]["instruction"] == new["content"]["instruction"]
                    or {**old["content"], "instruction": new["content"]["instruction"]} != new["content"]):
                raise PackageConflict("This test requires the same media and comparison with only the instructions changed.")
            correction = self.performance.correction_for_comparison(db, package, creative)
            if correction != prepared["correction"] or correction["kind"] != "keep_takes":
                raise PackageConflict("The buyer correction changed. Prepare a test from a current review.")
            test = {
                "id": test_id, "campaign_id": campaign_id, "revision": revision, "fingerprint": fingerprint,
                "started_at": datetime.now(timezone.utc).isoformat(), "package": package,
                "creative_version": creative, "comparison_version": new["comparison_version"],
                "source_review_id": prepared["review_id"], "source_correction": correction,
                "viewer_path": "/viewer?test=" + test_id,
                "evidence_protocol": {
                    **EVIDENCE_PROTOCOL, "decision_policy": POLICY_V1.copy(),
                    "additional_batch_size": ADDITIONAL_BATCH_SIZE if allow_additional_batch else None,
                    "sample_cap": SAMPLE_CAP if allow_additional_batch else None,
                },
                "versions": [
                    {"arm": arm, "revision": arm_revision, "content": group["content"],
                     "content_fingerprint": package_fingerprint(group["content"])}
                    for arm, arm_revision, group in (
                        ("original", prepared["source_revision"], old), ("revised", revision, new),
                    )
                ],
            }
            self._verify_media(test)
            self.drafts.require("youtube:review.write")
            db.execute("INSERT INTO instruction_tests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (test_id, self.drafts.scope.client_id, self.drafts.scope.brand_id, campaign_id,
                        revision, fingerprint, test["started_at"], json.dumps(test)))
        return test

    def open(self, test_id, participant_id, *, source="participant"):
        if not isinstance(participant_id, str) or not re.fullmatch(r"[0-9a-f]{32}", participant_id):
            raise ValueError("Use a valid participant reference.")
        if source not in ASSIGNMENT_SOURCES:
            raise ValueError("Use a valid assignment source.")
        with closing(self.viewer.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            test = self._test(db, test_id)
            self._verify_media(test)
            row = db.execute(
                "SELECT arm, visit_id, source FROM instruction_test_assignments WHERE test_id = ? AND participant_id = ?",
                (test_id, participant_id),
            ).fetchone()
            if row and row[2] is not None and row[2] != source:
                raise ValueError("Use a separate browser reference for each assignment source.")
            arm, visit_id = row[:2] if row else (secrets.choice(("original", "revised")), None)
            version = next(version for version in test["versions"] if version["arm"] == arm)
            result = self.viewer.open_example(
                test["creative_version"], test["comparison_version"], visit_id,
                content_fingerprint=version["content_fingerprint"], connection=db,
            )
            if row is None:
                db.execute("INSERT INTO instruction_test_assignments (test_id, participant_id, arm, visit_id, source) "
                           "VALUES (?, ?, ?, ?, ?)", (test_id, participant_id, arm, result["visit_id"], source))
            result["creative_ref"] = test["creative_version"]
            result["example"]["instruction"] = version["content"]["instruction"]
            result["examples"] = [item for item in result["examples"] if item["ref"] == test["comparison_version"]]
            for take, content in zip(result["example"]["takes"], version["content"]["takes"]):
                take["url"] += "?sha256=" + content["sha256"]
            result["example"]["captions"] += "?sha256=" + version["content"]["captions_sha256"]
            return result

    @staticmethod
    def _latest_snapshot(db, test_id):
        row = db.execute("SELECT snapshot FROM instruction_test_evidence_snapshots WHERE test_id = ? "
                         "ORDER BY rowid DESC LIMIT 1", (test_id,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _initial_batch_checkpoint(db, snapshot):
        protocol = snapshot["protocol"]
        size = protocol.get("additional_batch_size")
        if not size or not protocol.get("decision_policy") or not snapshot["supersedes"]:
            return None
        initial = protocol["sample_cap"] - size
        counts = (row["cohorts"]["participant"] for row in snapshot["rows"])
        if sum(count["mature_arrivals"] + count["unresolved"] for count in counts) <= initial:
            return None
        # Use the saved review point, rather than reconstructing it from later outcomes.
        row = db.execute("""
            SELECT s.snapshot FROM instruction_test_evidence_snapshots s
            WHERE s.test_id = ? AND (?, 0) = (
                SELECT SUM(json_extract(value, '$.cohorts.participant.mature_arrivals')),
                       SUM(json_extract(value, '$.cohorts.participant.unresolved'))
                FROM json_each(s.snapshot, '$.rows')
            )
            ORDER BY s.rowid DESC LIMIT 1
        """, (snapshot["test_id"], initial)).fetchone()
        checkpoint = json.loads(row[0]) if row else None
        return checkpoint if checkpoint and checkpoint["protocol"] == protocol else None

    def save_evidence_snapshot(self, campaign_id, revision, fingerprint, operation_id):
        self.drafts.require("youtube:review.write")
        self.drafts._package_scope(campaign_id, revision)
        if not isinstance(operation_id, str) or not re.fullmatch(r"[0-9a-f]{32}", operation_id):
            raise ValueError("Use a valid evidence operation reference.")
        test_id = self.test_id(campaign_id, revision, fingerprint, self.drafts.scope)
        with closing(self.viewer.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            test = self._test(db, test_id)
            existing = db.execute("SELECT snapshot FROM instruction_test_evidence_snapshots "
                                  "WHERE test_id = ? AND operation_id = ?", (test_id, operation_id)).fetchone()
            if existing:
                return json.loads(existing[0])
            self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)
            protocol = test.get("evidence_protocol")
            if protocol is None:
                raise PackageConflict("Start a new instruction test with a pinned observation window to save learning evidence.")
            cutoff = time_ns() // 1_000_000
            previous = self._latest_snapshot(db, test_id)
            if previous and cutoff < previous["cutoff_ms"]:
                raise PackageConflict("The server clock is earlier than the latest evidence cutoff. Try again later.")
            snapshot = {
                "test_id": test_id, **vars(self.drafts.scope), "campaign_id": campaign_id,
                "revision": revision, "fingerprint": fingerprint, "protocol": protocol,
                "creative_version": test["creative_version"], "comparison_version": test["comparison_version"],
                "cutoff_ms": cutoff, "supersedes": previous["id"] if previous else None,
                "rows": self._snapshot_rows(db, test, protocol["observation_window_ms"], cutoff),
            }
            snapshot["id"] = package_fingerprint({"test_id": test_id, "operation_id": operation_id})
            self.drafts.require("youtube:review.write")
            db.execute("INSERT INTO instruction_test_evidence_snapshots VALUES (?, ?, ?, ?)",
                       (snapshot["id"], test_id, operation_id, json.dumps(snapshot)))
        return snapshot

    def _snapshot_rows(self, db, test, window_ms, cutoff):
        rows = []
        for version in test["versions"]:
            # An assignment and its first completion each have a unique visit key.
            outcomes = db.execute("""
                WITH assigned AS (
                    SELECT a.source,
                           CASE WHEN v.arrived_ms IS NULL OR v.arrived_ms + :window > :cutoff
                                  OR NOT EXISTS (SELECT 1 FROM viewer_events e WHERE e.visit_id = v.id
                                                 AND e.kind = 'arrival' AND e.example_ref = :example)
                                  OR (c.visit_id IS NOT NULL AND
                                      (c.completed_ms IS NULL OR c.completed_ms < v.arrived_ms)) THEN NULL
                                WHEN c.completed_ms <= v.arrived_ms + :window THEN 1
                                ELSE 0 END AS completed
                    FROM instruction_test_assignments a JOIN viewer_visits v ON v.id = a.visit_id
                    LEFT JOIN viewer_completions c ON c.visit_id = v.id AND c.example_ref = :example
                    WHERE a.test_id = :test AND a.arm = :arm AND v.client_id = :client AND v.brand_id = :brand
                      AND v.campaign_id = :campaign
                      AND v.creative_ref = :creative AND v.content_fingerprint = :content
                      AND (v.arrived_ms IS NULL OR v.arrived_ms <= :cutoff)
                )
                SELECT source, COUNT(completed), COALESCE(SUM(completed), 0), COUNT(*) - COUNT(completed)
                FROM assigned GROUP BY source
            """, {"window": window_ms, "cutoff": cutoff, "example": test["comparison_version"],
                  "test": test["id"], "arm": version["arm"], "client": self.drafts.scope.client_id,
                  "brand": self.drafts.scope.brand_id, "campaign": self.drafts.campaign_id, "creative": test["creative_version"],
                  "content": version["content_fingerprint"]})
            cohorts = {source: {"mature_arrivals": 0, "completions": 0, "unresolved": 0}
                       for source in (*ASSIGNMENT_SOURCES, "unknown")}
            for source, mature, completed, unresolved in outcomes:
                cohorts[source or "unknown"] = {"mature_arrivals": mature, "completions": completed,
                                                 "unresolved": unresolved}
            rows.append({"arm": version["arm"], "revision": version["revision"],
                         "content_fingerprint": version["content_fingerprint"], "cohorts": cohorts})
        return rows

    def _assignment_rows(self, db, test, source):
        rows = []
        for version in test["versions"]:
            arrivals, completions = db.execute("""
                SELECT COUNT(*), COUNT(CASE WHEN EXISTS (
                    SELECT 1 FROM viewer_completions c WHERE c.visit_id = v.id AND c.example_ref = ?
                ) THEN 1 END)
                FROM instruction_test_assignments a JOIN viewer_visits v ON v.id = a.visit_id
                WHERE a.test_id = ? AND a.arm = ? AND v.client_id = ? AND v.brand_id = ?
                    AND v.campaign_id = ? AND a.source IS ?
                    AND v.creative_ref = ? AND v.content_fingerprint = ?
                    AND EXISTS (SELECT 1 FROM viewer_events e WHERE e.visit_id = v.id
                                AND e.kind = 'arrival' AND e.example_ref = ?)
            """, (test["comparison_version"], test["id"], version["arm"], self.drafts.scope.client_id,
                  self.drafts.scope.brand_id, self.drafts.campaign_id, source, test["creative_version"], version["content_fingerprint"],
                  test["comparison_version"])).fetchone()
            rows.append({"arm": version["arm"], "arrivals": arrivals, "completions": completions,
                         "completion_rate": completions / arrivals if arrivals else None})
        return rows

    def _evidence(self, db, test):
        through_event, = db.execute(
            "SELECT COALESCE(MAX(e.seq), 0) FROM viewer_events e JOIN instruction_test_assignments a "
            "ON a.visit_id = e.visit_id WHERE a.test_id = ? AND a.source = 'participant'", (test["id"],),
        ).fetchone()
        return {
            "test_id": test["id"], "campaign_id": test["campaign_id"],
            "revision": test["revision"], "fingerprint": test["fingerprint"],
            "versions": test["versions"], "rows": self._assignment_rows(db, test, "participant"),
            "started_at": test["started_at"], "through_event": through_event, "assignment_source": "participant",
            "minimum_per_version": MIN_TEST_ARRIVALS,
            "correction": self.performance.correction_for_comparison(db, test["package"], test["creative_version"]),
        }

    def review_context(self, test_id, *, connection=None):
        self.drafts.require("youtube:campaign.read")
        if connection is not None:
            return self._evidence(connection, self._test(connection, test_id))
        with closing(self.viewer.connect()) as db:
            db.execute("BEGIN")
            test = self._test(db, test_id)
            return self._evidence(db, test)

    def require_review_context(self, db, context):
        self.drafts.require("youtube:campaign.read")
        if context.get("assignment_source") != "participant":
            raise PackageConflict("Review the instruction test again using participant visits.")
        test = self._test(db, context["test_id"])
        current = self.performance.correction_for_comparison(db, test["package"], test["creative_version"])
        if current != context["correction"]:
            raise PackageConflict("The buyer correction changed. Review the instruction test again.")

    def save_review(self, db, context, assessment, *, inference=None):
        self.drafts.require("youtube:review.write")
        self.require_review_context(db, context)
        assessment = self.validate_assessment(context, assessment)
        review = {"evidence": context, "assessment": assessment}
        if inference is not None:
            review["inference"] = inference
        review_id = package_fingerprint(review)
        db.execute(
            "INSERT INTO instruction_test_reviews VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (review_id, context["test_id"], self.drafts.operator.id, datetime.now(timezone.utc).isoformat(), json.dumps(review)),
        )
        return {"id": review_id, **review}

    def next_test_context(self, db, test_id, review_id):
        """Validate a current experiment assessment and pin the approved revised arm as baseline."""
        self.drafts.require("youtube:campaign.read")
        test = self._test(db, test_id)
        row = db.execute(
            "SELECT id, snapshot FROM instruction_test_reviews WHERE test_id = ? ORDER BY rowid DESC LIMIT 1",
            (test_id,),
        ).fetchone()
        if row is None or row[0] != review_id:
            raise PackageConflict("Choose the latest saved assessment for this instruction test.")
        saved = json.loads(row[1])
        try:
            assessment = self.validate_assessment(saved["evidence"], saved["assessment"])
        except ValueError:
            raise PackageConflict("Review the instruction test again to verify its assessment.") from None
        if assessment != saved["assessment"] or saved["evidence"] != self._evidence(db, test):
            raise PackageConflict("Activity or the buyer correction changed. Review the instruction test again.")
        package = self.drafts.require_approved_package(
            db, test["campaign_id"], test["revision"], test["fingerprint"],
        )["package"]
        self._verify_media(test)
        group = next(group for group in package["groups"] if group["creative_version"] == test["creative_version"])
        revised = next(version for version in test["versions"] if version["arm"] == "revised")
        if group["content"] != revised["content"]:
            raise PackageConflict("The approved baseline differs from the reviewed experiment.")
        return {
            "package": package, "comparison": group["content"],
            "correction": saved["evidence"]["correction"],
            "next_action": "draft" if assessment["kind"] == "prepare_another_test" else "wait",
            "experiment_review": {"id": review_id, **saved},
            "review": {"id": review_id, "test_id": test_id, "fingerprint": test["fingerprint"],
                       "proposal": {"creative_version": test["creative_version"],
                                    "reason": assessment["reason"],
                                    "measure": "Compare completions per assigned visit in a new instruction experiment."}},
        }

    def save_next_test(self, db, source, instruction, *, inference=None):
        context = self.next_test_context(db, **source)
        if context["next_action"] != "draft":
            raise PackageConflict("This assessment calls for more evidence, not another draft.")
        return self.drafts.save_instruction_test(
            db, context["package"], context["review"], context["correction"], instruction, inference=inference,
        )

    @staticmethod
    def validate_assessment(context, assessment):
        if not isinstance(assessment, dict):
            raise ValueError("Provide a structured instruction-test assessment.")
        if set(assessment) == {"kind", "title", "reason"}:
            # Earlier runs returned prose. Retain their bounded decision and regenerate all factual wording.
            code = LEGACY_REASON_CODES.get(assessment["kind"]) if isinstance(assessment["kind"], str) else None
        elif set(assessment) in ({"reason_code"}, {"kind", "reason_code", "title", "reason"}):
            code = assessment["reason_code"]
        else:
            raise ValueError("Provide a structured instruction-test assessment.")
        if not isinstance(code, str) or code not in ASSESSMENT_REASONS:
            raise ValueError("Choose a supported assessment reason code.")
        kind, title = ASSESSMENT_REASONS[code]
        minimum = context["minimum_per_version"]
        sufficient = all(row["arrivals"] >= minimum for row in context["rows"])
        if not sufficient and code != "insufficient_visits":
            raise ValueError("Collect more assigned visits before proposing another test.")
        if sufficient and code == "insufficient_visits":
            raise ValueError("The captured evidence already meets the visit minimum.")
        if (code == "revised_not_higher"
                and (not context["correction"] or context["correction"]["kind"] != "keep_takes")):
            raise ValueError("The buyer correction does not permit another instruction change.")
        original, revised = context["rows"]
        if (code == "revised_not_higher"
                and revised["completions"] * original["arrivals"] > original["completions"] * revised["arrivals"]):
            raise ValueError("The revised completion rate is higher in the captured evidence.")
        facts = (
            f"Original instructions had {original['completions']} completed comparisons from "
            f"{original['arrivals']} assigned visits. Revised instructions had {revised['completions']} "
            f"completed comparisons from {revised['arrivals']} assigned visits. "
        )
        guidance = {
            "insufficient_visits": (
                f"Collect at least {minimum} assigned visits per version before considering another change. "
                "This is an illustrative POC threshold."
            ),
            "continue_observation": "Continue collecting evidence with the approved versions and buyer correction.",
            "revised_not_higher": (
                "The revised version has no higher observed completion rate. "
                "Keep both recordings fixed when considering another instruction test."
            ),
        }
        return {"kind": kind, "reason_code": code, "title": title, "reason": facts + guidance[code]}

    def read(self, campaign_id, revision, fingerprint):
        self.drafts._package_scope(campaign_id, revision)
        test_id = self.test_id(campaign_id, revision, fingerprint, self.drafts.scope)
        with closing(self.viewer.connect()) as db:
            db.execute("BEGIN")
            if not db.execute("SELECT 1 FROM instruction_tests WHERE id = ?", (test_id,)).fetchone():
                return None
            test = self._test(db, test_id)
            evidence = self._evidence(db, test)
            row = db.execute(
                "SELECT id, created_at, snapshot FROM instruction_test_reviews WHERE test_id = ? ORDER BY rowid DESC LIMIT 1",
                (test_id,),
            ).fetchone()
            review = {"id": row[0], "created_at": row[1], **json.loads(row[2])} if row else None
            if review:
                saved_assessment = review["assessment"]
                try:
                    assessment = self.validate_assessment(review["evidence"], saved_assessment)
                except ValueError:
                    enough = all(row["arrivals"] >= review["evidence"]["minimum_per_version"]
                                 for row in review["evidence"]["rows"])
                    assessment = self.validate_assessment(review["evidence"], {
                        "reason_code": "continue_observation" if enough else "insufficient_visits",
                    })
                review["assessment"] = assessment
                review["assessment_verified"] = (review["evidence"].get("assignment_source") == "participant"
                                                 and assessment == saved_assessment)
            snapshot = self._latest_snapshot(db, test_id)
            checkpoint = self._initial_batch_checkpoint(db, snapshot) if snapshot else None
            result = {**test, "evidence": evidence, "review": review,
                    "unknown_source_rows": self._assignment_rows(db, test, None),
                    "evidence_snapshot": snapshot,
                    "needs_review": review is None or not review["assessment_verified"] or review["evidence"] != evidence}
        decision = self.snapshot_decision(snapshot, checkpoint) if snapshot else None
        if (decision and decision["action"] in ("reuse", "collect", "continue_batch")
                and sum(row["arrivals"] for row in evidence["rows"]) > decision["assigned"]):
            decision = {**decision, "action": "refresh_snapshot"}
        return {**result, "evidence_decision": decision}

    @staticmethod
    def snapshot_decision(snapshot, checkpoint):
        checkpoint_id = checkpoint["id"] if checkpoint and recommend_instruction_action(checkpoint)["action"] == "collect" else None
        return recommend_instruction_action(snapshot, batch_checkpoint_id=checkpoint_id)
