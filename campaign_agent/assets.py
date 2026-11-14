"""Immutable brand-owned catalogs and private, content-addressed filesystem blobs.

The store is a trusted storage adapter, not an access policy. Staff commands check
current campaign access; public reads enter through an exact publication grant.
No method returns a public file URL or accepts a browser-supplied storage path.
"""
from contextlib import closing
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat

from .access import BrandScope, require_access
from .creatives import Example
from .handoff import media_sha256, package_fingerprint
from .migrations import migrate_path
from .workspaces import verify

MAX_BLOB_BYTES = 64 * 1024 * 1024


class AssetUnavailable(FileNotFoundError):
    pass


def asset_name(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}', name):
        raise ValueError('Use a media filename, without paths.')
    return name


def owner_key(scope):
    return package_fingerprint([scope.client_id, scope.brand_id])


def read_blob(root, scope, digest, size):
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest) or not 0 <= size <= MAX_BLOB_BYTES:
        raise AssetUnavailable('Private media is unavailable.')
    try:
        directory = os.open(Path(root) / owner_key(scope), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(digest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(fd, 'rb') as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise AssetUnavailable('Private media is unavailable.')
            data = file.read(size + 1)
    except OSError:
        raise AssetUnavailable('Private media is unavailable.') from None
    if len(data) != size or media_sha256(data) != digest:
        raise AssetUnavailable('Private media failed its content check.')
    return data


def write_blob(root, scope, digest, data):
    directory = Path(root) / owner_key(scope)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    pending = '.pending-' + secrets.token_hex(16)
    try:
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            try:
                # Atomic, no-overwrite publication. A crash leaves at most an unused
                # pending file, never a partially written digest visible to readers.
                os.link(pending, digest, src_dir_fd=folder, dst_dir_fd=folder, follow_symlinks=False)
            except FileExistsError:
                read_blob(root, scope, digest, len(data))
            os.fsync(folder)
        finally:
            os.unlink(pending, dir_fd=folder)
    finally:
        os.close(folder)


class CatalogMedia:
    def __init__(self, root, scope, assets):
        self.root, self.scope, self.assets = root, scope, assets

    def read_asset(self, name):
        entry = self.assets.get(asset_name(name))
        if entry is None:
            raise AssetUnavailable('Private media is unavailable.')
        return read_blob(self.root, self.scope, entry['digest'], entry['size'])


class AssetStore:
    def __init__(self, path, root):
        self.path, self.root = Path(path), Path(root).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        migrate_path(self.path)

    def import_catalog(self, context, campaign_id, examples, source, *, operator, access):
        """Trusted provisioning; no upload or ownership assertion endpoint is added."""
        require_access(operator, context, access, 'youtube:workspace.configure', campaign_id)
        examples = tuple(examples)
        if (not examples or any(e.scope != context.scope for e in examples)
                or len({e.ref for e in examples}) != len(examples)
                or len({e.creative_ref for e in examples}) != len(examples)):
            raise ValueError('Supply one version of each brand comparison.')
        names = sorted({asset_name(name) for e in examples for name in (e.preview, *(take[2] for take in e.takes))})
        # Serialize metadata publication behind the same write reservation as blob creation.
        # Existing blobs are never overwritten; an aborted import can only leave unused bytes.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            verify(db, context, campaign_id)
            assets = {}
            for name in names:
                file = Path(source) / name
                fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, 'rb') as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BLOB_BYTES:
                        raise ValueError('Use a bounded regular source media file.')
                    data = stream.read(MAX_BLOB_BYTES + 1)
                if len(data) > MAX_BLOB_BYTES:
                    raise ValueError('Media exceeds the local store limit.')
                digest = media_sha256(data)
                write_blob(self.root, context.scope, digest, data)
                assets[name] = {'digest': digest, 'size': len(data)}
                db.execute('INSERT INTO asset_blobs VALUES(?,?,?,?) ON CONFLICT DO NOTHING',
                           (context.scope.client_id, context.scope.brand_id, digest, len(data)))
            snapshot = {'examples': [asdict(e) for e in examples], 'assets': assets}
            catalog_id = package_fingerprint(snapshot)
            require_access(operator, context, access, 'youtube:workspace.configure', campaign_id)
            db.execute('INSERT INTO asset_catalogs VALUES(?,?,?,?) ON CONFLICT DO NOTHING',
                       (context.scope.client_id, context.scope.brand_id, catalog_id, json.dumps(snapshot)))
            return catalog_id

    def catalog(self, scope, catalog_id):
        if not isinstance(catalog_id, str) or not re.fullmatch('[0-9a-f]{64}', catalog_id):
            raise AssetUnavailable('Private media is unavailable.')
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT snapshot FROM asset_catalogs WHERE client_id=? AND brand_id=? AND id=?',
                             (scope.client_id, scope.brand_id, catalog_id)).fetchone()
            if row is None:
                raise AssetUnavailable('Private media is unavailable.')
            snapshot = json.loads(row[0])
            if package_fingerprint(snapshot) != catalog_id:
                raise AssetUnavailable('Private catalog failed its content check.')
            for entry in snapshot['assets'].values():
                if db.execute('SELECT size FROM asset_blobs WHERE client_id=? AND brand_id=? AND digest=?',
                              (scope.client_id, scope.brand_id, entry['digest'])).fetchone() != (entry['size'],):
                    raise AssetUnavailable('Private catalog has unavailable media.')
        examples = tuple(Example(**{**e, 'scope': BrandScope(**e['scope']),
                                    'takes': tuple(tuple(t) for t in e['takes'])}) for e in snapshot['examples'])
        if any(e.scope != scope for e in examples):
            raise AssetUnavailable('Private catalog owner is unavailable.')
        return examples, CatalogMedia(self.root, scope, snapshot['assets'])
