"""Prepare an offline review and persist its evidence and proposed test."""

from datetime import datetime, timezone
import json
import re

from .domain.performance import LOW_COMPLETION_RATE, MIN_LOCAL_ARRIVALS, apply_correction
from .handoff import package_fingerprint
from .ports.campaign_effects import SampleReporting
from .ports.evidence import BuyerCorrection, CorrectionReader, EvidenceReader, EvidenceStorage, EvidenceWriter
from campaign_agent.domain.errors import PackageConflict


MIN_SAMPLE_IMPRESSIONS = 100
VIEWER_ATTRIBUTION = "campaign_comparison_content_v1"
CORRECTION_CHOICES = {
    "keep_takes": "Keep both takes unchanged",
    "keep_comparison": "Keep the entire comparison unchanged",
}


def comparison_group(package, creative):
    return next(group for group in package["groups"] if group["creative_version"] == creative)


def comparison_identity(group, *, keep_takes=False):
    excluded = {"preview_sha256"}
    if keep_takes:
        excluded.add("instruction")
    content = {key: value for key, value in group["content"].items() if key not in excluded}
    return package_fingerprint({"comparison_version": group["comparison_version"], "content": content})


def propose_next_test(delivery, activity):
    """Select a controlled next step using the demo's illustrative thresholds."""
    local = {row["creative_version"]: row for row in activity}
    for row in delivery["rows"]:
        creative, metrics = row["creative_version"], row["metrics"]
        if metrics is not None and metrics["impressions"] < MIN_SAMPLE_IMPRESSIONS:
            return {
                "kind": "delivery_check", "creative_version": creative,
                "title": "Check delivery before changing the creative",
                "reason": f"The sample report shows {metrics['impressions']} impressions for this creative.",
                "change": "Check placement eligibility and inventory coverage in a manual rehearsal.",
                "hold_constant": "Keep the creative and comparison unchanged.",
                "measure": "Check impressions by creative before comparing viewer response.",
                "evidence": ["sample_delivery"],
            }
    for row in delivery["rows"]:
        creative = row["creative_version"]
        observation = local[creative]
        rate = observation["completion_rate"]
        if row["metrics"] is not None and observation["arrivals"] >= MIN_LOCAL_ARRIVALS and rate < LOW_COMPLETION_RATE:
            return {
                "kind": "comparison_test", "creative_version": creative,
                "title": "Test a shorter second take",
                "reason": f"{observation['completions']} of {observation['arrivals']} tagged local visits completed "
                          "the intended comparison.",
                "change": "Create a shorter second take and compare it with the current version in a local test.",
                "hold_constant": "Keep the ad, first take and destination flow the same.",
                "measure": "Compare completions per tagged arrival across the two versions.",
                "evidence": ["local_viewer_activity"],
            }
    if delivery["coverage"] == "partial":
        return {
            "kind": "coverage_check", "creative_version": None, "title": "Fill the delivery evidence gap",
            "reason": "The sample report omits delivery for at least one creative.",
            "change": "Rehearse the review with a delivery report that includes both creatives.",
            "hold_constant": "Keep the current creative and comparison examples.",
            "measure": "Confirm that both creative totals are present before comparing delivery.",
            "evidence": ["sample_delivery"],
        }
    return {
        "kind": "collect_activity", "creative_version": None, "title": "Collect more local comparison evidence",
        "reason": "The observed local activity does not meet the demo's trigger for a comparison change.",
        "change": "Run more local sessions with the current comparisons.",
        "hold_constant": "Keep the same creative versions and viewer tasks.",
        "measure": "Track tagged arrivals and intended-comparison completions for each creative.",
        "evidence": ["local_viewer_activity"],
    }


