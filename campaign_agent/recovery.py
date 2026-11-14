"""Operator-only SQLite snapshot and immutable asset backup/restore.

Bundles are private local artifacts. Restore writes a new directory, invalidates
staff sessions/public grants, and never rewrites domain snapshots or receipts.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

from .access import BrandScope
from .assets import asset_name, read_blob, write_blob
from .handoff import package_fingerprint
from .migrations import MIGRATIONS, SchemaConflict, versions


def readonly(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('Choose an existing product database.')
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)


def file_digest(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def _blobs(db):
    return [dict(client_id=c, brand_id=b, digest=d, size=s) for c, b, d, s in
            db.execute('SELECT client_id,brand_id,digest,size FROM asset_blobs ORDER BY client_id,brand_id,digest')]


def _validate(db):
    if versions(db) != len(MIGRATIONS):
        raise SchemaConflict('Migrate the store before taking a versioned backup.')
    if db.execute('PRAGMA quick_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Database integrity checks failed.')
    for client, brand, catalog_id, raw in db.execute('SELECT client_id,brand_id,id,snapshot FROM asset_catalogs'):
        snapshot = json.loads(raw)
        if package_fingerprint(snapshot) != catalog_id or any(e['scope'] != {'client_id': client, 'brand_id': brand}
                                                             for e in snapshot['examples']):
            raise ValueError('Asset catalog identity or ownership changed.')
        for name, entry in snapshot['assets'].items():
            asset_name(name)
            if db.execute('SELECT size FROM asset_blobs WHERE client_id=? AND brand_id=? AND digest=?',
                          (client, brand, entry['digest'])).fetchone() != (entry['size'],):
                raise ValueError('Asset catalog references unavailable media.')


def _clear_sessions(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='staff_sessions'").fetchone():
        db.execute('DELETE FROM staff_sessions')


def _new_directory(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive reservation: never overwrite a live store or another backup.
    path.mkdir(mode=0o700)
    return path


def backup_store(path, assets, destination):
    with closing(readonly(path)) as source:
        _validate(source)
        destination = _new_directory(destination)
        try:
            target = destination / 'state.sqlite3'
            with closing(sqlite3.connect(target)) as copy:
                source.backup(copy)
                with copy:
                    _clear_sessions(copy)
                _validate(copy)
                blobs = _blobs(copy)
            os.chmod(target, 0o600)
            for entry in blobs:
                scope = BrandScope(entry['client_id'], entry['brand_id'])
                data = read_blob(assets, scope, entry['digest'], entry['size'])
                write_blob(destination / 'blobs', scope, entry['digest'], data)
            manifest = {'format': 1, 'schema_version': len(MIGRATIONS),
                        'database_sha256': file_digest(target), 'blobs': blobs}
            # Completion marker is last. An incomplete bundle cannot be restored.
            manifest_path = destination / 'manifest.json'
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
            os.chmod(manifest_path, 0o600)
            return manifest
        except BaseException:
            shutil.rmtree(destination)
            raise


def verify_backup(bundle):
    bundle = Path(bundle)
    database, marker = bundle / 'state.sqlite3', bundle / 'manifest.json'
    if database.is_symlink() or marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 32*1024*1024:
        raise ValueError('Choose a complete private backup bundle.')
    manifest = json.loads(marker.read_text())
    if (set(manifest) != {'format', 'schema_version', 'database_sha256', 'blobs'}
            or manifest['format'] != 1 or manifest['schema_version'] != len(MIGRATIONS)
            or file_digest(database) != manifest['database_sha256']):
        raise ValueError('Backup database or format verification failed.')
    with closing(readonly(database)) as db:
        _validate(db)
        if _blobs(db) != manifest['blobs']:
            raise ValueError('Backup asset inventory does not match the database.')
    for entry in manifest['blobs']:
        read_blob(bundle / 'blobs', BrandScope(entry['client_id'], entry['brand_id']), entry['digest'], entry['size'])
    return manifest


def restore_store(bundle, destination):
    bundle = Path(bundle)
    manifest = verify_backup(bundle)
    destination = _new_directory(destination)
    try:
        target = destination / 'state.sqlite3'
        shutil.copyfile(bundle / 'state.sqlite3', target)
        os.chmod(target, 0o600)
        # Recheck the bytes actually copied; do not trust an earlier path check.
        if file_digest(target) != manifest['database_sha256']:
            raise ValueError('Backup changed during restore.')
        for entry in manifest['blobs']:
            scope = BrandScope(entry['client_id'], entry['brand_id'])
            data = read_blob(bundle / 'blobs', scope, entry['digest'], entry['size'])
            write_blob(destination / 'blobs', scope, entry['digest'], data)
        with closing(sqlite3.connect(target)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            _validate(db)
            _clear_sessions(db)
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='public_comparisons'").fetchone():
                db.execute('UPDATE public_comparisons SET active=0')
        (destination / 'RESTORED').write_text('Restore verified. Staff sign-in and public grants must be established again.\n')
        return {'database': str(target), 'assets': str(destination / 'blobs'), 'asset_blobs': len(manifest['blobs'])}
    except BaseException:
        shutil.rmtree(destination)
        raise
