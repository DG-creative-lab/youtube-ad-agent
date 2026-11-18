"""Campaign draft, approval and handoff commands over scoped records."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re

from campaign_agent.ports.drafts import CampaignDraftReader, CampaignDraftRepository, CampaignDraftStorage, DraftReader, DraftRepository
from campaign_agent.domain.errors import StaleDraft, PackageConflict
from campaign_agent.domain.placements import VIDEO_ID
from campaign_agent.access import LOCAL_CONTEXT, LOCAL_OPERATOR, require_access
from campaign_agent.creatives import render_instruction_choices
from campaign_agent import handoff
from campaign_agent.handoff import example_content, package_blockers, package_fingerprint, sample_package


MAX_PLACEMENTS = 2400
MAX_DRAFT_BYTES = 2_000_000
CATALOG_SOURCES = {"creator_supplied", "licensed"}
DEFAULT_DRAFT_PATH = Path(__file__).resolve().parents[2] / ".local/campaign-drafts.sqlite3"
BRIEF = {
    "id": "tts-contexts",
    "revision": 1,
    "title": "Text to Speech · YouTube test",
    "goal": "Compare how voice delivery fits two different viewing contexts.",
    "approved_claims": [
        "ElevenLabs Text to Speech generates spoken audio from written text.",
    ],
    "contexts": {
        "video-editing": {
            "title": "Video editing",
            "creative_ref": "editing-voiceover",
            "destination_ref": "editing-comparison",
            "planned_assets": ["original-editing-clip", "editing-narration-takes"],
        },
        "audiobook": {
            "title": "Audiobook production",
            "creative_ref": "audiobook-reading",
            "destination_ref": "audiobook-comparison",
            "planned_assets": ["original-story-passage", "audiobook-narration-takes"],
        },
    },
}
POLICY = {
    "id": "local-campaign-rules",
    "revision": 1,
    "rules": [
        "Use original or permitted footage, text and audio.",
        "Keep fictional placements separate from real catalog placements.",
        "Confirm targeting in Google Ads before launch.",
    ],
}


class CampaignDrafts:
    def __init__(self, live, operator, *, context, access, media_dir, storage: CampaignDraftStorage,
                 new_id, campaign_id=None, examples=None):
        self.operator = operator
        self.context = context
        self.scope = context.scope
        self.access = access
        self.media_dir = media_dir
        self._storage = storage
        self._new_id = new_id
        self.live = live
        if campaign_id is None and context != LOCAL_CONTEXT:
            raise ValueError("Choose a provisioned campaign for this workspace.")
        self.campaign_id = campaign_id or ("tts-catalog" if live else "tts-sample")
        self._examples = None if examples is None and context == LOCAL_CONTEXT else tuple(examples or ())
        if (not self.examples or any(example.scope != self.scope for example in self.examples)
                or len({example.ref for example in self.examples}) != len(self.examples)
                or len({example.creative_ref for example in self.examples}) != len(self.examples)):
            raise PermissionError("Supply the brand's own comparison catalog.")
        self.sources = CATALOG_SOURCES if live else {"sample_search", "synthetic"}

    def _require_owner(self, repository: DraftReader):
        context = self.context
        if repository.owner_row(self.campaign_id) != (context.scope.client_id, context.scope.brand_id,
                                                     context.workspace_id, context.installation_id):
            raise PermissionError("The campaign is unavailable in this workspace.")

    def read_from(self, repository: DraftReader, revision=None):
        self.require("youtube:campaign.read")
        self._require_owner(repository)
        snapshot = repository.read_snapshot(self.campaign_id, revision)
        return json.loads(snapshot) if snapshot is not None else None

    def read(self, revision=None):
        route = getattr(self, "_placement_commands", None)
        if route is not None and route[1]():
            return route[0].read(revision)
        with self._storage.read() as records:
            return self.read_from(records, revision)

    def _package_scope(self, campaign_id, revision):
        self.require("youtube:campaign.read")
        if (self.live or campaign_id != self.campaign_id
                or type(revision) is not int or not 1 <= revision < 2**63):
            raise ValueError("Choose a valid sample campaign revision.")
        return self.scope.client_id, self.scope.brand_id, campaign_id

    def _review_from(self, records: CampaignDraftReader, campaign_id, revision):
        scope = self._package_scope(campaign_id, revision)
        latest = self.read_from(records)
        draft = latest if latest["revision"] == revision else self.read_from(records, revision)
        if draft is None:
            raise ValueError("Campaign revision unavailable.")
        draft = {**draft, "placements": self._validate_from(records, draft["placements"], draft["brief"]["contexts"])}
        package = sample_package(draft, self.media_dir, examples=self.examples)
        fingerprint = package_fingerprint(package)
        key = (*scope, revision, fingerprint)
        row = records.approval_row(key)
        approval = {"actor_id": row[0], "approved_at": row[1]} if row else None
        return {"package": package, "fingerprint": fingerprint, "approval": approval,
                "current_revision": latest["revision"], "blockers": package_blockers(package)}, key

    def _approval_history(self, records: CampaignDraftReader, scope):
        return [
            {"revision": revision, "fingerprint": fingerprint, "approved_at": approved_at,
             "snapshot_available": bool(available)}
            for revision, fingerprint, approved_at, available in records.approval_history(scope)
        ]

    def read_approved_package(self, campaign_id, revision, fingerprint):
        scope = self._package_scope(campaign_id, revision)
        with self._storage.read() as records:
            return self._approved_snapshot(records, (*scope, revision, fingerprint))

    def read_approved_from(self, records: CampaignDraftReader, campaign_id, revision, fingerprint):
        scope = self._package_scope(campaign_id, revision)
        return self._approved_snapshot(records, (*scope, revision, fingerprint))

    def _approved_snapshot(self, records: CampaignDraftReader, key):
        self._require_owner(records)
        row = records.approval_snapshot_row(key)
        if row is None or row[2] is None:
            return None
        return {"fingerprint": key[4], "approval": {"actor_id": row[0], "approved_at": row[1]},
                "package": json.loads(row[2])}

    def review_package(self, campaign_id, revision):
        with self._storage.read() as records:
            review, key = self._review_from(records, campaign_id, revision)
            review["history"] = self._approval_history(records, key[:3])
            return review

    def _require_current_package(self, review, revision, fingerprint):
        if review["current_revision"] != revision or review["fingerprint"] != fingerprint:
            raise PackageConflict("The package has changed. Load and review the latest draft.")
        if review["blockers"]:
            raise PackageConflict(" ".join(review["blockers"]))

    def approve_package(self, campaign_id, revision, fingerprint):
        with self._storage.write() as unit:
            records = unit.drafts
            self.require("youtube:campaign.approve")
            review, key = self._review_from(records, campaign_id, revision)
            self._require_current_package(review, revision, fingerprint)
            if review["approval"] is None:
                approved_at = datetime.now(timezone.utc).isoformat()
                self.require("youtube:campaign.approve")
                records.append_approval(key, self.operator.id, approved_at, json.dumps(review["package"]))
                review["approval"] = {"actor_id": self.operator.id, "approved_at": approved_at}
            review["history"] = self._approval_history(records, key[:3])
            unit.commit()
            return review

    def require_approved_from(self, records: CampaignDraftReader, campaign_id, revision, fingerprint):
        """Validate approval against the current unit and return the reviewed package."""
        review, _ = self._review_from(records, campaign_id, revision)
        self._require_current_package(review, revision, fingerprint)
        if review["approval"] is None:
            raise PackageConflict("Approve this revision before continuing.")
        return review

    def export_setup(self, campaign_id, revision, fingerprint):
        self.require("youtube:campaign.export")
        with self._storage.read() as records:
            review = self.require_approved_from(records, campaign_id, revision, fingerprint)
            self.require("youtube:campaign.export")
            return {
                "handoff": "Manual Google Ads setup example",
                "instructions": "Use this as a walkthrough. Replace fictional placements with verified targets "
                                "and replace local preview and viewer paths before a live campaign.",
                "approval": review["approval"],
                "fingerprint": fingerprint,
                **review["package"],
            }

    def register_catalog(self, rows):
        """Record independently supplied entries admitted by the local CLI."""
        self.require("youtube:catalog.write")
        entries = []
        for row in rows:
            reference = row.get("source_reference")
            if (not self.live or row["source"] not in CATALOG_SOURCES
                    or not isinstance(reference, str) or not reference.strip() or len(reference) > 500):
                raise ValueError("Catalog registration requires a creator-supplied or licensed source and a source_reference of up to 500 characters for each entry.")
            entries.append((row["video_id"], row["description"], row["source"], reference.strip()))

        scope = self.scope.client_id, self.scope.brand_id, self.campaign_id
        with self._storage.write() as unit:
            records = unit.drafts
            self.require("youtube:catalog.write")
            self._require_owner(records)
            for entry in entries:
                records.register_catalog_entry(scope, self._new_id(), entry)
            references = {entry[0]: records.catalog_ref(scope, entry) for entry in entries}
            unit.commit()
            return references

    def comparison_content(self, example, fingerprint, *, records: CampaignDraftReader | None = None):
        """Verify a content reference using current media and immutable instruction versions."""
        if example.scope != self.scope or example not in self.examples:
            raise PermissionError("The comparison is unavailable in this workspace.")
        content = example_content(example, self.media_dir)
        if self.live or package_fingerprint(content) == fingerprint:
            return content
        key = example.scope.client_id, example.scope.brand_id, example.creative_ref, example.ref
        if records is None:
            with self._storage.read() as reader:
                instructions = reader.instructions(*key)
        else:
            instructions = records.instructions(*key)
        for instruction in instructions:
            variant = {**content, "instruction": instruction}
            if package_fingerprint(variant) == fingerprint:
                return variant
        return content

    @staticmethod
    def validate_instruction(instruction, original):
        if (not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 500
                or instruction.strip() == original):
            raise ValueError("Provide revised comparison instructions of up to 500 characters.")
        return instruction.strip()

    def start_brief(self, campaign_id, revision, fingerprint, *, title, goal, context):
        """Start a brief from the approved comparison catalog in the sample workspace."""
        if (not isinstance(title, str) or not 0 < len(title.strip()) <= 120
                or not isinstance(goal, str) or not 0 < len(goal.strip()) <= 500
                or not isinstance(context, str) or context not in BRIEF["contexts"]):
            raise ValueError("Enter a brief title, goal and supported comparison context.")
        with self._storage.write() as unit:
            records = unit.drafts
            self.require("youtube:campaign.draft")
            review, _ = self._review_from(records, campaign_id, revision)
            if review["current_revision"] != revision or review["fingerprint"] != fingerprint:
                raise PackageConflict("The package has changed. Load and review the latest draft.")
            current = self.read_from(records)
            saved = {
                "campaign_id": campaign_id, "revision": revision + 1, "policy": POLICY,
                "brief": {**BRIEF, "id": self._new_id(), "title": title.strip(), "goal": goal.strip(),
                          "contexts": {context: BRIEF["contexts"][context]}},
                "placements": [row for row in current["placements"] if row["creative"] == context],
            }
            self.require("youtube:campaign.draft")
            records.append_snapshot(campaign_id, saved["revision"], json.dumps(saved))
            unit.commit()
        return saved

    def save_instruction_test_from(self, records: CampaignDraftRepository, package, review, correction, instruction, *, inference=None):
        """Persist one instruction change in the caller's validated review transaction."""
        self._package_scope(package["campaign_id"], package["revision"])
        group = next(group for group in package["groups"]
                     if group["creative_version"] == review["proposal"]["creative_version"])
        instruction = self.validate_instruction(instruction, group["content"]["instruction"])
        if inference is not None and inference.get("mode") == "openrouter":
            if render_instruction_choices(inference.get("wording_choices")) != instruction:
                raise ValueError("Provider instructions must match the approved components.")
        current = self.read_from(records)
        if current["revision"] != package["revision"]:
            raise StaleDraft(current)
        test = {
            "review_id": review["id"], "source_revision": package["revision"],
            "source_fingerprint": review["fingerprint"], "correction": correction,
            "creative_version": group["creative_version"],
            "before": group["content"]["instruction"], "after": instruction,
            "original_viewer_path": group["viewer_path"],
            "reason": review["proposal"]["reason"], "measure": review["proposal"]["measure"],
        }
        if "test_id" in review:
            test.update(source_test_id=review["test_id"], review_type="instruction_test")
        if inference is not None:
            test["inference"] = inference
        return self._save_instruction_revision_from(records, current, group, instruction, {"instruction_test": test})

    def _save_instruction_revision_from(self, records: CampaignDraftRepository, current, group, instruction, provenance):
        """Write the wording, its viewer version and provenance in the caller's transaction."""
        self.require("youtube:campaign.draft")
        self._require_owner(records)
        saved = {
            **current, "revision": current["revision"] + 1,
            "comparison_instructions": {**current.get("comparison_instructions", {}),
                                        group["creative_version"]: instruction},
            **provenance,
        }
        if "instruction_test" in provenance:
            saved.pop("instruction_reuse", None)
        versions = [(package_fingerprint({"instruction": text}), text)
                    for text in (group["content"]["instruction"], instruction)]
        records.add_instructions(self.scope.client_id, self.scope.brand_id, group["creative_version"],
                                 group["comparison_version"], versions)
        records.append_snapshot(self.campaign_id, saved["revision"], json.dumps(saved))
        return saved

    def save(self, payload, *, repository: DraftRepository | None = None):
        route = getattr(self, "_placement_commands", None)
        if repository is None and route is not None and route[1]():
            return route[0].save(payload)
        if not isinstance(payload, dict) or set(payload) != {"campaign_id", "revision", "placements"}:
            raise ValueError("Send a campaign ID, expected revision and placements.")
        expected = payload["revision"]
        if (payload["campaign_id"] != self.campaign_id
                or type(expected) is not int or not 1 <= expected < 2**63):
            raise ValueError("The campaign ID or revision is invalid.")
        rows = payload["placements"]
        if not isinstance(rows, list) or len(rows) > MAX_PLACEMENTS:
            raise ValueError(f"Save up to {MAX_PLACEMENTS} placements at a time.")

        if repository is not None:
            return self._save_from(repository, expected, rows)
        with self._storage.write() as unit:
            saved = self._save_from(unit.drafts, expected, rows)
            unit.commit()
            return saved

    def _save_from(self, repository: DraftRepository, expected, rows):
        self.require("youtube:campaign.draft")
        current = self.read_from(repository)
        placements = self._validate_from(repository, rows, current["brief"]["contexts"])
        revision = current["revision"]
        if expected != revision:
            if expected == revision - 1 and placements == current["placements"]:
                return current
            raise StaleDraft(current)
        if placements == current["placements"]:
            return current
        saved = {**current, "revision": revision + 1, "placements": placements}
        self.require("youtube:campaign.draft")
        repository.append_snapshot(self.campaign_id, saved["revision"], json.dumps(saved))
        return saved

    def require(self, capability):
        require_access(self.operator, self.context, self.access, capability, self.campaign_id)

    @property
    def examples(self):
        return handoff.EXAMPLES if self._examples is None else self._examples

    def _validate_from(self, repository: DraftReader, rows, contexts):
        seen, result = set(), []
        for row in rows:
            fields = ("id", "title", "creative", "source")
            if not isinstance(row, dict):
                raise ValueError("Each placement needs a video ID, title, context and source.")
            registered = "catalog_ref" in row
            if self.live or registered:
                fields += ("catalog_ref",)
            if set(row) not in (set(fields), set(fields) | ({"source_reference"} if registered else set())):
                raise ValueError("Use the required placement fields and registered catalog reference.")
            video_id, title, context, source = (row[key] for key in ("id", "title", "creative", "source"))
            if (not isinstance(source, str) or source not in self.sources | (CATALOG_SOURCES if registered else set())
                    or not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id) or video_id in seen
                    or not isinstance(context, str) or context not in contexts
                    or not isinstance(title, str) or not title.strip() or len(title) > 3000):
                raise ValueError("Use unique catalog video IDs, known contexts and permitted sources.")
            if self.live or registered:
                ref, entry = row["catalog_ref"], None
                if isinstance(ref, str) and re.fullmatch(r"[0-9a-f]{32}", ref):
                    if self.live:
                        entry = repository.live_catalog_entry(
                            self.scope.client_id, self.scope.brand_id, self.campaign_id, ref)
                    else:
                        entry = repository.placement_catalog_entry(
                            self.scope.client_id, self.scope.brand_id, self.campaign_id, ref)
                if (entry is None or entry[:3] != (video_id, title, source)
                        or not isinstance(entry[3], str) or not entry[3].strip()
                        or ("source_reference" in row and row["source_reference"] != entry[3])):
                    raise ValueError("The placement does not match a registered catalog entry.")
            seen.add(video_id)
            result.append({**{key: row[key] for key in fields},
                           **({"source_reference": entry[3]} if self.live or registered else {})})
        return result