class CampaignPerformance:
    def __init__(self, drafts, viewer, reporting: SampleReporting, storage: EvidenceStorage):
        if viewer.campaign_id != drafts.campaign_id:
            raise ValueError("Bind measurement to this campaign before reviewing activity.")
        self.drafts = drafts
        self.viewer = viewer
        self.reporting, self.storage = reporting, storage

    def measurement_capabilities(self):
        """Return the viewer owner's definitions, not an unscoped activity query."""
        self.drafts.require('youtube:campaign.read')
        return self.viewer.capabilities()

    def _latest_correction(self, records: CorrectionReader, evidence, package):
        proposal = evidence["proposal"]
        if proposal["kind"] != "comparison_test":
            return None
        scope = self.drafts.scope.client_id, self.drafts.scope.brand_id, evidence["campaign_id"]
        return self._comparison_correction(records, scope, package, proposal["creative_version"])

    def correction_for_comparison_from(self, records: CorrectionReader, package, creative):
        scope = self.drafts._package_scope(package["campaign_id"], package["revision"])
        return self._comparison_correction(records, scope, package, creative)

    def _comparison_correction(self, records: CorrectionReader, scope, package, creative):
        group = comparison_group(package, creative)
        row = records.correction_row(*scope, creative, group["comparison_version"],
                                     comparison_identity(group, keep_takes=True), comparison_identity(group))
        return self._correction_record(row) if row else None

    @staticmethod
    def _correction_record(row):
        correction_id, kind, note, review_id, actor, created_at = row
        return {"id": correction_id, "kind": kind, "label": CORRECTION_CHOICES[kind], "note": note,
                "review_id": review_id, "actor_id": actor, "created_at": created_at}

    def save_correction(self, campaign_id, revision, fingerprint, review_id, kind, note, operation_id):
        self.drafts.require("youtube:review.write")
        if not isinstance(operation_id, str) or not re.fullmatch(r"[0-9a-f]{32}", operation_id):
            raise ValueError("Use a valid correction operation ID.")
        if (not isinstance(kind, str) or kind not in CORRECTION_CHOICES
                or not isinstance(note, str) or len(note.strip()) > 500):
            raise ValueError("Choose a correction and enter a note of up to 500 characters.")
        note = note.strip()
        scope = self.drafts.scope.client_id, self.drafts.scope.brand_id, campaign_id
        with self.storage.write() as unit:
            approved = self.drafts.require_approved_from(unit.drafts, campaign_id, revision, fingerprint)
            package = approved["package"]
            row = (unit.performance_review_row((*scope, revision, fingerprint), VIEWER_ATTRIBUTION, review_id)
                   if review_id is not None else None)
            if row is None:
                raise ValueError("Choose a review for this approved package.")
            evidence = json.loads(row[2])
            if evidence["proposal"]["kind"] != "comparison_test":
                raise ValueError("Choose a review that proposes a comparison test.")
            creative = evidence["proposal"]["creative_version"]
            group = comparison_group(package, creative)
            activity = next(row for row in evidence["local_viewer_activity"]["rows"]
                            if row["creative_version"] == creative)
            actor = self.drafts.operator.id
            correction_id = package_fingerprint({
                "client": self.drafts.scope.client_id, "brand": self.drafts.scope.brand_id, "campaign": campaign_id,
                "actor": actor, "operation": operation_id,
            })
            existing = unit.correction_operation(correction_id)
            if existing is not None and existing != (review_id, kind, note):
                raise ValueError("This correction operation was already used for a different save.")
            self.drafts.require("youtube:review.write")
            unit.add_correction(BuyerCorrection(
                id=correction_id, scope=scope, creative=creative, fingerprint=activity["comparison_fingerprint"],
                review_id=review_id, actor=actor, kind=kind, note=note, created_at=datetime.now(timezone.utc).isoformat(),
                comparison_identity=comparison_identity(group), takes_identity=comparison_identity(group, keep_takes=True),
                comparison_version=group["comparison_version"],
            ))
            saved = self._latest_correction(unit, evidence, package)
            unit.commit()
            return saved

    def capture_review(self, campaign_id, revision, fingerprint, scenario):
        package = self.drafts.export_setup(campaign_id, revision, fingerprint)
        comparisons = [
            (group["creative_version"], group["comparison_version"], package_fingerprint(group["content"]))
            for group in package["groups"]
        ]
        delivery = self.reporting.snapshot(scenario, [creative for creative, _, _ in comparisons])
        activity = self.viewer.summarize(self.drafts.scope, comparisons)
        evidence = {
            "campaign_id": campaign_id, "revision": revision, "fingerprint": fingerprint,
            "sample_delivery": delivery,
            "local_viewer_activity": {"source": "Recorded local viewer events", "window": "All local history",
                                      "grain": "Verified visits by comparison content", "rows": activity,
                                      "attribution": VIEWER_ATTRIBUTION},
            "proposal": propose_next_test(delivery, activity),
        }
        return evidence

    def require_current_activity_from(self, records: EvidenceReader, evidence, package):
        comparisons = [(group['creative_version'], group['comparison_version'], package_fingerprint(group['content']))
                       for group in package['groups']]
        if self.viewer.summarize_from(records, self.drafts.scope, comparisons) != evidence['local_viewer_activity']['rows']:
            raise PackageConflict('Viewer activity changed. Review performance again before preparing a test.')

    def save_review_from(self, records: EvidenceWriter, evidence):
        self.drafts.require("youtube:review.write")
        campaign_id, revision, fingerprint = (evidence[key] for key in ('campaign_id', 'revision', 'fingerprint'))
        package = self.drafts.require_approved_from(records.drafts, campaign_id, revision, fingerprint)['package']
        self.require_current_activity_from(records, evidence, package)
        evidence = {**evidence, 'proposal': propose_next_test(evidence['sample_delivery'], evidence['local_viewer_activity']['rows'])}
        correction = self._latest_correction(records, evidence, package)
        if correction:
            evidence['proposal'] = apply_correction(evidence['proposal'], correction)
        review_id = package_fingerprint({'client': self.drafts.scope.client_id, 'brand': self.drafts.scope.brand_id, 'evidence': evidence})
        now = datetime.now(timezone.utc).isoformat()
        key = self.drafts.scope.client_id, self.drafts.scope.brand_id, campaign_id, revision, fingerprint
        created_at = records.save_performance_review(key, review_id, now, json.dumps(evidence))
        return {'id': review_id, 'created_at': created_at, **evidence}

    def review(self, campaign_id, revision, fingerprint, scenario):
        evidence = self.capture_review(campaign_id, revision, fingerprint, scenario)
        with self.storage.write() as unit:
            review = self.save_review_from(unit, evidence)
            unit.commit()
            return review

    def saved_review_from(self, records: EvidenceReader, campaign_id, revision, fingerprint, review_id=None):
        """Read a verified-content review within the caller's unit and campaign scope."""
        scope = self.drafts._package_scope(campaign_id, revision)
        self.drafts._require_owner(records.drafts)
        row = records.performance_review_row((*scope, revision, fingerprint), VIEWER_ATTRIBUTION, review_id)
        return {'id': row[0], 'created_at': row[1], **json.loads(row[2])} if row else None

    def instruction_test_context_from(self, records: EvidenceReader, campaign_id, revision, fingerprint, review_id):
        approved = self.drafts.require_approved_from(records.drafts, campaign_id, revision, fingerprint)
        key = self.drafts.scope.client_id, self.drafts.scope.brand_id, campaign_id, revision, fingerprint
        row = records.performance_review_row(key, VIEWER_ATTRIBUTION, review_id) if review_id is not None else None
        if row is None:
            raise ValueError("Choose a review for this approved package.")
        review = {"id": review_id, "created_at": row[1], **json.loads(row[2])}
        correction = self._latest_correction(records, review, approved["package"])
        if correction != review["proposal"].get("correction"):
            raise PackageConflict("The buyer correction changed. Run another review before preparing a test.")
        if (review["proposal"]["kind"] != "comparison_test"
                or not correction or correction["kind"] != "keep_takes"):
            raise ValueError("This preparation supports instruction tests with a keep-takes correction.")
        group = comparison_group(approved["package"], review["proposal"]["creative_version"])
        return {"package": approved["package"], "review": review, "correction": correction,
                "comparison": group["content"]}

    def save_instruction_test_from(self, records: EvidenceWriter, source, instruction, *, inference=None):
        context = self.instruction_test_context_from(records, **source)
        options = {"inference": inference} if inference is not None else {}
        return self.drafts.save_instruction_test_from(
            records.drafts, context["package"], context["review"], context["correction"], instruction, **options,
        )

    def read(self, campaign_id, revision, fingerprint):
        response = {
            "scenarios": self.reporting.scenarios(), "review": None, "correction": None,
            "correction_choices": [{"id": key, "label": label} for key, label in CORRECTION_CHOICES.items()],
        }
        with self.storage.read() as records:
            approved = self.drafts.read_approved_from(records.drafts, campaign_id, revision, fingerprint)
            if approved is None:
                return response
            key = self.drafts.scope.client_id, self.drafts.scope.brand_id, campaign_id, revision, fingerprint
            row = records.performance_review_row(key, VIEWER_ATTRIBUTION)
            if row:
                response["review"] = {"id": row[0], "created_at": row[1], **json.loads(row[2])}
                response["correction"] = self._latest_correction(records, response["review"], approved["package"])
        return response
