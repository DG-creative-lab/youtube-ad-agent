"""Native history, concurrent commands, scoped bytes and real recovery; all offline."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier, Event
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from campaign_agent.access import LOCAL_CONTEXT, LOCAL_OPERATOR, Operator, WorkspaceContext, BrandScope
from campaign_agent.adapters.fixture_access import offline_fixture
from campaign_agent.agent.run import AgentRuntime, DEMO_REQUEST
from campaign_agent.assets import AssetStore, AssetUnavailable, owner_key
from campaign_agent.creatives import EXAMPLES
from campaign_agent.handoff import DEMO_MEDIA_DIR, package_fingerprint
from campaign_agent import migrations
from campaign_agent.migrations import migrate_path, SchemaConflict, versions
from campaign_agent.recovery import backup_store, restore_store, verify_backup
from campaign_agent.workspaces import provision_workspace
from scripts.campaign_drafts import StaleDraft
from scripts.compare_instruction_policies import walkthrough
import test_hosted_access as hosted_fixtures
from test_tenant_workspaces import Decisions


def rows(path, omit=()):
    with closing(sqlite3.connect(path)) as db:
        tables = [name for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name: sorted(db.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(), key=repr)
                for name in tables if name not in omit}


def legacy_ownership(db):
    # Authored pre-#37 structural shape, without the new journal or asset tables.
    db.execute('''CREATE TABLE IF NOT EXISTS brand_workspaces (
        client_id TEXT NOT NULL, brand_id TEXT NOT NULL, workspace_id TEXT NOT NULL UNIQUE,
        installation_id TEXT NOT NULL, PRIMARY KEY(client_id,brand_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS campaign_owners (
        campaign_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL)''')


class ProductStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.path = self.directory / 'state.sqlite3'
        self.root = self.directory / 'private-blobs'
        self.policy = Decisions()

    def hosted(self):
        case = hosted_fixtures.HostedAccessTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_unversioned_learning_history_migrates_and_restores_exactly(self):
        with patch('campaign_agent.workspaces.migrate', side_effect=legacy_ownership):
            learning = walkthrough(self.path)
            old = AgentRuntime(self.path, media_dir=DEMO_MEDIA_DIR)
            revision = learning['draft_revision']
            fingerprint = old.drafts.review_package('tts-sample', revision)['fingerprint']
            approved = old.drafts.approve_package('tts-sample', revision, fingerprint)
            setup = old.setup.validate('tts-sample', revision, fingerprint)
            old.setup.create('tts-sample', revision, fingerprint, setup['id'])
        before = rows(self.path)
        self.assertNotIn('product_schema_migrations', before)
        self.assertTrue(before['instruction_findings'])
        self.assertTrue(before['instruction_test_evidence_snapshots'])
        self.assertTrue(before['simulated_campaigns'])
        migrate_path(self.path)
        store = AssetStore(self.path, self.root)
        catalog = store.import_catalog(LOCAL_CONTEXT, 'tts-sample', EXAMPLES, DEMO_MEDIA_DIR,
                                       operator=LOCAL_OPERATOR, access=self.policy)
        after = rows(self.path)
        for table, history in before.items():
            self.assertEqual(after[table], history, table)
        examples, media = store.catalog(LOCAL_CONTEXT.scope, catalog)
        reopened = AgentRuntime(self.path, media_dir=media, examples=examples)
        self.assertEqual(reopened.drafts.review_package('tts-sample', revision), approved)
        backup = self.directory / 'backup'
        backup_store(self.path, self.root, backup)
        restored = self.directory / 'restored'
        result = restore_store(backup, restored)
        restored_rows = rows(result['database'])
        for table, history in after.items():
            self.assertEqual(restored_rows[table], history, table)
        recovered_store = AssetStore(result['database'], result['assets'])
        examples, media = recovered_store.catalog(LOCAL_CONTEXT.scope, catalog)
        recovered = AgentRuntime(result['database'], examples=examples, media_dir=media)
        self.assertEqual(recovered.drafts.review_package('tts-sample', revision), approved)
        self.assertEqual(recovered.setup.read('tts-sample', revision, fingerprint)['status'], 'verified')
        for _, _, _, _, saved_hash, _, _, snapshot in restored_rows['campaign_package_approvals']:
            self.assertEqual(package_fingerprint(json.loads(snapshot)), saved_hash)

    def test_migrations_are_serialized_atomic_and_reject_unknown_history(self):
        migrate_path(self.path, target=1)
        with patch.object(migrations, 'MIGRATIONS', (migrations.MIGRATIONS[0],
                ('broken-upgrade', ('CREATE TABLE partial_upgrade(id INTEGER)', 'INVALID SQL')))):
            with self.assertRaises(sqlite3.OperationalError):
                migrate_path(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(versions(db), 1)
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='partial_upgrade'").fetchone())
        barrier = Barrier(3)
        def upgrade():
            barrier.wait(timeout=10)
            return migrate_path(self.path)
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(list(pool.map(lambda _: upgrade(), range(3))), [3, 3, 3])
        prior = rows(self.path)
        migrate_path(self.path)
        self.assertEqual(rows(self.path), prior)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO product_schema_migrations(version,name,checksum) VALUES(4,'future','unknown')")
        with self.assertRaises(SchemaConflict):
            migrate_path(self.path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM product_schema_migrations WHERE version=4')
            db.execute("UPDATE product_schema_migrations SET checksum='changed' WHERE version=1")
        with self.assertRaises(SchemaConflict):
            migrate_path(self.path)

    def test_unknown_legacy_ownership_is_not_adopted_or_partly_migrated(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE campaign_owners(campaign_id TEXT, owner_guess TEXT)')
            db.execute("INSERT INTO campaign_owners VALUES('unknown','untrusted')")
        before = rows(self.path)
        with self.assertRaises(SchemaConflict):
            migrate_path(self.path)
        self.assertEqual(rows(self.path), before)

    def test_same_column_legacy_schema_requires_ownership_constraints(self):
        brand = '''CREATE TABLE brand_workspaces (
            client_id TEXT NOT NULL, brand_id TEXT NOT NULL, workspace_id TEXT NOT NULL UNIQUE,
            installation_id TEXT NOT NULL, PRIMARY KEY(client_id,brand_id))'''
        campaign = '''CREATE TABLE campaign_owners (
            campaign_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL)'''
        variants = [
            ('no-constraints', 'CREATE TABLE brand_workspaces(client_id TEXT,brand_id TEXT,workspace_id TEXT,installation_id TEXT)',
             'CREATE TABLE campaign_owners(campaign_id TEXT,client_id TEXT,brand_id TEXT)', None),
            ('brand-primary-key', brand.replace(', PRIMARY KEY(client_id,brand_id)', ''), campaign, None),
            ('brand-wrong-primary-key', brand.replace('PRIMARY KEY(client_id,brand_id)', 'PRIMARY KEY(workspace_id)'), campaign, None),
            ('workspace-unique', brand.replace('NOT NULL UNIQUE', 'NOT NULL'), campaign, None),
            ('workspace-composite-unique', brand.replace('NOT NULL UNIQUE', 'NOT NULL'), campaign,
             'CREATE UNIQUE INDEX workspace_identity ON brand_workspaces(workspace_id,client_id)'),
            ('workspace-partial-unique', brand.replace('NOT NULL UNIQUE', 'NOT NULL'), campaign,
             "CREATE UNIQUE INDEX workspace_identity ON brand_workspaces(workspace_id) WHERE brand_id<>'excluded'"),
            ('workspace-expression-unique', brand.replace('NOT NULL UNIQUE', 'NOT NULL'), campaign,
             'CREATE UNIQUE INDEX workspace_identity ON brand_workspaces(lower(workspace_id))'),
            ('workspace-nocase-unique', brand.replace('NOT NULL UNIQUE', 'NOT NULL'), campaign,
             'CREATE UNIQUE INDEX workspace_identity ON brand_workspaces(workspace_id COLLATE NOCASE)'),
            ('workspace-type-affinity', brand.replace('workspace_id TEXT', 'workspace_id INTEGER'), campaign, None),
            ('campaign-primary-key', brand, campaign.replace('TEXT PRIMARY KEY', 'TEXT'), None),
            ('campaign-wrong-primary-key', brand, campaign.replace('campaign_id TEXT PRIMARY KEY', 'campaign_id TEXT')[:-1] + ', PRIMARY KEY(campaign_id,client_id))', None),
        ]
        for column in ('client_id', 'brand_id', 'workspace_id', 'installation_id'):
            variants.append(('brand-nullable-' + column, brand.replace(column + ' TEXT NOT NULL', column + ' TEXT'), campaign, None))
        for column in ('client_id', 'brand_id'):
            variants.append(('campaign-nullable-' + column, brand, campaign.replace(column + ' TEXT NOT NULL', column + ' TEXT'), None))
        for label, brand_sql, campaign_sql, index_sql in variants:
            with self.subTest(schema=label):
                path = self.directory / (label + '.sqlite3')
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute(brand_sql)
                    db.execute(campaign_sql)
                    if index_sql:
                        db.execute(index_sql)
                    schema = db.execute('SELECT name,sql FROM sqlite_master ORDER BY name').fetchall()
                before = rows(path)
                with self.assertRaises(SchemaConflict):
                    migrate_path(path)
                context = WorkspaceContext(BrandScope('client-a', 'brand'), 'workspace-a', 'install-a')
                with self.assertRaises(SchemaConflict):
                    provision_workspace(path, context, 'campaign-a',
                                        operator=Operator('provisioner', frozenset({context.scope})), access=self.policy)
                self.assertEqual(rows(path), before)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('SELECT name,sql FROM sqlite_master ORDER BY name').fetchall(), schema)
                # Simulate a weak schema adopted by the earlier implementation.
                # A valid journal must not bypass verification on the next command.
                with patch('campaign_agent.migrations._check_ownership_schema'):
                    migrate_path(path)
                adopted = rows(path)
                with self.assertRaises(SchemaConflict):
                    migrate_path(path)
                with self.assertRaises(SchemaConflict):
                    provision_workspace(path, context, 'campaign-a',
                                        operator=Operator('provisioner', frozenset({context.scope})), access=self.policy)
                self.assertEqual(rows(path), adopted)

    def test_constrained_legacy_schema_keeps_workspace_unique_across_clients(self):
        for explicit_index in (False, True):
            with self.subTest(explicit_unique_index=explicit_index):
                path = self.directory / f'valid-{explicit_index}.sqlite3'
                with closing(sqlite3.connect(path)) as db, db:
                    if explicit_index:
                        db.execute('''CREATE TABLE brand_workspaces (
                            client_id TEXT NOT NULL,brand_id TEXT NOT NULL,workspace_id TEXT NOT NULL,
                            installation_id TEXT NOT NULL,PRIMARY KEY(client_id,brand_id))''')
                        db.execute('CREATE UNIQUE INDEX "workspace \' uniqueness" ON brand_workspaces(workspace_id)')
                        db.execute('CREATE TABLE campaign_owners(campaign_id TEXT NOT NULL PRIMARY KEY,client_id TEXT NOT NULL,brand_id TEXT NOT NULL)')
                    else:
                        legacy_ownership(db)
                migrate_path(path)
                a = WorkspaceContext(BrandScope('client-a', 'brand'), 'shared-workspace', 'install-a')
                b = WorkspaceContext(BrandScope('client-b', 'brand'), 'shared-workspace', 'install-b')
                operator = Operator('provisioner', frozenset({a.scope, b.scope}))
                provision_workspace(path, a, 'campaign-a', operator=operator, access=self.policy)
                before = rows(path)
                with self.assertRaises(PermissionError):
                    provision_workspace(path, b, 'campaign-b', operator=operator, access=self.policy)
                self.assertEqual(rows(path), before)

    def test_immutable_asset_versions_keep_approved_content_and_owner(self):
        runtime = AgentRuntime(self.path, media_dir=DEMO_MEDIA_DIR)
        runtime.resume(runtime.start(DEMO_REQUEST))
        fingerprint = runtime.drafts.review_package('tts-sample', 2)['fingerprint']
        approved = runtime.drafts.approve_package('tts-sample', 2, fingerprint)
        store = AssetStore(self.path, self.root)
        first = store.import_catalog(LOCAL_CONTEXT, 'tts-sample', EXAMPLES, DEMO_MEDIA_DIR,
                                     operator=LOCAL_OPERATOR, access=self.policy)
        self.assertEqual(store.import_catalog(LOCAL_CONTEXT, 'tts-sample', EXAMPLES, DEMO_MEDIA_DIR,
                                              operator=LOCAL_OPERATOR, access=self.policy), first)
        changed = self.directory / 'changed'
        shutil.copytree(DEMO_MEDIA_DIR, changed)
        (changed / 'editing-a.mp4').write_bytes((DEMO_MEDIA_DIR / 'editing-b.mp4').read_bytes())
        second = store.import_catalog(LOCAL_CONTEXT, 'tts-sample', EXAMPLES, changed,
                                      operator=LOCAL_OPERATOR, access=self.policy)
        self.assertNotEqual(first, second)
        original_examples, original_media = store.catalog(LOCAL_CONTEXT.scope, first)
        self.assertEqual(AgentRuntime(self.path, examples=original_examples, media_dir=original_media).drafts.review_package('tts-sample', 2), approved)
        self.assertNotEqual(original_media.read_asset('editing-a.mp4'), store.catalog(LOCAL_CONTEXT.scope, second)[1].read_asset('editing-a.mp4'))
        for table in ('asset_blobs', 'asset_catalogs'):
            for operation in (f'DELETE FROM {table}', f'UPDATE {table} SET client_id=client_id'):
                with closing(sqlite3.connect(self.path)) as db, db, self.assertRaises(sqlite3.IntegrityError):
                    db.execute(operation)
        with closing(sqlite3.connect(self.path)) as db, db, self.assertRaises(sqlite3.IntegrityError):
            db.execute('INSERT INTO asset_blobs VALUES(?,?,?,?)', ('foreign', 'brand', 'a'*64, 0))
        for name in ('../state.sqlite3', '/etc/passwd', 'nested/file'):
            with self.assertRaises(ValueError):
                original_media.read_asset(name)

    def test_scoped_http_media_cannot_return_another_clients_bytes(self):
        case = self.hosted()
        args = case.prepare()
        a = case.buyer.get('/api/campaign/package', params={'revision': 2}).json()
        store = AssetStore(case.path, case.path.with_suffix('.assets'))
        context = WorkspaceContext(BrandScope('tenant-b', 'brand'), 'workspace-b', 'install-b')
        examples = tuple(replace(e, scope=context.scope) for e in EXAMPLES)
        source = self.directory / 'b-media'
        shutil.copytree(DEMO_MEDIA_DIR, source)
        (source / 'editing-a.mp4').write_bytes((DEMO_MEDIA_DIR / 'editing-b.mp4').read_bytes())
        b_catalog = store.import_catalog(context, 'campaign-b', examples, source,
                                         operator=Operator('provisioner', frozenset({context.scope})), access=self.policy)
        old_assets = case.app.assets
        def assets(client, brand):
            return store.catalog(context.scope, b_catalog) if (client, brand) == ('tenant-b', 'brand') else old_assets(client, brand)
        case.app.assets = case.app.publications.assets = assets
        path = a['package']['groups'][0]['preview_path']
        self.assertEqual(case.buyer.get(path).content, (DEMO_MEDIA_DIR / 'editing-a.mp4').read_bytes())
        self.assertEqual(case.other.get(path).status_code, 409)
        b = case.other.get('/api/campaign/package', params={'revision': 1}).json()
        self.assertEqual(case.other.get(b['package']['groups'][0]['preview_path']).content, (DEMO_MEDIA_DIR / 'editing-b.mp4').read_bytes())
        for foreign in (BrandScope('tenant-a', 'brand'), BrandScope('tenant-a', 'brand2')):
            with self.assertRaises(AssetUnavailable):
                store.catalog(foreign, b_catalog)
        self.assertEqual(case.public.get(path).status_code, 404)
        case.post(case.reviewer, '/api/campaign/approve', args)
        public = next(link['path'] for link in case.post(case.reviewer, '/api/campaign/export', args)['public_comparisons']
                      if link['creative_ref'] == 'editing-voiceover-v1')
        token = public.split('attribution=')[1]
        self.assertEqual(case.public.get('/published/' + token + '/a').content, (DEMO_MEDIA_DIR / 'editing-a.mp4').read_bytes())

    def test_corrupt_or_symlinked_private_blob_returns_no_bytes(self):
        case = self.hosted()
        case.prepare()
        package = case.buyer.get('/api/campaign/package', params={'revision': 2}).json()['package']
        group = package['groups'][0]
        blob = case.path.with_suffix('.assets') / owner_key(BrandScope('tenant-a', 'brand')) / group['content']['preview_sha256']
        original = blob.read_bytes()
        secret = self.directory / 'secret'
        secret.write_bytes(b'private unrelated material')
        for replacement in ('symlink', 'corrupt', 'fifo'):
            with self.subTest(replacement=replacement):
                blob.unlink()
                if replacement == 'symlink':
                    blob.symlink_to(secret)
                elif replacement == 'fifo':
                    os.mkfifo(blob)
                else:
                    blob.write_bytes(b'corrupt')
                response = case.buyer.get(group['preview_path'])
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(secret.read_bytes(), response.content)
                blob.unlink()
                blob.write_bytes(original)

    def test_competing_native_revision_writes_preserve_the_winner_and_approval(self):
        runtime = AgentRuntime(self.path, media_dir=DEMO_MEDIA_DIR)
        runtime.resume(runtime.start(DEMO_REQUEST))
        fingerprint = runtime.drafts.review_package('tts-sample', 2)['fingerprint']
        runtime.drafts.approve_package('tts-sample', 2, fingerprint)
        approval = rows(self.path)['campaign_package_approvals']
        draft = runtime.drafts.read()
        writers = [AgentRuntime(self.path, media_dir=DEMO_MEDIA_DIR).drafts for _ in range(2)]
        barrier = Barrier(2)
        def save(index):
            barrier.wait(timeout=10)
            try:
                return 'saved', writers[index].save({'campaign_id': 'tts-sample', 'revision': 2,
                                                     'placements': [draft['placements'][index]]})
            except StaleDraft:
                return 'conflict', None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, range(2)))
        self.assertEqual(sorted(status for status, _ in results), ['conflict', 'saved'])
        winner = next(value for status, value in results if status == 'saved')
        self.assertEqual(runtime.drafts.read(), winner)
        self.assertEqual(winner['revision'], 3)
        self.assertEqual(rows(self.path)['campaign_package_approvals'], approval)
        self.assertIsNone(runtime.drafts.review_package('tts-sample', 3)['approval'])

    def test_backup_restore_preserves_two_clients_and_revokes_replayed_authority(self):
        case = self.hosted()
        args = case.prepare()
        case.post(case.reviewer, '/api/campaign/approve', args)
        publication = case.post(case.reviewer, '/api/campaign/export', args)['public_comparisons'][0]['path']
        setup = case.post(case.reviewer, '/api/campaign/setup/validate', args)
        case.post(case.reviewer, '/api/campaign/setup/create', {**args, 'setup_id': setup['id']})
        before = rows(case.path)
        backup = self.directory / 'backup'
        backup_store(case.path, case.path.with_suffix('.assets'), backup)
        self.assertEqual(rows(case.path), before)
        self.assertEqual(rows(backup / 'state.sqlite3')['staff_sessions'], [])
        restored = restore_store(backup, self.directory / 'restored')
        after = rows(restored['database'])
        for table, data in before.items():
            if table not in {'staff_sessions', 'public_comparisons'}:
                self.assertEqual(after[table], data, table)
        self.assertEqual(after['staff_sessions'], [])
        self.assertTrue(all(row[-1] == 0 for row in after['public_comparisons']))
        recovered = offline_fixture(restored['database'], asset_root=restored['assets'])
        with TestClient(recovered.staff, base_url=recovered.staff_origin) as staff, TestClient(recovered.viewer, base_url=recovered.viewer_origin) as viewer:
            self.assertEqual(staff.get('/api/campaign', headers={'Cookie': case.app.cookie+'='+case.buyer.cookies.get(case.app.cookie)}).status_code, 401)
            self.assertEqual(viewer.get(publication).status_code, 404)
            staff.post('/fixture', json={'profile': 'reviewer-a'}, headers={'Origin': recovered.staff_origin})
            review = staff.get('/api/campaign/package', params={'revision': 2}).json()
            self.assertEqual(review['fingerprint'], args['fingerprint'])
            self.assertEqual(review['approval']['actor_id'], 'gp-reviewer-a')
            staff.post('/fixture', json={'profile': 'buyer-b'}, headers={'Origin': recovered.staff_origin})
            self.assertEqual(staff.get('/api/campaign').json()['revision'], 1)
            self.assertEqual(staff.get('/api/agent/conversations').json(), [])

    def test_tampered_backup_and_existing_destinations_are_refused(self):
        case = self.hosted()
        backup = self.directory / 'backup'
        manifest = backup_store(case.path, case.path.with_suffix('.assets'), backup)
        self.assertEqual(verify_backup(backup), manifest)
        with self.assertRaises(FileExistsError):
            backup_store(case.path, case.path.with_suffix('.assets'), backup)
        occupied = self.directory / 'occupied'
        occupied.mkdir()
        (occupied / 'keep').write_text('existing state')
        with self.assertRaises(FileExistsError):
            restore_store(backup, occupied)
        self.assertEqual((occupied / 'keep').read_text(), 'existing state')
        for kind in ('blob', 'database'):
            corrupt = self.directory / ('bad-' + kind)
            shutil.copytree(backup, corrupt)
            if kind == 'blob':
                entry = manifest['blobs'][0]
                target = corrupt / 'blobs' / owner_key(BrandScope(entry['client_id'], entry['brand_id'])) / entry['digest']
            else:
                target = corrupt / 'state.sqlite3'
            target.write_bytes(b'changed')
            destination = self.directory / ('failed-' + kind)
            with self.assertRaises((ValueError, AssetUnavailable)):
                restore_store(corrupt, destination)
            self.assertFalse(destination.exists())

    def test_online_backup_uses_a_committed_snapshot_during_an_uncommitted_write(self):
        runtime = AgentRuntime(self.path, media_dir=DEMO_MEDIA_DIR)
        runtime.resume(runtime.start(DEMO_REQUEST))
        store = AssetStore(self.path, self.root)
        store.import_catalog(LOCAL_CONTEXT, 'tts-sample', EXAMPLES, DEMO_MEDIA_DIR, operator=LOCAL_OPERATOR, access=self.policy)
        ready, release = Event(), Event()
        def pending():
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                snapshot = {**runtime.drafts.read(), 'revision': 3}
                db.execute('INSERT INTO campaign_revisions VALUES(?,?,?)', ('tts-sample', 3, json.dumps(snapshot)))
                ready.set()
                if not release.wait(timeout=20):
                    raise RuntimeError('Writer was not released')
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(pending)
            self.assertTrue(ready.wait(timeout=10))
            try:
                backup = self.directory / 'backup'
                backup_store(self.path, self.root, backup)
                self.assertEqual(max(row[1] for row in rows(backup / 'state.sqlite3')['campaign_revisions']), 2)
            finally:
                release.set()
            future.result(timeout=10)
        self.assertEqual(runtime.drafts.read()['revision'], 3)
