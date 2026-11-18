"""Scoped viewer visits, events and comparison completion."""

import re

from .creatives import EXAMPLES
from .domain.errors import PackageConflict
from .handoff import package_fingerprint
from .ports.viewer_storage import ViewerReader, ViewerStorage, ViewerWriter


class ViewerNotFound(LookupError):
    """The requested link, example or visit is outside the viewer's scope."""


class ViewerMeasurement:
    def __init__(self, storage: ViewerStorage, examples=EXAMPLES, *, campaign_id="tts-sample", clock_ms, new_visit_id):
        # Server composition selects the campaign. Public payloads cannot override it.
        self.storage, self.campaign_id = storage, campaign_id
        self._clock_ms, self._new_visit_id = clock_ms, new_visit_id
        self.examples = {example.ref: example for example in examples}
        self.links = {example.creative_ref: example for example in examples}

    def resolve(self, creative_ref, example_ref=None):
        origin = self.links.get(creative_ref)
        target = self.examples.get(example_ref) if example_ref is not None else origin
        if origin is None or target is None or origin.scope != target.scope:
            raise ViewerNotFound("This comparison is unavailable.")
        return origin, target

    def open_verified_ad(self, drafts, attribution, visit_id, *, rehearsal):
        with self.storage.write() as unit:
            link = unit.verified_setup_link(drafts.scope, drafts.campaign_id, attribution)
            if link is None:
                raise ViewerNotFound("This ad comparison is unavailable.")
            result = self._open_reviewed(
                drafts,
                {"creative_ref": link["creative_ref"], "example_ref": link["comparison_ref"], "visit_id": visit_id},
                link["content_fingerprint"], None, records=unit, ad_link_id=link["id"], rehearsal=rehearsal,
            )
            unit.commit()
            return {**result, "creative_ref": link["creative_ref"]}

    def open_reviewed(self, drafts, data, fingerprint, references):
        return self._open_reviewed(drafts, data, fingerprint, references)

    def _open_reviewed(self, drafts, data, fingerprint, references, *, records: ViewerWriter | None = None,
                       ad_link_id=None, rehearsal=False):
        if fingerprint is None and records is None:
            return self.open_example(**data)
        origin, example = self.resolve(data["creative_ref"], data["example_ref"])
        if references is None:
            references = {origin.ref: fingerprint}
        if references.get(origin.ref) != fingerprint or example.ref not in references:
            raise PackageConflict("The comparison has changed. Reload the package in the planner.")
        verified = {}
        for item in self.examples.values():
            if item.scope != origin.scope or item.ref not in references:
                continue
            content = drafts.comparison_content(item, references[item.ref],
                                                records=records.drafts if records is not None else None)
            if (package_fingerprint(content) == references[item.ref]
                    and all(take["sha256"] for take in content["takes"])):
                verified[item.ref] = content
        if not verified:
            raise PackageConflict("The comparison has changed. Reload the package in the planner.")
        selected_ref = example.ref if example.ref in verified else next(iter(verified))
        visit = {**data, "example_ref": selected_ref, "content_fingerprint": fingerprint,
                 "origin_unavailable": origin.ref not in verified, "ad_link_id": ad_link_id, "rehearsal": rehearsal}
        result = (self.open_example(**visit) if records is None else self.open_from(records, **visit))
        content = verified[selected_ref]
        comparison = result["example"]
        comparison["instruction"] = content["instruction"]
        for take, reviewed in zip(comparison["takes"], content["takes"]):
            take["url"] += "?sha256=" + reviewed["sha256"]
        comparison["captions"] += "?sha256=" + content["captions_sha256"]
        result["examples"] = [item for item in result["examples"] if item["ref"] in verified]
        if selected_ref != example.ref:
            result["notice"] = "That reviewed example is unavailable. Another verified example is open."
        return result

    def visit_key(self, origin, visit_id):
        return visit_id, origin.scope.client_id, origin.scope.brand_id, origin.creative_ref, self.campaign_id

    def require_visit(self, records: ViewerReader, origin, visit_id):
        visit = records.visit_attribution(self.visit_key(origin, visit_id))
        if visit is None:
            raise ViewerNotFound("This visit is unavailable.")
        return visit

    def summarize(self, scope, comparisons):
        """Count tagged visits and intended-example outcomes in one local snapshot."""
        with self.storage.read() as records:
            return self.summarize_from(records, scope, comparisons)

    def summarize_from(self, records: ViewerReader, scope, comparisons):
        observations = []
        for creative_ref, example_ref, fingerprint in comparisons:
            origin, example = self.resolve(creative_ref, example_ref)
            if origin.scope != scope or origin.ref != example.ref:
                raise ViewerNotFound("This comparison is unavailable.")
            arrivals, opened, completed, unattributed = records.comparison_counts(
                scope, self.campaign_id, creative_ref, example_ref, fingerprint)
            observations.append({
                "creative_version": creative_ref, "comparison_version": example_ref,
                "comparison_fingerprint": fingerprint, "unattributed_arrivals": unattributed,
                "arrivals": arrivals, "intended_opens": opened, "completions": completed,
                "completion_rate": completed / arrivals if arrivals else None,
            })
        return observations

    def open_example(self, creative_ref, example_ref=None, visit_id=None, **options):
        with self.storage.write() as unit:
            result = self.open_from(unit, creative_ref, example_ref, visit_id, **options)
            unit.commit()
            return result

    def open_from(self, records: ViewerWriter, creative_ref, example_ref=None, visit_id=None, *,
                  content_fingerprint=None, origin_unavailable=False, ad_link_id=None, rehearsal=False):
        origin, target = self.resolve(creative_ref, example_ref)
        if ad_link_id is not None and (target != origin or origin_unavailable or content_fingerprint is None):
            raise ViewerNotFound("This ad comparison is unavailable.")
        if visit_id is None:
            visit_id = self._new_visit_id()
            attribution = None if origin_unavailable else content_fingerprint
            records.add_visit(self.visit_key(origin, visit_id), attribution, ad_link_id, self._clock_ms(),
                              int(rehearsal) if ad_link_id is not None else None)
        else:
            attribution, saved_link = self.require_visit(records, origin, visit_id)
            if saved_link != ad_link_id:
                raise ViewerNotFound("This visit is unavailable.")
            # A visit with unknown content can resume, but later verification cannot attribute its old activity.
            if attribution is not None:
                if attribution != content_fingerprint:
                    raise ViewerNotFound("This visit is unavailable.")
                if origin_unavailable:
                    records.clear_attribution(visit_id)
        records.add_arrival(visit_id, target.ref)
        state = self.state(records, visit_id, target.ref)
        return {
            "visit_id": visit_id,
            "example": {
                "ref": target.ref, "title": target.title, "instruction": target.instruction,
                "passage": target.passage, "takes": [
                    {"id": take, "label": label, "video": name.endswith(".mp4"),
                     "url": f"/viewer/media/{creative_ref}/{target.ref}/{take}"}
                    for take, label, name in target.takes
                ],
                "captions": f"/viewer/media/{creative_ref}/{target.ref}/captions",
            },
            "examples": [
                {"ref": item.ref, "title": item.title}
                for item in self.examples.values() if item.scope == origin.scope
            ],
            **state,
        }

    @staticmethod
    def state(records: ViewerReader, visit_id, example_ref):
        return {"finished": records.finished_takes(visit_id, example_ref),
                "choice": records.last_choice(visit_id, example_ref),
                "complete": records.completed(visit_id, example_ref)}

    def record(self, creative_ref, visit_id, example_ref, event_id, kind, take):
        with self.storage.write() as unit:
            result = self.record_from(unit, creative_ref, visit_id, example_ref, event_id, kind, take)
            unit.commit()
            return result

    def record_from(self, records: ViewerWriter, creative_ref, visit_id, example_ref, event_id, kind, take,
                    *, expected_attribution: tuple[str, str] | None = None):
        origin, target = self.resolve(creative_ref, example_ref)
        takes = {item[0] for item in target.takes}
        if not re.fullmatch(r"[0-9a-f]{32}", event_id) or kind not in {"start", "finish", "choose"} or take not in takes:
            raise ValueError("Invalid comparison event.")
        event = (example_ref, kind, take)
        saved_attribution = self.require_visit(records, origin, visit_id)
        if expected_attribution is not None and saved_attribution != expected_attribution:
            raise ViewerNotFound("This visit is unavailable.")
        existing = records.event(visit_id, event_id)
        if existing is not None:
            if existing != event:
                raise ValueError("This event ID belongs to a different action.")
            return self.state(records, visit_id, example_ref)
        if records.event(visit_id, f"arrival:{example_ref}") is None:
            raise ViewerNotFound("Open this comparison before recording playback.")
        if kind == "finish" and not records.started(visit_id, example_ref, take):
            raise ValueError("Start this take before finishing it.")
        if kind == "choose" and set(records.finished_takes(visit_id, example_ref)) != takes:
            raise ValueError("Finish both takes before choosing.")
        records.add_event(visit_id, event_id, event)
        if kind == "choose":
            records.add_completion(visit_id, example_ref, take, self._clock_ms())
        return self.state(records, visit_id, example_ref)
