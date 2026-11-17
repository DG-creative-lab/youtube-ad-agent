"""Build the manual handoff for the fictional campaign."""
import hashlib
from pathlib import Path

from .creatives import EXAMPLES
from .domain.fingerprints import package_fingerprint as package_fingerprint
from .application.planner_context import assemble_package


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
    selected = EXAMPLES if examples is None else examples

    class LogicalContent:
        def content(self, example):
            return example_content(example, media_dir)

    return assemble_package(draft, selected, LogicalContent())


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
