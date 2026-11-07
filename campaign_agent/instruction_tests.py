"""Pinned instruction experiments, stable assignments and evidence-backed assessments."""

from contextlib import closing
from datetime import datetime, timezone
import json
import re
import secrets

from .access import LOCAL_BRAND
from .handoff import package_fingerprint
from .measurement import ViewerNotFound
from scripts.campaign_drafts import PackageConflict


MIN_TEST_ARRIVALS = 20
# Bump when saved assessments need reverification under a changed acceptance contract.
ASSESSMENT_VERSION = "evidence-reasons-v1"
ASSESSMENT_REASONS = {
    "insufficient_visits": ("insufficient_evidence", "Insufficient evidence"),
    "continue_observation": ("keep_collecting", "Keep collecting evidence"),
    "revised_not_higher": ("prepare_another_test", "Consider another instruction test"),
}
LEGACY_REASON_CODES = {kind: code for code, (kind, _title) in ASSESSMENT_REASONS.items()}


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
                    PRIMARY KEY (test_id, participant_id)
                );
                CREATE TABLE IF NOT EXISTS instruction_test_reviews (
                    id TEXT PRIMARY KEY, test_id TEXT NOT NULL REFERENCES instruction_tests(id),
                    actor_id TEXT NOT NULL, created_at TEXT NOT NULL, snapshot TEXT NOT NULL
                );
            """)

    @staticmethod
    def test_id(campaign_id, revision, fingerprint):
        return package_fingerprint({"scope": vars(LOCAL_BRAND), "campaign": campaign_id,
                                    "revision": revision, "fingerprint": fingerprint})[:32]

    def _test(self, db, test_id):
        if not isinstance(test_id, str) or not re.fullmatch(r"[0-9a-f]{32}", test_id):
            raise ValueError("Choose a valid instruction test.")
        row = db.execute(
            "SELECT snapshot FROM instruction_tests WHERE id = ? AND client_id = ? AND brand_id = ? "
            "AND campaign_id = ?",
            (test_id, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, self.drafts.campaign_id),
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

    def start(self, campaign_id, revision, fingerprint):
        self.drafts._package_scope(campaign_id, revision)
        test_id = self.test_id(campaign_id, revision, fingerprint)
        with closing(self.viewer.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT id FROM instruction_tests WHERE id = ?", (test_id,)).fetchone()
            if existing:
                return self._test(db, test_id)
            package = self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)["package"]
            prepared = package.get("instruction_test")
            if prepared is None:
                raise ValueError("Prepare and approve an instruction test first.")
            original = db.execute(
                "SELECT snapshot FROM campaign_package_approvals WHERE client_id = ? AND brand_id = ? "
                "AND campaign_id = ? AND revision = ? AND fingerprint = ? AND snapshot IS NOT NULL",
                (LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, campaign_id,
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
                "versions": [
                    {"arm": arm, "revision": arm_revision, "content": group["content"],
                     "content_fingerprint": package_fingerprint(group["content"])}
                    for arm, arm_revision, group in (
                        ("original", prepared["source_revision"], old), ("revised", revision, new),
                    )
                ],
            }
            self._verify_media(test)
            db.execute("INSERT INTO instruction_tests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (test_id, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, campaign_id,
                        revision, fingerprint, test["started_at"], json.dumps(test)))
        return test

    def open(self, test_id, participant_id):
        if not isinstance(participant_id, str) or not re.fullmatch(r"[0-9a-f]{32}", participant_id):
            raise ValueError("Use a valid participant reference.")
        with closing(self.viewer.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            test = self._test(db, test_id)
            self._verify_media(test)
            row = db.execute(
                "SELECT arm, visit_id FROM instruction_test_assignments WHERE test_id = ? AND participant_id = ?",
                (test_id, participant_id),
            ).fetchone()
            arm, visit_id = row if row else (secrets.choice(("original", "revised")), None)
            version = next(version for version in test["versions"] if version["arm"] == arm)
            result = self.viewer.open_example(
                test["creative_version"], test["comparison_version"], visit_id,
                content_fingerprint=version["content_fingerprint"], connection=db,
            )
            if row is None:
                db.execute("INSERT INTO instruction_test_assignments VALUES (?, ?, ?, ?)",
                           (test_id, participant_id, arm, result["visit_id"]))
            result["creative_ref"] = test["creative_version"]
            result["example"]["instruction"] = version["content"]["instruction"]
            result["examples"] = [item for item in result["examples"] if item["ref"] == test["comparison_version"]]
            for take, content in zip(result["example"]["takes"], version["content"]["takes"]):
                take["url"] += "?sha256=" + content["sha256"]
            result["example"]["captions"] += "?sha256=" + version["content"]["captions_sha256"]
            return result

    def _evidence(self, db, test):
        rows = []
        for version in test["versions"]:
            arrivals, completions = db.execute("""
                SELECT COUNT(*), COUNT(CASE WHEN EXISTS (
                    SELECT 1 FROM viewer_completions c WHERE c.visit_id = v.id AND c.example_ref = ?
                ) THEN 1 END)
                FROM instruction_test_assignments a JOIN viewer_visits v ON v.id = a.visit_id
                WHERE a.test_id = ? AND a.arm = ? AND v.client_id = ? AND v.brand_id = ?
                    AND v.creative_ref = ? AND v.content_fingerprint = ?
                    AND EXISTS (SELECT 1 FROM viewer_events e WHERE e.visit_id = v.id
                                AND e.kind = 'arrival' AND e.example_ref = ?)
            """, (test["comparison_version"], test["id"], version["arm"], LOCAL_BRAND.client_id,
                  LOCAL_BRAND.brand_id, test["creative_version"], version["content_fingerprint"],
                  test["comparison_version"])).fetchone()
            rows.append({"arm": version["arm"], "arrivals": arrivals, "completions": completions,
                         "completion_rate": completions / arrivals if arrivals else None})
        through_event, = db.execute(
            "SELECT COALESCE(MAX(e.seq), 0) FROM viewer_events e JOIN instruction_test_assignments a "
            "ON a.visit_id = e.visit_id WHERE a.test_id = ?", (test["id"],),
        ).fetchone()
        return {
            "test_id": test["id"], "campaign_id": test["campaign_id"],
            "revision": test["revision"], "fingerprint": test["fingerprint"],
            "versions": test["versions"], "rows": rows,
            "started_at": test["started_at"], "through_event": through_event,
            "minimum_per_version": MIN_TEST_ARRIVALS,
            "correction": self.performance.correction_for_comparison(db, test["package"], test["creative_version"]),
        }

    def review_context(self, test_id):
        self.drafts.operator.require_brand(LOCAL_BRAND)
        with closing(self.viewer.connect()) as db:
            db.execute("BEGIN")
            test = self._test(db, test_id)
            return self._evidence(db, test)

    def require_review_context(self, db, context):
        self.drafts.operator.require_brand(LOCAL_BRAND)
        test = self._test(db, context["test_id"])
        current = self.performance.correction_for_comparison(db, test["package"], test["creative_version"])
        if current != context["correction"]:
            raise PackageConflict("The buyer correction changed. Review the instruction test again.")

    def save_review(self, db, context, assessment, *, inference=None):
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
        test_id = self.test_id(campaign_id, revision, fingerprint)
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
                review["assessment_verified"] = assessment == saved_assessment
            return {**test, "evidence": evidence, "review": review,
                    "needs_review": review is None or not review["assessment_verified"] or review["evidence"] != evidence}
