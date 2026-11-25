"""The explicit local startup retains native constructor and adoption behavior."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from campaign_agent.access import LOCAL_CONTEXT
from campaign_agent.adapters.sqlite_planner_startup import initialize_local_planner
from campaign_agent.bootstrap.runtime import create_runtime as AgentRuntime
from campaign_agent.bootstrap.runtime import DEMO_MEDIA_DIR
from campaign_agent.bootstrap.local import create_local_planner
from campaign_agent.handoff import read_media
from campaign_agent.application.campaigns import BRIEF, POLICY
from campaign_agent.creatives import EXAMPLES
from campaign_agent.migrations import migrate
from campaign_agent.adapters.sqlite_workspace_admission import _bind


class PlannerStartupTests(unittest.TestCase):
    def test_selected_local_planner_rejects_mismatched_override_before_store_initialization(self):
        for example in EXAMPLES:
            with self.subTest(context=example.ref):
                media = self.root / example.ref
                shutil.copytree(DEMO_MEDIA_DIR, media)
                (media / example.takes[0][2]).write_bytes(b'previous passage recording')
                path = self.root / (example.ref + '.sqlite')
                with patch('campaign_agent.bootstrap.local.MEDIA_DIR', media):
                    with self.assertRaisesRegex(ValueError, 'Local comparison media'):
                        create_local_planner(path)
                self.assertFalse(path.exists())

    def test_selected_planner_reuses_bound_media_and_rejects_later_file_changes(self):
        media = self.root / 'media'
        shutil.copytree(DEMO_MEDIA_DIR, media)
        path = self.root / 'planner.sqlite'
        with patch('campaign_agent.bootstrap.local.MEDIA_DIR', media):
            runtime = create_local_planner(path)
        # HTTP re-composition may reuse the already verified source for the
        # selected placement graph as well as the retained commands.
        reopened = create_local_planner(path, media_dir=runtime.drafts.media_dir)
        for example in EXAMPLES:
            name = example.takes[0][2]
            self.assertEqual(read_media(reopened.drafts.media_dir, name), (DEMO_MEDIA_DIR / name).read_bytes())
            (media / name).write_bytes(b'replaced after startup')
            with self.assertRaises(FileNotFoundError):
                read_media(reopened.drafts.media_dir, name)
        package = reopened.drafts.review_package('tts-sample', 1)
        self.assertIn('Prepare the preview and comparison media for Video editing.', package['blockers'])
        self.assertIn('Prepare the preview and comparison media for Audiobook production.', package['blockers'])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.seed = json.dumps({'campaign_id': 'tts-sample', 'revision': 1,
                                'brief': BRIEF, 'policy': POLICY, 'placements': []})

    def explicit(self, path, authorize=lambda _capability: None):
        return initialize_local_planner(path, context=LOCAL_CONTEXT, campaign_id='tts-sample',
                                        seed_snapshot=self.seed, examples=EXAMPLES, authorize=authorize)

    def snapshot(self, path):
        with closing(sqlite3.connect(path)) as db:
            schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
            rows = {}
            for _, name, _, _ in (entry for entry in schema if entry[0] == 'table'):
                rows[name] = db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
            # The journal timestamps and transcript timestamps are wall-clock fields.
            rows['product_schema_migrations'] = [row[:3] for row in rows['product_schema_migrations']]
            rows['planner_messages'] = [row[:-1] for row in rows['planner_messages']]
            return schema, rows

    def test_fresh_and_reopen_match_all_legacy_schema_and_rows(self):
        legacy, explicit = self.root / 'legacy.db', self.root / 'explicit.db'
        AgentRuntime(legacy)
        calls = []
        self.assertEqual(self.explicit(explicit, calls.append), 'tts-sample')
        self.assertEqual(calls, ['youtube:campaign.read', 'youtube:campaign.draft'])
        self.assertEqual(self.snapshot(legacy), self.snapshot(explicit))
        before = self.snapshot(explicit)
        calls.clear()
        self.explicit(explicit, calls.append)
        self.assertEqual(calls, ['youtube:campaign.read'])
        self.assertEqual(self.snapshot(explicit), before)

    def test_denied_seed_rolls_back_admission_and_journal(self):
        path = self.root / 'denied.db'
        def authorize(capability):
            if capability == 'youtube:campaign.draft':
                raise PermissionError('Authored denial')
        with self.assertRaisesRegex(PermissionError, 'Authored denial'):
            self.explicit(path, authorize)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])

    def test_legacy_viewer_attribution_obeys_sibling_ambiguity(self):
        for sibling in (False, True):
            with self.subTest(sibling=sibling):
                source = self.root / f'viewer-{sibling}.db'
                with closing(sqlite3.connect(source)) as db, db:
                    db.execute('BEGIN IMMEDIATE')
                    migrate(db)
                    _bind(db, LOCAL_CONTEXT, 'tts-sample')
                    if sibling:
                        _bind(db, LOCAL_CONTEXT, 'sibling')
                    db.execute('CREATE TABLE viewer_visits (id TEXT PRIMARY KEY, client_id TEXT NOT NULL, '
                               'brand_id TEXT NOT NULL, creative_ref TEXT NOT NULL)')
                    db.execute('INSERT INTO viewer_visits VALUES(?,?,?,?)',
                               ('old-visit', 'local-client', 'tts-demo', 'editing-voiceover'))
                legacy, explicit = self.root / f'legacy-{sibling}.db', self.root / f'explicit-{sibling}.db'
                shutil.copyfile(source, legacy)
                shutil.copyfile(source, explicit)
                AgentRuntime(legacy)
                self.explicit(explicit)
                self.assertEqual(self.snapshot(legacy), self.snapshot(explicit))
                with closing(sqlite3.connect(explicit)) as db:
                    self.assertEqual(db.execute('SELECT campaign_id FROM viewer_visits').fetchone()[0],
                                     None if sibling else 'tts-sample')

    def test_legacy_transcript_is_adopted_once_without_changing_payload(self):
        source = self.root / 'source.db'
        AgentRuntime(source)
        snapshot = json.dumps({'request': 'Find placements', 'revision': 1, 'catalog_id': 'a' * 32})
        outcome = json.dumps({'revision': 2, 'message': 'Saved exactly.', 'ambiguous': []})
        with closing(sqlite3.connect(source)) as db, db:
            db.execute('DROP TABLE planner_messages')
            db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?)',
                       ('run', 'local-client', 'tts-demo', 'local-operator', 'Find placements', 'ready_for_review', 'tts-sample'))
            db.execute('INSERT INTO planner_jobs(run_id,session_id,snapshot,outcome) VALUES(?,?,?,?)',
                       ('run', 'session', snapshot, outcome))
        legacy, explicit = self.root / 'legacy-transcript.db', self.root / 'explicit-transcript.db'
        shutil.copyfile(source, legacy)
        shutil.copyfile(source, explicit)
        AgentRuntime(legacy)
        self.explicit(explicit)
        self.assertEqual(self.snapshot(legacy), self.snapshot(explicit))
        before = self.snapshot(explicit)
        self.explicit(explicit)
        self.assertEqual(self.snapshot(explicit), before)
        with closing(sqlite3.connect(explicit)) as db:
            self.assertEqual(db.execute('SELECT role,content,revision,catalog_id,kind FROM planner_messages ORDER BY id').fetchall(),
                             [('user', 'Find placements', 1, 'a' * 32, 'request'),
                              ('assistant', 'Saved exactly.', 2, 'a' * 32, 'ready_for_review')])


    def test_legacy_provenance_and_correction_identities_match(self):
        source = self.root / 'legacy-data.db'
        AgentRuntime(source)
        rows = [{'video_id': 'abcdefghijk', 'description': 'Authored title', 'source': 'synthetic',
                 'source_reference': 'Original catalog source'}]
        scope = {'client_id': 'local-client', 'brand_id': 'tts-demo'}
        identity = {'scope': scope, 'campaign': 'tts-sample', 'rows': rows}
        digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        reference = digest({**identity, 'video': 'abcdefghijk'})[:32]
        group = {'creative_version': 'editing-voiceover', 'comparison_version': 'editing-comparison-v1',
                 'content': {'preview_sha256': 'old-preview', 'instruction': 'old wording', 'title': 'fixture'}}
        package = {'groups': [group]}
        with closing(sqlite3.connect(source)) as db, db:
            db.execute('DROP TABLE placement_catalog_entries')
            db.execute('CREATE TABLE placement_catalog_entries (ref TEXT PRIMARY KEY, client_id TEXT NOT NULL, '
                       'brand_id TEXT NOT NULL, campaign_id TEXT NOT NULL, video_id TEXT NOT NULL, '
                       'title TEXT NOT NULL, source TEXT NOT NULL)')
            db.execute('INSERT INTO placement_catalog_entries VALUES(?,?,?,?,?,?,?)',
                       (reference, 'local-client', 'tts-demo', 'tts-sample', 'abcdefghijk', 'Authored title', 'synthetic'))
            db.execute('INSERT INTO placement_catalogs VALUES(?,?,?,?,?,?)',
                       ('catalog', 'local-client', 'tts-demo', 'tts-sample', 'Catalog', json.dumps(rows)))
            db.execute('DROP TABLE campaign_buyer_corrections')
            db.execute('CREATE TABLE campaign_buyer_corrections (sequence INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, '
                       'client_id TEXT NOT NULL, brand_id TEXT NOT NULL, campaign_id TEXT NOT NULL, '
                       'creative_version TEXT NOT NULL, comparison_fingerprint TEXT NOT NULL, '
                       'review_id TEXT NOT NULL, actor_id TEXT NOT NULL, kind TEXT NOT NULL, '
                       'note TEXT NOT NULL, created_at TEXT NOT NULL)')
            db.execute('INSERT INTO campaign_buyer_corrections VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (1, 'correction', 'local-client', 'tts-demo', 'tts-sample', 'editing-voiceover',
                        'old-fingerprint', 'review', 'operator', 'keep_takes', 'note', 'created'))
            db.execute('INSERT INTO campaign_performance_reviews VALUES(?,?,?,?,?,?,?,?,?)',
                       ('review', 'local-client', 'tts-demo', 'tts-sample', 1, 'fingerprint', 'created', 'created', '{}'))
            db.execute('INSERT INTO campaign_package_approvals VALUES(?,?,?,?,?,?,?,?)',
                       ('local-client', 'tts-demo', 'tts-sample', 1, 'fingerprint', 'operator', 'created', json.dumps(package)))
        legacy, explicit = self.root / 'legacy-data-original.db', self.root / 'legacy-data-explicit.db'
        shutil.copyfile(source, legacy)
        shutil.copyfile(source, explicit)
        AgentRuntime(legacy)
        self.explicit(explicit)
        self.assertEqual(self.snapshot(legacy), self.snapshot(explicit))
        full = {'comparison_version': group['comparison_version'],
                'content': {'instruction': 'old wording', 'title': 'fixture'}}
        takes = {'comparison_version': group['comparison_version'], 'content': {'title': 'fixture'}}
        with closing(sqlite3.connect(explicit)) as db:
            self.assertEqual(db.execute('SELECT source_reference FROM placement_catalog_entries WHERE ref=?', (reference,)).fetchone(),
                             ('Original catalog source',))
            self.assertEqual(db.execute('SELECT comparison_identity,takes_identity,comparison_version '
                                        'FROM campaign_buyer_corrections').fetchone(),
                             (digest(full), digest(takes), 'editing-comparison-v1'))

    def test_legacy_approval_and_assignment_columns_preserve_rows(self):
        source = self.root / 'legacy-columns.db'
        AgentRuntime(source)
        with closing(sqlite3.connect(source)) as db, db:
            db.execute('DROP TABLE campaign_package_approvals')
            db.execute('CREATE TABLE campaign_package_approvals (client_id TEXT NOT NULL, brand_id TEXT NOT NULL, '
                       'campaign_id TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, '
                       'actor_id TEXT NOT NULL, approved_at TEXT NOT NULL, '
                       'PRIMARY KEY(client_id,brand_id,campaign_id,revision,fingerprint))')
            db.execute('INSERT INTO campaign_package_approvals VALUES(?,?,?,?,?,?,?)',
                       ('local-client', 'tts-demo', 'tts-sample', 1, 'old-fingerprint', 'operator', 'old-time'))
            db.execute('DROP TABLE instruction_test_assignments')
            db.execute("CREATE TABLE instruction_test_assignments (test_id TEXT NOT NULL REFERENCES instruction_tests(id), "
                       "participant_id TEXT NOT NULL, arm TEXT NOT NULL CHECK (arm IN ('original','revised')), "
                       "visit_id TEXT NOT NULL UNIQUE REFERENCES viewer_visits(id), PRIMARY KEY(test_id,participant_id))")
            db.execute('INSERT INTO viewer_visits(id,client_id,brand_id,creative_ref,campaign_id) VALUES(?,?,?,?,?)',
                       ('visit', 'local-client', 'tts-demo', 'editing-voiceover', 'tts-sample'))
            db.execute('INSERT INTO instruction_tests VALUES(?,?,?,?,?,?,?,?)',
                       ('test', 'local-client', 'tts-demo', 'tts-sample', 1, 'old-fingerprint', 'old-time', '{}'))
            db.execute('INSERT INTO instruction_test_assignments VALUES(?,?,?,?)', ('test', 'participant', 'original', 'visit'))
        legacy, explicit = self.root / 'legacy-columns-original.db', self.root / 'legacy-columns-explicit.db'
        shutil.copyfile(source, legacy)
        shutil.copyfile(source, explicit)
        AgentRuntime(legacy)
        self.explicit(explicit)
        self.assertEqual(self.snapshot(legacy), self.snapshot(explicit))
        with closing(sqlite3.connect(explicit)) as db:
            self.assertEqual(db.execute('SELECT actor_id,approved_at,snapshot FROM campaign_package_approvals').fetchone(),
                             ('operator', 'old-time', None))
            self.assertEqual(db.execute('SELECT test_id,participant_id,arm,visit_id,source FROM instruction_test_assignments').fetchone(),
                             ('test', 'participant', 'original', 'visit', None))

    def test_incompatible_legacy_ownership_schema_is_not_adopted(self):
        from campaign_agent.adapters.sqlite_schema import SchemaConflict
        path = self.root / 'wrong-owner.db'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE brand_workspaces(client_id TEXT NOT NULL, brand_id TEXT NOT NULL, '
                       'workspace_id TEXT PRIMARY KEY, installation_id TEXT NOT NULL)')
            db.execute('INSERT INTO brand_workspaces VALUES(?,?,?,?)', ('c', 'b', 'w', 'i'))
        with self.assertRaises(SchemaConflict):
            self.explicit(path)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT * FROM brand_workspaces').fetchall(), [('c', 'b', 'w', 'i')])
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall(),
                             [('brand_workspaces',)])

    def test_unknown_migration_history_is_rejected_without_changes(self):
        from campaign_agent.adapters.sqlite_schema import SchemaConflict
        path = self.root / 'unknown.db'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE product_schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, '
                       'checksum TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            db.execute('INSERT INTO product_schema_migrations(version,name,checksum) VALUES(1,?,?)', ('unknown', 'bad'))
        with self.assertRaises(SchemaConflict):
            self.explicit(path)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT version,name,checksum FROM product_schema_migrations').fetchall(),
                             [(1, 'unknown', 'bad')])
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall(),
                             [('product_schema_migrations',)])

if __name__ == '__main__':
    unittest.main()
