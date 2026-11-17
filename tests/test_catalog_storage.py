"""Catalogue transaction and command conformance with authored data."""
from contextlib import contextmanager
import sqlite3
import unittest
from unittest.mock import patch

from campaign_agent.adapters.sqlite_planner import SQLiteCatalogStorage
from campaign_agent.placement_discovery import PlacementDiscovery
from campaign_agent.ports.catalogs import (
    CatalogEntry, CatalogRecord, CatalogScope, CatalogStorageError, CatalogUnitClosed,
)
import test_placement_planner as planner_fixtures


ROWS = [
    {'video_id': 'STORAGEX001', 'source': 'synthetic', 'description': 'Storage fixture one.'},
    {'video_id': 'STORAGEX002', 'source': 'synthetic', 'description': 'Storage fixture two.'},
]
EXPECTED_ID = '0700c27f25edc5e39d9d7ead25e0d97d'
EXPECTED_SNAPSHOT = ('[{"video_id": "STORAGEX001", "description": "Storage fixture one.", '
                     '"source": "synthetic", "source_reference": "Authored offline fixture"}, '
                     '{"video_id": "STORAGEX002", "description": "Storage fixture two.", '
                     '"source": "synthetic", "source_reference": "Authored offline fixture"}]')
SCOPE = CatalogScope('local-client', 'tts-demo', 'tts-sample')


