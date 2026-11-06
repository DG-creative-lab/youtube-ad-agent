"""Prepare an offline review and persist its evidence and proposed test."""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .access import LOCAL_BRAND
from .handoff import package_fingerprint


DELIVERY_FIXTURE = Path(__file__).resolve().parents[1] / "examples/tts-performance/delivery.json"
MIN_SAMPLE_IMPRESSIONS = 100
MIN_LOCAL_ARRIVALS = 3
LOW_COMPLETION_RATE = 0.5
VIEWER_ATTRIBUTION = "verified_comparison_content"


class SampleCampaignReporting:
    def __init__(self):
        self.fixture = json.loads(DELIVERY_FIXTURE.read_text())

    def scenarios(self):
        return [{"id": key, "label": value["label"]} for key, value in self.fixture["scenarios"].items()]

    def snapshot(self, scenario, creatives):
        selected = self.fixture["scenarios"].get(scenario)
        if selected is None:
            raise ValueError("Choose a sample delivery scenario.")
        rows = [
            {"creative_version": creative, "metrics": selected["rows"].get(creative)}
            for creative in creatives
        ]
        return {
            "fixture_id": self.fixture["id"], "source": self.fixture["source"], "grain": self.fixture["grain"],
            "window": self.fixture["window"], "scenario": scenario, "label": selected["label"],
            "coverage": "complete" if all(row["metrics"] is not None for row in rows) else "partial",
            "rows": rows,
        }


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
    def __init__(self, drafts, viewer, reporting=None):
        self.drafts = drafts
        self.viewer = viewer
        self.reporting = reporting if reporting is not None else SampleCampaignReporting()
        with closing(sqlite3.connect(drafts.path)) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS campaign_performance_reviews (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL, last_requested_at TEXT NOT NULL, snapshot TEXT NOT NULL
                )
            """)

    def review(self, campaign_id, revision, fingerprint, scenario):
        package = self.drafts.export_setup(campaign_id, revision, fingerprint)
        comparisons = [
            (group["creative_version"], group["comparison_version"], package_fingerprint(group["content"]))
            for group in package["groups"]
        ]
        delivery = self.reporting.snapshot(scenario, [creative for creative, _, _ in comparisons])
        activity = self.viewer.summarize(LOCAL_BRAND, comparisons)
        evidence = {
            "campaign_id": campaign_id, "revision": revision, "fingerprint": fingerprint,
            "sample_delivery": delivery,
            "local_viewer_activity": {"source": "Recorded local viewer events", "window": "All local history",
                                      "grain": "Verified visits by comparison content", "rows": activity,
                                      "attribution": VIEWER_ATTRIBUTION},
            "proposal": propose_next_test(delivery, activity),
        }
        review_id = package_fingerprint({
            "client": LOCAL_BRAND.client_id, "brand": LOCAL_BRAND.brand_id, "evidence": evidence,
        })
        snapshot = json.dumps(evidence)
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                "INSERT INTO campaign_performance_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET last_requested_at = excluded.last_requested_at",
                (review_id, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, campaign_id, revision,
                 fingerprint, now, now, snapshot),
            )
            created_at = db.execute("SELECT created_at FROM campaign_performance_reviews WHERE id = ?",
                                    (review_id,)).fetchone()[0]
        return {"id": review_id, "created_at": created_at, **evidence}

    def read(self, campaign_id, revision, fingerprint):
        if self.drafts.read_approved_package(campaign_id, revision, fingerprint) is None:
            return {"scenarios": self.reporting.scenarios(), "review": None}
        with closing(sqlite3.connect(self.drafts.path)) as db:
            row = db.execute(
                "SELECT id, created_at, snapshot FROM campaign_performance_reviews "
                "WHERE client_id = ? AND brand_id = ? AND campaign_id = ? AND revision = ? AND fingerprint = ? "
                "AND json_extract(snapshot, '$.local_viewer_activity.attribution') = ? "
                "ORDER BY last_requested_at DESC, id DESC LIMIT 1",
                (LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, campaign_id, revision, fingerprint, VIEWER_ATTRIBUTION),
            ).fetchone()
        latest = {"id": row[0], "created_at": row[1], **json.loads(row[2])} if row else None
        return {"scenarios": self.reporting.scenarios(), "review": latest}
