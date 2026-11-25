"""Read authored logical comparison media or capture immutable content facts."""
from copy import deepcopy
from dataclasses import asdict
import json
import hashlib
from pathlib import Path

from campaign_agent.domain.errors import PackageConflict
from campaign_agent.ports.storage_errors import StorageError
from campaign_agent.ports.planner_context import ComparisonContent, ComparisonExample


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


MEDIA_MANIFEST = "media-manifest.json"


def comparison_media_manifest(directory, examples):
    """Trusted authoring records which definitions produced these exact files."""
    names = {name for example in examples for name in (example.preview, *(t[2] for t in example.takes))}
    return {
        "schema": "comparison-media/v1",
        # Scope is authorized by CampaignDrafts/the private asset catalog. The
        # recording binding describes content, so a permitted rescope of the
        # same authored demo does not claim different spoken words.
        "examples": json.loads(json.dumps([
            {key: value for key, value in asdict(example).items() if key != "scope"}
            for example in examples
        ])),
        "files": {name: _sha256((directory / name).read_bytes()) for name in sorted(names)},
    }


def write_media_manifest(directory, examples):
    manifest = comparison_media_manifest(directory, examples)
    pending = directory / (MEDIA_MANIFEST + ".pending")
    pending.write_text(json.dumps(manifest, indent=2) + "\n")
    pending.replace(directory / MEDIA_MANIFEST)


class BoundLocalMedia:
    """Freeze a verified local script/file pairing, including across later reads."""
    def __init__(self, directory, examples, *, bundled_directory, bundled_examples):
        message = ("Local comparison media does not match the current example definitions. "
                   "Back up .local/viewer-media, then regenerate it with "
                   "python3 -m scripts.prepare_viewer_media, or replace it with the current "
                   "bundled examples/viewer-media files. Restart and review the new package.")
        examples = tuple(examples)
        try:
            current = comparison_media_manifest(directory, examples)
            manifest = directory / MEDIA_MANIFEST
            if manifest.exists():
                if manifest.stat().st_size > 1_000_000:
                    raise ValueError(message)
                expected = json.loads(manifest.read_text())
            else:
                # A manifest-free copy is safe only when every byte matches our
                # known current bundle and its actual authored definitions.
                expected = comparison_media_manifest(bundled_directory, bundled_examples)
            if current != expected:
                raise ValueError(message)
        except (OSError, ValueError):
            raise ValueError(message) from None
        self.directory, self.files = directory, current["files"]

    def read_asset(self, name):
        if name not in self.files:
            raise FileNotFoundError("Local comparison media is unavailable.")
        data = (self.directory / name).read_bytes()
        if _sha256(data) != self.files[name]:
            raise FileNotFoundError("Local comparison media changed; regenerate and restart before review.")
        return data


class CapturedMedia:
    def __init__(self, contents, validate=None):
        self._contents = deepcopy(contents)
        self._validate = validate

    def validate(self):
        if self._validate is not None:
            self._validate()

    def content(self, example: ComparisonExample) -> ComparisonContent:
        return deepcopy(self._contents[example.ref])


class LocalMedia:
    """Capture immutable logical facts and revalidate local bytes at acceptance."""
    def __init__(self, source):
        self._source = source

    def _read_asset(self, name):
        return (self._source.read_asset(name) if hasattr(self._source, 'read_asset')
                else (Path(self._source) / name).read_bytes())

    def content(self, example: ComparisonExample) -> ComparisonContent:
        def asset(name):
            try:
                return _sha256(self._read_asset(name))
            except FileNotFoundError:
                return None
            except OSError:
                raise StorageError('media', 'The authored comparison media is unavailable.') from None

        names = {example.preview, *(name for _, _, name in example.takes)}
        hashes = {name: asset(name) for name in names}
        captions = f"WEBVTT\n\n00:00:00.000 --> 00:00:08.000\n{example.passage}\n".encode()
        return {
            'title': example.title, 'instruction': example.instruction,
            'passage': example.passage, 'captions_sha256': _sha256(captions),
            'takes': [{'id': take, 'label': label, 'asset': name, 'sha256': hashes[name]}
                      for take, label, name in example.takes],
            'preview_sha256': hashes[example.preview],
        }

    def capture(self, examples):
        examples = tuple(examples)
        contents = {example.ref: self.content(example) for example in examples}

        def validate():
            if {example.ref: self.content(example) for example in examples} != contents:
                raise PackageConflict('The campaign media changed. Read the latest package before continuing.')
        return CapturedMedia(contents, validate)