class CatalogStorageTests(unittest.TestCase):
    def setUp(self):
        self.case = planner_fixtures.PlacementPlannerTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.commands = self.case.runtime.planner.catalogs
        self.storage = SQLiteCatalogStorage(self.case.path)

    def stored(self):
        with sqlite3.connect(self.case.path) as db:
            return (db.execute('SELECT id,label,snapshot FROM placement_catalogs WHERE id=?',
                               (EXPECTED_ID,)).fetchall(),
                    db.execute("SELECT video_id,source_reference FROM placement_catalog_entries "
                               "WHERE video_id LIKE 'STORAGEX%' ORDER BY video_id").fetchall())

    def test_existing_identity_raw_snapshot_and_first_label_survive_reopen(self):
        self.assertEqual(self.commands.register('  Storage fixture  ', ROWS), EXPECTED_ID)
        before = self.stored()
        self.assertEqual(before, ([(EXPECTED_ID, 'Storage fixture', EXPECTED_SNAPSHOT)],
                                 [('STORAGEX001', 'Authored offline fixture'),
                                  ('STORAGEX002', 'Authored offline fixture')]))
        reopened = self.case.reopen().planner.catalogs
        self.assertEqual(reopened.register('Changed label', ROWS), EXPECTED_ID)
        self.assertEqual(self.stored(), before)
        self.assertIn({'id': EXPECTED_ID, 'label': 'Storage fixture', 'count': 2}, reopened.list())

    def test_entry_failure_rolls_back_catalog_and_prior_entry(self):
        with sqlite3.connect(self.case.path) as db:
            db.execute('''CREATE TRIGGER reject_second_entry BEFORE INSERT ON placement_catalog_entries
                          WHEN NEW.video_id='STORAGEX002' BEGIN
                          SELECT RAISE(ABORT, 'authored private database failure'); END''')
        with self.assertRaises(CatalogStorageError) as caught:
            self.commands.register('Storage fixture', ROWS)
        self.assertEqual(str(caught.exception), 'Catalogue storage is unavailable.')
        self.assertEqual(self.stored(), ([], []))

    def test_commit_failure_rolls_back_both_tables_and_never_reports_success(self):
        connect = sqlite3.connect

        class FailedCommit(sqlite3.Connection):
            def commit(self):
                raise sqlite3.OperationalError('authored private commit failure')

        with patch('campaign_agent.adapters.sqlite_planner.sqlite3.connect',
                   side_effect=lambda path: connect(path, factory=FailedCommit)):
            with self.assertRaises(CatalogStorageError):
                self.commands.register('Storage fixture', ROWS)
        self.assertEqual(self.stored(), ([], []))
        self.assertEqual(self.commands.register('Storage fixture', ROWS), EXPECTED_ID)

    def test_units_roll_back_by_default_and_repositories_expire(self):
        record = CatalogRecord(EXPECTED_ID, SCOPE, 'Storage fixture', EXPECTED_SNAPSHOT)
        with self.storage.write() as unit:
            repo = unit.catalogs
            repo.add_catalog(record)
        self.assertEqual(self.stored(), ([], []))
        with self.assertRaises(CatalogUnitClosed):
            repo.list_catalogs(SCOPE)
        with self.storage.write() as committed:
            committed.catalogs.add_catalog(record)
            committed.commit()
            with self.assertRaises(CatalogUnitClosed):
                committed.catalogs.add_catalog(record)
        with self.storage.read() as reader:
            self.assertIn(record, reader.list_catalogs(SCOPE))
            for foreign in (CatalogScope('foreign', SCOPE.brand_id, SCOPE.campaign_id),
                            CatalogScope(SCOPE.client_id, 'foreign', SCOPE.campaign_id),
                            CatalogScope(SCOPE.client_id, SCOPE.brand_id, 'foreign')):
                self.assertEqual(reader.list_catalogs(foreign), ())
        with self.assertRaises(CatalogUnitClosed):
            reader.list_catalogs(SCOPE)

    def test_read_unit_keeps_its_snapshot_during_concurrent_commit(self):
        with sqlite3.connect(self.case.path) as db:
            db.execute('PRAGMA journal_mode=WAL')
        with self.storage.read() as reader:
            before = reader.list_catalogs(SCOPE)
            self.commands.register('Storage fixture', ROWS)
            self.assertEqual(reader.list_catalogs(SCOPE), before)
        with self.storage.read() as reader:
            self.assertIn(EXPECTED_ID, [record.id for record in reader.list_catalogs(SCOPE)])

    def test_permission_recheck_denies_before_opening_write_unit(self):
        require = self.commands.drafts.require
        checks = 0

        def revoked(capability):
            nonlocal checks
            require(capability)
            if capability == 'youtube:catalog.write':
                checks += 1
                if checks == 2:
                    raise PermissionError('Authored revocation')

        with patch.object(self.commands.drafts, 'require', side_effect=revoked), \
             patch.object(self.commands.catalog_storage, 'write', side_effect=AssertionError('Must not open write unit')):
            with self.assertRaisesRegex(PermissionError, 'Authored revocation'):
                self.commands.register('Storage fixture', ROWS)
        self.assertEqual(self.stored(), ([], []))

    def test_real_commands_accept_an_isolated_authored_store(self):
        class AuthoredStorage:
            def __init__(self):
                self.records, self.entries = {}, {}

            @contextmanager
            def write(self):
                records, entries = dict(self.records), dict(self.entries)
                owner = self

                class Unit:
                    def add_catalog(self, record: CatalogRecord):
                        records.setdefault(record.id, record)

                    def add_entry(self, entry: CatalogEntry):
                        entries.setdefault(entry.ref, entry)

                    def commit(self):
                        owner.records, owner.entries = records, entries

                unit = Unit()
                unit.catalogs = unit
                yield unit

            @contextmanager
            def read(self):
                yield self

            def list_catalogs(self, scope):
                return tuple(record for record in self.records.values() if record.scope == scope)

        storage = AuthoredStorage()
        isolated = PlacementDiscovery(self.commands.drafts, storage)
        with patch.object(self.commands.catalog_storage, 'write', side_effect=AssertionError('No native writes')), \
             patch.object(self.commands.catalog_storage, 'read', side_effect=AssertionError('No native reads')):
            self.assertEqual(isolated.register('Storage fixture', ROWS), EXPECTED_ID)
            self.assertEqual(isolated.list(), [{'id': EXPECTED_ID, 'label': 'Storage fixture', 'count': 2}])
        self.assertEqual(storage.records[EXPECTED_ID].snapshot, EXPECTED_SNAPSHOT)
        self.assertEqual({entry.video_id for entry in storage.entries.values()}, {'STORAGEX001', 'STORAGEX002'})
        self.assertEqual(self.stored(), ([], []))
