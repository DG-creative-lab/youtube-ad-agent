"""Read authored logical comparison media or capture immutable content facts."""
from copy import deepcopy
import hashlib
from pathlib import Path

from campaign_agent.domain.errors import PackageConflict
from campaign_agent.ports.storage_errors import StorageError
from campaign_agent.ports.planner_context import ComparisonContent, ComparisonExample


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


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
