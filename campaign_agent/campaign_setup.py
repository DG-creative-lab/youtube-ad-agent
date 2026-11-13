"""Validate, approve and verify one paused setup per package and provider account."""
from contextlib import closing
from datetime import datetime, timezone
import json
import re
import sqlite3
from typing import Protocol
from urllib.parse import urlsplit

from .handoff import package_fingerprint
from scripts.campaign_drafts import PackageConflict


def _valid_resource_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'\S+', value) is not None


class SetupProviderError(RuntimeError):
    """The provider operation's outcome could not be established."""


class SetupProvider(Protocol):
    name: str
    account_id: str
    local_validation: bool

    def prepare(self, package: dict, fingerprint: str) -> dict: ...
    def validate(self, plan: dict) -> str | None: ...
    def create_paused(self, operation_id: str, plan: dict) -> dict: ...
    def readback(self, operation_id: str, plan: dict) -> dict | None: ...


class CampaignSetup:
    def __init__(self, drafts, provider: SetupProvider, *, viewer_links=None):
        self.drafts, self.provider = drafts, provider
        self.viewer_links = viewer_links
        self.path = drafts.path
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            columns = {row[1] for row in db.execute('PRAGMA table_info(campaign_setups)')}
            legacy = bool(columns) and 'provider' not in columns
            if legacy:
                db.execute('ALTER TABLE campaign_setups RENAME TO campaign_setups_legacy')
            db.execute('''CREATE TABLE IF NOT EXISTS campaign_setups (
                client_id TEXT NOT NULL, brand_id TEXT NOT NULL, campaign_id TEXT NOT NULL,
                revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                provider TEXT NOT NULL, account_id TEXT NOT NULL, snapshot TEXT NOT NULL,
                PRIMARY KEY (client_id, brand_id, campaign_id, revision, fingerprint, provider, account_id)
            )''')
            if legacy:
                db.execute('''INSERT INTO campaign_setups
                              SELECT client_id, brand_id, campaign_id, revision, fingerprint,
                                     json_extract(snapshot, '$.plan.provider'),
                                     json_extract(snapshot, '$.plan.account_id'), snapshot
                              FROM campaign_setups_legacy''')
                db.execute('DROP TABLE campaign_setups_legacy')

    def _key(self, campaign_id, revision, fingerprint):
        scope = self.drafts._package_scope(campaign_id, revision)
        if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
            raise ValueError('Choose a valid package fingerprint.')
        return *scope, revision, fingerprint, self.provider.name, self.provider.account_id

    @staticmethod
    def _read(db, key):
        row = db.execute('''SELECT snapshot FROM campaign_setups WHERE client_id=? AND brand_id=?
                           AND campaign_id=? AND revision=? AND fingerprint=?
                           AND provider=? AND account_id=?''', key).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _update(db, key, record):
        db.execute('''UPDATE campaign_setups SET snapshot=? WHERE client_id=? AND brand_id=?
                      AND campaign_id=? AND revision=? AND fingerprint=? AND provider=? AND account_id=?''',
                   (json.dumps(record), *key))

    def read(self, campaign_id, revision, fingerprint):
        key = self._key(campaign_id, revision, fingerprint)
        with closing(sqlite3.connect(self.path)) as db:
            return self._read(db, key)

    def validate(self, campaign_id, revision, fingerprint, *, connection=None):
        self.drafts.require("youtube:setup.manage")
        key = self._key(campaign_id, revision, fingerprint)
        if not self.provider.local_validation:
            if connection is not None:
                raise ValueError('Validate the Google Ads setup from the sandbox CLI.')
            with closing(sqlite3.connect(self.path)) as db:
                db.execute('BEGIN')
                record, plan, links = self._prepare(db, key)
            if record is not None:
                return record
            self.drafts.require("youtube:setup.manage")
            validation_id = self.provider.validate(plan)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)
                existing = self._read(db, key)
                if existing is not None:
                    existing = self._require_setup(db, key, existing['id'])
                    self._require_current_destinations(db, key, existing)
                    return existing
                return self._save_validated(db, key, plan, links, validation_id)
        if connection is None:
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                return self.validate(campaign_id, revision, fingerprint, connection=db)
        existing, plan, links = self._prepare(connection, key)
        if existing is not None:
            return existing
        self.provider.validate(plan)
        return self._save_validated(connection, key, plan, links)

    def _prepare(self, db, key):
        campaign_id, revision, fingerprint = key[2:5]
        package = self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)['package']
        existing = self._read(db, key)
        if existing is not None:
            existing = self._require_setup(db, key, existing['id'])
            self._require_current_destinations(db, key, existing)
            return existing, None, None
        links, groups = [], []
        for group in package['groups']:
            link = {'context': group['context'], 'creative_ref': group['creative_version'],
                    'comparison_ref': group['comparison_version'],
                    'content_fingerprint': package_fingerprint(group['content'])}
            link['id'] = package_fingerprint({'setup_scope': key, 'comparison': link})
            path = '/viewer?attribution=' + link['id']
            links.append({**link, 'path': path})
            groups.append({**group, 'viewer_path': path})
        if self.viewer_links is not None:
            links = self.viewer_links(package, fingerprint)
            by_context = {link['context']: link for link in links}
            groups = [{**group, 'viewer_path': by_context[group['context']]['path']} for group in package['groups']]
        plan = self.provider.prepare({**package, 'groups': groups}, fingerprint)
        return None, plan, self._used_viewer_links(plan, links)

    @staticmethod
    def _used_viewer_links(plan, links):
        destinations = {group['context']: group['destination']
                        for group in plan.get('expected_readback', plan)['groups']}
        used_links = []
        for link in links:
            destination = destinations[link['context']]
            url = urlsplit(destination)
            if f'{url.path}?{url.query}' == link['path'] and not url.fragment:
                used_links.append({**link, 'destination': destination})
        return used_links

    def _require_current_destinations(self, db, key, record):
        if self.viewer_links is None:
            return
        package = self.drafts.require_approved_package(db, *key[2:5])['package']
        links = self.viewer_links(package, key[4])
        if self._used_viewer_links(record['plan'], links) != record.get('viewer_links', []):
            raise PackageConflict('The saved public comparison destinations no longer match this package. '
                                  'Prepare and approve a new package revision before exporting and validating.')

    @staticmethod
    def _setup_id(key, plan):
        # The plan already binds the provider and account. Preserve IDs issued before the journal migration.
        return package_fingerprint({'scope': key[:5], 'plan': plan})

    def _save_validated(self, connection, key, plan, links, validation_id=None):
        self.drafts.require("youtube:setup.manage")
        revision, fingerprint = key[3:5]
        record = {'id': self._setup_id(key, plan), 'revision': revision,
                  'fingerprint': fingerprint, 'plan': plan, 'status': 'validated',
                  'approval': None, 'receipt': None, 'readback': None}
        if validation_id:
            record['validation_request_id'] = validation_id
        if links:
            record['viewer_links'] = links
        self._require_current_destinations(connection, key, record)
        connection.execute('INSERT INTO campaign_setups VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (*key, json.dumps(record)))
        return record

    @staticmethod
    def verified_viewer_link(db, scope, link_id, *, campaign_id="tts-sample"):
        row = db.execute('''SELECT link.value FROM campaign_setups AS setup,
                            json_each(setup.snapshot, '$.viewer_links') AS link
                            WHERE setup.client_id=? AND setup.brand_id=?
                            AND setup.campaign_id=?
                            AND json_extract(setup.snapshot, '$.status')='verified'
                            AND json_extract(link.value, '$.id')=?''',
                         (scope.client_id, scope.brand_id, campaign_id, link_id)).fetchone()
        return json.loads(row[0]) if row else None

    def _require_setup(self, db, key, setup_id):
        record = self._read(db, key)
        if (record is None or record['id'] != setup_id
                or self._setup_id(key, record['plan']) != setup_id):
            raise PackageConflict('Validate and review this exact setup first.')
        plan = record['plan']
        if (plan['provider'], plan['account_id'], plan['action'], plan['status']) != (
                self.provider.name, self.provider.account_id, 'create_paused', 'PAUSED'):
            raise PackageConflict('The approved setup is unavailable for this provider and account.')
        return record

    def create(self, campaign_id, revision, fingerprint, setup_id):
        self.drafts.require("youtube:setup.manage")
        key = self._key(campaign_id, revision, fingerprint)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            record = self._require_setup(db, key, setup_id)
            if record['status'] != 'validated':
                return record
            self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)
            self.drafts.require("youtube:setup.manage")
            self._require_current_destinations(db, key, record)
            record['approval'] = {'actor_id': self.drafts.operator.id, 'approved_at': datetime.now(timezone.utc).isoformat()}
            record['status'] = 'creating'
            self._update(db, key, record)

        try:
            self.drafts.require("youtube:setup.manage")
            # The journal reservation and a potentially slow access check are not
            # evidence that the exact saved destinations are still usable now.
            with closing(sqlite3.connect(self.path)) as db:
                db.execute('BEGIN')
                self._require_current_destinations(db, key, record)
        except Exception:
            # Only pre-dispatch checks ran: the provider call below has not started.
            self._release_undispatched(key, setup_id, record['approval'])
            raise
        try:
            receipt = self.provider.create_paused(setup_id, record['plan'])
        except SetupProviderError:
            return self._save_receipt(key, setup_id, None)
        self._save_receipt(key, setup_id, receipt)
        return self.reconcile(campaign_id, revision, fingerprint, setup_id)

    def _release_undispatched(self, key, setup_id, reservation):
        """Release only this known-unsent reservation, even if current access is unavailable."""
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            record = self._require_setup(db, key, setup_id)
            if (record['status'] == 'creating' and record['approval'] == reservation
                    and record['receipt'] is None and record['readback'] is None):
                record.update(status='validated', approval=None)
                self._update(db, key, record)

    def _save_receipt(self, key, setup_id, receipt):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            record = self._require_setup(db, key, setup_id)
            if record['status'] == 'creating':
                record.update(status='created' if receipt else 'unknown', receipt=receipt)
                self._update(db, key, record)
            elif receipt is not None and record['receipt'] is None and record['readback'] is not None:
                record['receipt'] = receipt
                if record['readback']['campaign_id'] != receipt['campaign_id']:
                    record['status'] = 'mismatch'
                self._update(db, key, record)
            return record

    def reconcile(self, campaign_id, revision, fingerprint, setup_id):
        self.drafts.require("youtube:setup.manage")
        key = self._key(campaign_id, revision, fingerprint)
        with closing(sqlite3.connect(self.path)) as db:
            record = self._require_setup(db, key, setup_id)
        if record['approval'] is None:
            raise PackageConflict('Approve creation before reading back a setup.')
        if record['status'] in {'verified', 'mismatch'}:
            return record
        try:
            self.drafts.require("youtube:setup.manage")
            observed = self.provider.readback(setup_id, record['plan'])
        except SetupProviderError:
            return record
        if (observed is None or observed['operation_id'] != setup_id
                or observed['configuration']['account_id'] != record['plan']['account_id']):
            return record
        observed_id = observed.get('campaign_id')
        observed_groups = observed['groups']
        if not _valid_resource_id(observed_id) or not all(
                _valid_resource_id(group.get(field))
                for group in observed_groups for field in ('ad_group_id', 'ad_id')):
            return record
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            record = self._require_setup(db, key, setup_id)
            if record['status'] in {'verified', 'mismatch'}:
                return record
            receipt = record['receipt']
            expected = record['plan'].get('expected_readback', record['plan'])
            expected_contexts = [group['context'] for group in expected['groups']]
            matches = (observed['configuration'] == expected
                       and [group['context'] for group in observed_groups] == expected_contexts
                       and (receipt is None or observed_id == receipt['campaign_id']))
            record.update(status='verified' if matches else 'mismatch', readback=observed)
            self._update(db, key, record)
            return record
