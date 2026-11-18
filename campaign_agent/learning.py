"""Scoped reuse of a saved instruction experiment decision."""

import json
import re

from campaign_agent.application.campaigns import POLICY
from campaign_agent.domain.errors import PackageConflict
from .agent.draft_permissions import permits
from .handoff import package_fingerprint
from .instruction_tests import EVIDENCE_PROTOCOL
from .measurement import ViewerNotFound
from .ports.evidence import EvidenceReader, EvidenceStorage


FINDING_VERSION = 1
MATCH_PROTOCOL = {key: value for key, value in EVIDENCE_PROTOCOL.items() if key != "additional_batch_size"}


def _reference(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Choose a valid instruction finding or evidence snapshot.")


def _comparison_key(group, baseline):
    return package_fingerprint({
        "context": group["context"],
        "creative": group["creative_version"],
        "comparison": group["comparison_version"],
        "protocol": MATCH_PROTOCOL,
        "baseline": baseline,
    })


class InstructionFindings:
    def __init__(self, tests, storage: EvidenceStorage):
        self.tests = tests
        self.drafts = tests.drafts
        self.storage = storage

    @property
    def scope(self):
        return self.drafts.scope.client_id, self.drafts.scope.brand_id, self.drafts.campaign_id

    def _current_source(self, records: EvidenceReader, test, snapshot_id):
        snapshot = self.tests.latest_snapshot_from(records, test["id"])
        if not snapshot or snapshot["id"] != snapshot_id or snapshot["protocol"] != test.get("evidence_protocol"):
            return None
        protocol = snapshot["protocol"]
        if any(protocol.get(key) != value for key, value in MATCH_PROTOCOL.items()):
            return None
        frozen = [row["cohorts"]["participant"] for row in snapshot["rows"]]
        live = self.tests.assignment_rows_from(records, test, "participant")
        if any(count["unresolved"] or count["mature_arrivals"] != row["arrivals"]
               for count, row in zip(frozen, live, strict=True)):
            return None
        # A completion committed in the same millisecond as the cutoff can change the evidence.
        at_cutoff = self.tests.snapshot_rows_from(records, test, protocol["observation_window_ms"], snapshot["cutoff_ms"])
        return snapshot if [row["cohorts"]["participant"] for row in at_cutoff] == frozen else None

    def save(self, campaign_id, revision, fingerprint, *, snapshot_id):
        self.drafts.require("youtube:learning.manage")
        _reference(snapshot_id)
        with self.storage.write() as records:
            package = self.drafts.require_approved_from(records.drafts, campaign_id, revision, fingerprint)["package"]
            test = self.tests.test_from(records, self.tests.test_id(campaign_id, revision, fingerprint, self.drafts.scope))
            snapshot = self._current_source(records, test, snapshot_id)
            if snapshot is None:
                raise PackageConflict("Save a current snapshot with resolved participant outcomes first.")
            decision = self.tests.snapshot_decision(snapshot, self.tests.initial_batch_checkpoint_from(records, snapshot))
            if decision["action"] != "reuse" or decision["batch_status"] == "no_batch_recommendation":
                raise PackageConflict("This evidence does not support saving a reuse finding.")
            creative = test["creative_version"]
            correction = self.tests.performance.correction_for_comparison_from(records, package, creative)
            if correction != test["source_correction"]:
                raise PackageConflict("The buyer correction changed. Review the experiment again.")
            original, revised = test["versions"]
            group = next(group for group in package["groups"] if group["creative_version"] == creative)
            finding_id = package_fingerprint({"version": FINDING_VERSION, "snapshot_id": snapshot_id})
            self.drafts.require("youtube:learning.manage")
            finding = {
                "id": finding_id, "version": FINDING_VERSION, "action": "reuse",
                "test_id": test["id"], "snapshot_id": snapshot_id, "cutoff_ms": snapshot["cutoff_ms"],
                "source_revision": revision, "source_brief": package["brief"],
                "brand_policy": package["policy"], "context": group["context"], "context_title": group["title"],
                "model": "Beta–Bernoulli", "decision": decision,
                "before": original["content"]["instruction"], "after": revised["content"]["instruction"],
                "revised_content_fingerprint": revised["content_fingerprint"],
            }
            records.add_finding(self.scope, finding_id,
                                _comparison_key(group, original["content_fingerprint"]), json.dumps(finding))
            row = records.finding_retired_row(self.scope, finding_id)
            if row is None or row[0]:
                raise PackageConflict("This finding is unavailable for reuse.")
            records.commit()
        return finding

    def _target(self, records: EvidenceReader, campaign_id, revision, fingerprint):
        review, _ = self.drafts._review_from(records.drafts, campaign_id, revision)
        if review["current_revision"] != revision or review["fingerprint"] != fingerprint:
            raise PackageConflict("The package has changed. Load and review the latest draft.")
        return review["package"], self.drafts.read_from(records.drafts)

    def _latest_match(self, records: EvidenceReader, package):
        if len(package["groups"]) != 1 or "instruction_test" in package:
            return None
        group, = package["groups"]
        key = _comparison_key(group, package_fingerprint(group["content"]))
        row = records.latest_finding_row(self.scope, key)
        return json.loads(row[0]) if row and not row[1] else None

    def _eligible(self, records: EvidenceReader, package, draft):
        finding = self._latest_match(records, package)
        if (not finding or finding["version"] != FINDING_VERSION or package["brief"] == finding["source_brief"]
                or draft["policy"] != POLICY or package["policy"] != finding["brand_policy"]):
            return None
        try:
            test = self.tests.test_from(records, finding["test_id"])
        except ViewerNotFound:
            return None
        if not self._current_source(records, test, finding["snapshot_id"]):
            return None
        group, = package["groups"]
        correction = self.tests.performance.correction_for_comparison_from(records, package, group["creative_version"])
        if not correction or correction["kind"] != "keep_takes":
            return None
        return {"finding": finding, "correction": correction}

    def read(self, campaign_id, revision, fingerprint):
        with self.storage.read() as records:
            package, draft = self._target(records, campaign_id, revision, fingerprint)
            return self._eligible(records, package, draft)

    def retire(self, campaign_id, revision, fingerprint, *, finding_id):
        self.drafts.require("youtube:learning.manage")
        _reference(finding_id)
        with self.storage.write() as records:
            package, _ = self._target(records, campaign_id, revision, fingerprint)
            finding = self._latest_match(records, package)
            if not finding or finding["id"] != finding_id:
                raise PackageConflict("This finding is no longer available for this brief.")
            self.drafts.require("youtube:learning.manage")
            if not records.retire_finding(self.scope, finding_id):
                raise PackageConflict("This finding is no longer available for this brief.")
            records.commit()
        return {"retired": finding_id}

    def apply(self, campaign_id, revision, fingerprint, *, finding_id, correction_id, draft_permission="none"):
        _reference(finding_id)
        if not permits({"draft_permission": draft_permission}, "apply_instruction_finding"):
            raise PermissionError("Allow an instruction draft before applying a finding.")
        with self.storage.write() as records:
            package, draft = self._target(records, campaign_id, revision, fingerprint)
            eligible = self._eligible(records, package, draft)
            if not eligible or eligible["finding"]["id"] != finding_id or eligible["correction"]["id"] != correction_id:
                raise PackageConflict("The finding or buyer correction changed. Reload the brief to review it.")
            finding = eligible["finding"]
            group, = package["groups"]
            instruction = self.drafts.validate_instruction(finding["after"], group["content"]["instruction"])
            if package_fingerprint({**group["content"], "instruction": instruction}) != finding["revised_content_fingerprint"]:
                raise PackageConflict("The revised wording no longer matches the tested comparison.")
            saved = self.drafts._save_instruction_revision_from(
                records.drafts, draft, group, instruction, {"instruction_reuse": eligible},
            )
            records.commit()
            return saved
