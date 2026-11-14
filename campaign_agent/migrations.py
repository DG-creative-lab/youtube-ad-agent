"""Transactional, append-only migration journal for ownership and private assets.

Domain-specific legacy admission stays with its owning commands. These migrations
never rebuild campaign JSON, infer a customer owner, or rewrite approvals.
"""
from contextlib import closing
import hashlib
import sqlite3


class SchemaConflict(RuntimeError):
    pass


def immutable(table):
    return tuple(f'''CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()}
        BEFORE {operation} ON {table} BEGIN
        SELECT RAISE(ABORT,'Product ownership or asset version is immutable'); END'''
        for operation in ('UPDATE', 'DELETE'))


MIGRATIONS = (
    ('product-ownership', (
        '''CREATE TABLE IF NOT EXISTS brand_workspaces (
            client_id TEXT NOT NULL, brand_id TEXT NOT NULL, workspace_id TEXT NOT NULL UNIQUE,
            installation_id TEXT NOT NULL, PRIMARY KEY(client_id,brand_id))''',
        '''CREATE TABLE IF NOT EXISTS campaign_owners (
            campaign_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL)''',
        *immutable('brand_workspaces'), *immutable('campaign_owners'),
    )),
    ('private-asset-versions', (
        '''CREATE TABLE asset_blobs (
            client_id TEXT NOT NULL, brand_id TEXT NOT NULL, digest TEXT NOT NULL,
            size INTEGER NOT NULL CHECK(size>=0), PRIMARY KEY(client_id,brand_id,digest),
            FOREIGN KEY(client_id,brand_id) REFERENCES brand_workspaces(client_id,brand_id))''',
        '''CREATE TABLE asset_catalogs (
            client_id TEXT NOT NULL, brand_id TEXT NOT NULL, id TEXT NOT NULL,
            snapshot TEXT NOT NULL, PRIMARY KEY(client_id,brand_id,id),
            FOREIGN KEY(client_id,brand_id) REFERENCES brand_workspaces(client_id,brand_id))''',
        *immutable('asset_blobs'), *immutable('asset_catalogs'),
        *(f'''CREATE TRIGGER {table}_owner BEFORE INSERT ON {table}
            WHEN NOT EXISTS(SELECT 1 FROM brand_workspaces
                            WHERE client_id=NEW.client_id AND brand_id=NEW.brand_id)
            BEGIN SELECT RAISE(ABORT,'Asset owner must be provisioned'); END'''
          for table in ('asset_blobs', 'asset_catalogs')),
    )),
)


def _checksum(statements):
    return hashlib.sha256('\n'.join(statements).encode()).hexdigest()


def versions(db):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='product_schema_migrations' AND type='table'").fetchone()
    rows = db.execute('SELECT version,name,checksum FROM product_schema_migrations ORDER BY version').fetchall() if exists else []
    for expected, (version, name, checksum) in enumerate(rows, 1):
        if (version != expected or version > len(MIGRATIONS)
                or (name, checksum) != (MIGRATIONS[version-1][0], _checksum(MIGRATIONS[version-1][1]))):
            raise SchemaConflict('Unknown, incomplete or changed storage migration history. Use the matching application release.')
    if rows:
        _check_ownership_schema(db, allow_missing=False)
    return len(rows)


def _check_ownership_schema(db, *, allow_missing):
    expected = {
        'brand_workspaces': (('client_id', 'brand_id', 'workspace_id', 'installation_id'),
                             ('client_id', 'brand_id'), {'client_id', 'brand_id', 'workspace_id', 'installation_id'}),
        # Preserve the original SQLite TEXT PRIMARY KEY declaration for campaign_id;
        # it reports notnull=0. Native provisioning rejects null IDs, and admission
        # below also refuses any existing null identity instead of inventing an owner.
        'campaign_owners': (('campaign_id', 'client_id', 'brand_id'), ('campaign_id',), {'client_id', 'brand_id'}),
    }
    for table, (columns, primary_key, required_nonnull) in expected.items():
        existing = db.execute(f'PRAGMA table_info({table})').fetchall()
        if not existing and allow_missing:
            continue
        actual_pk = tuple(row[1] for row in sorted(existing, key=lambda row: row[5]) if row[5])
        nonnull = {row[1] for row in existing if row[3]}
        unique_keys = set()
        for name, unique, partial in db.execute('SELECT name,"unique",partial FROM pragma_index_list(?)', (table,)):
            if unique and not partial:
                # Partial/expression/composite alternatives cannot substitute for
                # a full key. Bind legacy index names as data, not SQL identifiers.
                key = db.execute('SELECT name,coll FROM pragma_index_xinfo(?) WHERE key=1 ORDER BY seqno', (name,)).fetchall()
                if all(column is not None and collation == 'BINARY' for column, collation in key):
                    unique_keys.add(tuple(column for column, _ in key))
        required_unique = {primary_key} | ({('workspace_id',)} if table == 'brand_workspaces' else set())
        if (tuple(row[1] for row in existing) != columns or actual_pk != primary_key
                or any(row[2].upper() != 'TEXT' for row in existing)
                or not required_nonnull <= nonnull or not required_unique <= unique_keys):
            raise SchemaConflict('Ownership schema keys, uniqueness or nullability need explicit reconciliation before migration.')
        if db.execute(f'SELECT 1 FROM {table} WHERE ' + ' OR '.join(f'{column} IS NULL' for column in columns)).fetchone():
            raise SchemaConflict('Ownership has null identities; migration cannot infer their owner.')
    owners = db.execute("SELECT 1 FROM sqlite_master WHERE name='campaign_owners' AND type='table'").fetchone()
    brands = db.execute("SELECT 1 FROM sqlite_master WHERE name='brand_workspaces' AND type='table'").fetchone()
    if owners and db.execute('SELECT 1 FROM campaign_owners LIMIT 1').fetchone():
        if not brands or db.execute('''SELECT 1 FROM campaign_owners c WHERE NOT EXISTS (
            SELECT 1 FROM brand_workspaces b WHERE b.client_id=c.client_id AND b.brand_id=c.brand_id)''').fetchone():
            raise SchemaConflict('Legacy ownership has unbound brands; migration cannot infer their owner.')


def migrate(db, *, target=None):
    """Caller holds BEGIN IMMEDIATE; DDL and journal entries commit together."""
    if not db.in_transaction:
        raise ValueError('Migrations require an explicit write transaction.')
    current = versions(db)
    target = len(MIGRATIONS) if target is None else target
    if type(target) is not int or not current <= target <= len(MIGRATIONS):
        raise SchemaConflict('Only supported forward migrations are allowed; restore a backup for rollback.')
    if current == 0:
        _check_ownership_schema(db, allow_missing=True)
    db.execute('''CREATE TABLE IF NOT EXISTS product_schema_migrations (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    for index in range(current, target):
        name, statements = MIGRATIONS[index]
        for sql in statements:
            db.execute(sql)
        db.execute('INSERT INTO product_schema_migrations(version,name,checksum) VALUES(?,?,?)',
                   (index+1, name, _checksum(statements)))
    return target


def migrate_path(path, *, target=None):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        return migrate(db, target=target)
