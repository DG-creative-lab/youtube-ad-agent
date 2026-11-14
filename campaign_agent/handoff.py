"""Build the manual handoff for the fictional campaign."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

from .creatives import EXAMPLES


MEDIA_DIR = Path(__file__).resolve().parents[1] / ".local/viewer-media"
DEMO_MEDIA_DIR = Path(__file__).resolve().parents[1] / "examples/viewer-media"


def media_sha256(data):
    return hashlib.sha256(data).hexdigest()


def caption_bytes(example):
    return f"WEBVTT\n\n00:00:00.000 --> 00:00:08.000\n{example.passage}\n".encode()


def read_media(source, name):
    """The portable demo uses Path; hosted composition supplies scoped private media."""
    return source.read_asset(name) if hasattr(source, 'read_asset') else (source / name).read_bytes()


def example_content(example, media_dir):
    def asset(name):
        try:
            return media_sha256(read_media(media_dir, name))
        except FileNotFoundError:
            return None

    names = {example.preview, *(name for _, _, name in example.takes)}
    hashes = {name: asset(name) for name in names}
    return {
        "title": example.title,
        "instruction": example.instruction,
        "passage": example.passage,
        "captions_sha256": media_sha256(caption_bytes(example)),
        "takes": [
            {"id": take, "label": label, "asset": name, "sha256": hashes[name]}
            for take, label, name in example.takes
        ],
        "preview_sha256": hashes[example.preview],
    }


def sample_package(draft, media_dir, *, examples=None):
    examples = {example.ref: example for example in (EXAMPLES if examples is None else examples)}
    groups = []
    for context, brief in draft["brief"]["contexts"].items():
        example = examples[brief["destination_ref"] + "-v1"]
        content = example_content(example, media_dir)
        content["instruction"] = draft.get("comparison_instructions", {}).get(example.creative_ref, example.instruction)
        preview_hash = content["preview_sha256"]
        groups.append({
            "context": context,
            "title": brief["title"],
            "creative_version": example.creative_ref,
            "preview_asset": example.preview,
            "preview_path": (
                f"/viewer/media/{example.creative_ref}/{example.ref}/preview?sha256={preview_hash}"
                if preview_hash else None
            ),
            "comparison_version": example.ref,
            "content": content,
            "placements": [
                {"demo_id": row["id"], "title": row["title"], "source": row["source"],
                 "label": "Catalog candidate · inventory unverified" if row["source"] in {"licensed", "creator_supplied"} else "Fictional placement",
                 **({"catalog_ref": row["catalog_ref"]} if "catalog_ref" in row else {}),
                 **({"source_reference": row["source_reference"]} if "source_reference" in row else {})}
                for row in draft["placements"] if row["creative"] == context
            ],
        })
    references = [(group["comparison_version"], package_fingerprint(group["content"])) for group in groups]
    for group, (_, fingerprint) in zip(groups, references):
        query = [("ad", group["creative_version"]), ("content", fingerprint)]
        query.extend(("reviewed", f"{ref}:{digest}") for ref, digest in references)
        group["viewer_path"] = "/viewer?" + urlencode(query)
    return {
        "campaign_id": draft["campaign_id"],
        "revision": draft["revision"],
        "data_label": ("Catalog candidates · inventory unverified" if any(row["source"] in {"licensed", "creator_supplied"}
                       for row in draft["placements"]) else "Fictional placements for an offline sample"),
        "title": draft["brief"]["title"],
        "brief": {"id": draft["brief"]["id"], "revision": draft["brief"]["revision"]},
        "policy": {"id": draft["policy"]["id"], "revision": draft["policy"]["revision"]},
        "proposed_setup": {
            "objective": draft["brief"]["goal"],
            "format": "YouTube video ad example",
            "budget": "Unset for the offline sample",
            "schedule": "Unscheduled",
        },
        "groups": groups,
        **({"instruction_test": draft["instruction_test"]} if "instruction_test" in draft else {}),
        **({"instruction_reuse": draft["instruction_reuse"]} if "instruction_reuse" in draft else {}),
    }


def package_blockers(package):
    blockers = []
    for group in package["groups"]:
        title = group["title"]
        if not group["placements"]:
            blockers.append(f"Add placements for {title}.")
        content = group["content"]
        if not content["preview_sha256"] or any(not take["sha256"] for take in content["takes"]):
            blockers.append(f"Prepare the preview and comparison media for {title}.")
    return blockers


def package_fingerprint(package):
    encoded = json.dumps(package, sort_keys=True, separators=(",", ":")).encode()
    return media_sha256(encoded)
