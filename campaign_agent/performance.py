"""Prepare an offline review and persist its evidence and proposed test."""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

from .access import LOCAL_BRAND
from .handoff import package_fingerprint
from scripts.campaign_drafts import PackageConflict


DELIVERY_FIXTURE = Path(__file__).resolve().parents[1] / "examples/tts-performance/delivery.json"
MIN_SAMPLE_IMPRESSIONS = 100
MIN_LOCAL_ARRIVALS = 3
LOW_COMPLETION_RATE = 0.5
VIEWER_ATTRIBUTION = "verified_comparison_content"
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


def apply_correction(proposal, correction):
    if correction["kind"] == "keep_takes":
        changes = {
            "title": "Test clearer comparison instructions",
            "change": "Compare revised instructions with the current wording in a local test.",
            "hold_constant": "Keep the ad, both takes and the choice controls the same.",
        }
    else:
        changes = {
            "title": "Test how the ad sets up the comparison",
            "change": "Compare a clearer invitation to try both takes with the current ad invitation.",
            "hold_constant": "Keep the placements, takes and viewer experience the same.",
        }
    return {**proposal, **changes, "correction": correction}


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
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                CREATE TABLE IF NOT EXISTS campaign_performance_reviews (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL, last_requested_at TEXT NOT NULL, snapshot TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS campaign_buyer_corrections (
                    sequence INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE,
                    client_id TEXT NOT NULL, brand_id TEXT NOT NULL, campaign_id TEXT NOT NULL,
                    creative_version TEXT NOT NULL, comparison_fingerprint TEXT NOT NULL,
                    review_id TEXT NOT NULL, actor_id TEXT NOT NULL, kind TEXT NOT NULL,
                    note TEXT NOT NULL, created_at TEXT NOT NULL,
                    comparison_identity TEXT, takes_identity TEXT, comparison_version TEXT
                )
            """)
            columns = {column[1] for column in db.execute("PRAGMA table_info(campaign_buyer_corrections)")}
            missing = {"comparison_identity", "takes_identity", "comparison_version"} - columns
            for column in sorted(missing):
                db.execute(f"ALTER TABLE campaign_buyer_corrections ADD COLUMN {column} TEXT")
            self._migrate_correction_identities(db)

    def _migrate_correction_identities(self, db):
        rows = db.execute("""
            SELECT c.id, c.creative_version, a.snapshot
            FROM campaign_buyer_corrections c
            JOIN campaign_performance_reviews r ON r.id = c.review_id
                AND r.client_id = c.client_id AND r.brand_id = c.brand_id AND r.campaign_id = c.campaign_id
            JOIN campaign_package_approvals a ON a.client_id = r.client_id AND a.brand_id = r.brand_id
                AND a.campaign_id = r.campaign_id AND a.revision = r.revision AND a.fingerprint = r.fingerprint
            WHERE a.snapshot IS NOT NULL
                AND (c.comparison_identity IS NULL OR c.takes_identity IS NULL OR c.comparison_version IS NULL)
        """).fetchall()
        for correction_id, creative, snapshot in rows:
            group = comparison_group(json.loads(snapshot), creative)
            db.execute(
                "UPDATE campaign_buyer_corrections SET comparison_identity = ?, takes_identity = ?, "
                "comparison_version = ? WHERE id = ?",
                (comparison_identity(group), comparison_identity(group, keep_takes=True),
                 group["comparison_version"], correction_id),
            )

    def _latest_correction(self, db, evidence, package):
        proposal = evidence["proposal"]
        if proposal["kind"] != "comparison_test":
            return None
        creative = proposal["creative_version"]
        group = comparison_group(package, creative)
        # Select the newest choice for these takes before checking whether it applies to the full comparison.
        row = db.execute("""
            SELECT id, kind, note, review_id, actor_id, created_at FROM (
                SELECT id, kind, note, review_id, actor_id, created_at, comparison_identity
                FROM campaign_buyer_corrections
                WHERE client_id = ? AND brand_id = ? AND campaign_id = ?
                    AND creative_version = ? AND comparison_version = ? AND takes_identity = ?
                ORDER BY sequence DESC LIMIT 1
            )
            WHERE kind = 'keep_takes' OR (kind = 'keep_comparison' AND comparison_identity = ?)
        """, (LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, evidence["campaign_id"],
              creative, group["comparison_version"], comparison_identity(group, keep_takes=True),
              comparison_identity(group))).fetchone()
        return self._correction_record(row) if row else None

    def correction_for_comparison(self, db, package, creative):
        self.drafts._package_scope(package["campaign_id"], package["revision"])
        return self._latest_correction(db, {
            "campaign_id": package["campaign_id"],
            "proposal": {"kind": "comparison_test", "creative_version": creative},
        }, package)

    @staticmethod
    def _correction_record(row):
        correction_id, kind, note, review_id, actor, created_at = row
        return {"id": correction_id, "kind": kind, "label": CORRECTION_CHOICES[kind], "note": note,
                "review_id": review_id, "actor_id": actor, "created_at": created_at}

    def save_correction(self, campaign_id, revision, fingerprint, review_id, kind, note, operation_id):
        if not isinstance(operation_id, str) or not re.fullmatch(r"[0-9a-f]{32}", operation_id):
            raise ValueError("Use a valid correction operation ID.")
        if (not isinstance(kind, str) or kind not in CORRECTION_CHOICES
                or not isinstance(note, str) or len(note.strip()) > 500):
            raise ValueError("Choose a correction and enter a note of up to 500 characters.")
        note = note.strip()
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            approved = self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)
            package = approved["package"]
            row = db.execute("""
                SELECT snapshot FROM campaign_performance_reviews
                WHERE id = ? AND client_id = ? AND brand_id = ? AND campaign_id = ? AND revision = ? AND fingerprint = ?
                    AND json_extract(snapshot, '$.local_viewer_activity.attribution') = ?
            """, (review_id, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, campaign_id, revision,
                  fingerprint, VIEWER_ATTRIBUTION)).fetchone()
            if row is None:
                raise ValueError("Choose a review for this approved package.")
            evidence = json.loads(row[0])
            if evidence["proposal"]["kind"] != "comparison_test":
                raise ValueError("Choose a review that proposes a comparison test.")
            creative = evidence["proposal"]["creative_version"]
            group = comparison_group(package, creative)
            activity = next(row for row in evidence["local_viewer_activity"]["rows"]
                            if row["creative_version"] == creative)
            actor = self.drafts.operator.id
            correction_id = package_fingerprint({
                "client": LOCAL_BRAND.client_id, "brand": LOCAL_BRAND.brand_id, "campaign": campaign_id,
                "actor": actor, "operation": operation_id,
            })
            existing = db.execute(
                "SELECT review_id, kind, note FROM campaign_buyer_corrections WHERE id = ?", (correction_id,),
            ).fetchone()
            if existing is not None and existing != (review_id, kind, note):
                raise ValueError("This correction operation was already used for a different save.")
            db.execute("""
                INSERT INTO campaign_buyer_corrections
                    (id, client_id, brand_id, campaign_id, creative_version, comparison_fingerprint,
                     review_id, actor_id, kind, note, created_at, comparison_identity, takes_identity, comparison_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING
            """, (correction_id, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, campaign_id, creative,
                  activity["comparison_fingerprint"], review_id, actor, kind, note, datetime.now(timezone.utc).isoformat(),
                  comparison_identity(group), comparison_identity(group, keep_takes=True),
                  group["comparison_version"]))
            return self._latest_correction(db, evidence, package)

    def capture_review(self, campaign_id, revision, fingerprint, scenario):
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
        return evidence

    def require_current_activity(self, db, evidence, package):
        comparisons = [(group['creative_version'], group['comparison_version'], package_fingerprint(group['content']))
                       for group in package['groups']]
        if self.viewer.summarize(LOCAL_BRAND, comparisons, connection=db) != evidence['local_viewer_activity']['rows']:
            raise PackageConflict('Viewer activity changed. Review performance again before preparing a test.')

    def save_review(self, db, evidence):
        campaign_id, revision, fingerprint = (evidence[key] for key in ('campaign_id', 'revision', 'fingerprint'))
        package = self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)['package']
        self.require_current_activity(db, evidence, package)
        evidence = {**evidence, 'proposal': propose_next_test(evidence['sample_delivery'], evidence['local_viewer_activity']['rows'])}
        correction = self._latest_correction(db, evidence, package)
        if correction:
            evidence['proposal'] = apply_correction(evidence['proposal'], correction)
        review_id = package_fingerprint({'client': LOCAL_BRAND.client_id, 'brand': LOCAL_BRAND.brand_id, 'evidence': evidence})
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            'INSERT INTO campaign_performance_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) '
            'ON CONFLICT(id) DO UPDATE SET last_requested_at = excluded.last_requested_at',
            (review_id, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, campaign_id, revision, fingerprint,
             now, now, json.dumps(evidence)))
        created_at = db.execute('SELECT created_at FROM campaign_performance_reviews WHERE id=?', (review_id,)).fetchone()[0]
        return {'id': review_id, 'created_at': created_at, **evidence}

    def review(self, campaign_id, revision, fingerprint, scenario):
        evidence = self.capture_review(campaign_id, revision, fingerprint, scenario)
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            return self.save_review(db, evidence)

    def saved_review(self, db, campaign_id, revision, fingerprint, review_id=None):
        """Read a verified-content review within the caller's transaction and campaign scope."""
        self.drafts._package_scope(campaign_id, revision)
        query = ("SELECT id,created_at,snapshot FROM campaign_performance_reviews "
                 "WHERE client_id=? AND brand_id=? AND campaign_id=? AND revision=? AND fingerprint=? "
                 "AND json_extract(snapshot, '$.local_viewer_activity.attribution')=?")
        values = [LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, campaign_id, revision, fingerprint, VIEWER_ATTRIBUTION]
        if review_id is not None:
            query += ' AND id=?'
            values.append(review_id)
        row = db.execute(query + ' ORDER BY last_requested_at DESC,id DESC LIMIT 1', values).fetchone()
        return {'id': row[0], 'created_at': row[1], **json.loads(row[2])} if row else None

    def instruction_test_context(self, db, campaign_id, revision, fingerprint, review_id):
        approved = self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)
        row = db.execute(
            "SELECT created_at, snapshot FROM campaign_performance_reviews "
            "WHERE id = ? AND client_id = ? AND brand_id = ? AND campaign_id = ? "
            "AND revision = ? AND fingerprint = ? "
            "AND json_extract(snapshot, '$.local_viewer_activity.attribution') = ?",
            (review_id, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, campaign_id, revision, fingerprint,
             VIEWER_ATTRIBUTION),
        ).fetchone()
        if row is None:
            raise ValueError("Choose a review for this approved package.")
        review = {"id": review_id, "created_at": row[0], **json.loads(row[1])}
        correction = self._latest_correction(db, review, approved["package"])
        if correction != review["proposal"].get("correction"):
            raise PackageConflict("The buyer correction changed. Run another review before preparing a test.")
        if (review["proposal"]["kind"] != "comparison_test"
                or not correction or correction["kind"] != "keep_takes"):
            raise ValueError("This preparation supports instruction tests with a keep-takes correction.")
        group = comparison_group(approved["package"], review["proposal"]["creative_version"])
        return {"package": approved["package"], "review": review, "correction": correction,
                "comparison": group["content"]}

    def save_instruction_test(self, db, source, instruction, *, inference=None):
        context = self.instruction_test_context(db, **source)
        options = {"inference": inference} if inference is not None else {}
        return self.drafts.save_instruction_test(
            db, context["package"], context["review"], context["correction"], instruction, **options,
        )

    def read(self, campaign_id, revision, fingerprint):
        response = {
            "scenarios": self.reporting.scenarios(), "review": None, "correction": None,
            "correction_choices": [{"id": key, "label": label} for key, label in CORRECTION_CHOICES.items()],
        }
        approved = self.drafts.read_approved_package(campaign_id, revision, fingerprint)
        if approved is None:
            return response
        with closing(sqlite3.connect(self.drafts.path)) as db:
            db.execute("BEGIN")
            row = db.execute(
                "SELECT id, created_at, snapshot FROM campaign_performance_reviews "
                "WHERE client_id = ? AND brand_id = ? AND campaign_id = ? AND revision = ? AND fingerprint = ? "
                "AND json_extract(snapshot, '$.local_viewer_activity.attribution') = ? "
                "ORDER BY last_requested_at DESC, id DESC LIMIT 1",
                (LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, campaign_id, revision, fingerprint, VIEWER_ATTRIBUTION),
            ).fetchone()
            if row:
                response["review"] = {"id": row[0], "created_at": row[1], **json.loads(row[2])}
                response["correction"] = self._latest_correction(db, response["review"], approved["package"])
        return response
