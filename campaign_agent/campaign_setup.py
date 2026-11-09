"""Validate, approve and verify creation of one paused setup per package."""
from contextlib import closing
from datetime import datetime, timezone
import json
import re
import sqlite3
from typing import Protocol

from .handoff import package_fingerprint
from scripts.campaign_drafts import PackageConflict


def _valid_resource_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'\S+', value) is not None


class SetupProviderError(RuntimeError):
    """The provider operation's outcome could not be established."""


class SetupProvider(Protocol):
    name: str
    account_id: str

    def validate(self, plan: dict) -> None: ...
    def create_paused(self, operation_id: str, plan: dict) -> dict: ...
    def readback(self, operation_id: str, account_id: str) -> dict | None: ...


class CampaignSetup:
    def __init__(self, drafts, provider: SetupProvider):
        self.drafts, self.provider = drafts, provider
        self.path = drafts.path
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS campaign_setups (
                client_id TEXT NOT NULL, brand_id TEXT NOT NULL, campaign_id TEXT NOT NULL,
                revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, snapshot TEXT NOT NULL,
                PRIMARY KEY (client_id, brand_id, campaign_id, revision, fingerprint)
            )''')

    def _key(self, campaign_id, revision, fingerprint):
        scope = self.drafts._package_scope(campaign_id, revision)
        if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
            raise ValueError('Choose a valid package fingerprint.')
        return *scope, revision, fingerprint

    @staticmethod
    def _read(db, key):
        row = db.execute('''SELECT snapshot FROM campaign_setups WHERE client_id=? AND brand_id=?
                           AND campaign_id=? AND revision=? AND fingerprint=?''', key).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _update(db, key, record):
        db.execute('''UPDATE campaign_setups SET snapshot=? WHERE client_id=? AND brand_id=?
                      AND campaign_id=? AND revision=? AND fingerprint=?''', (json.dumps(record), *key))

    def read(self, campaign_id, revision, fingerprint):
        key = self._key(campaign_id, revision, fingerprint)
        with closing(sqlite3.connect(self.path)) as db:
            return self._read(db, key)

    def validate(self, campaign_id, revision, fingerprint, *, connection=None):
        if connection is None:
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                return self.validate(campaign_id, revision, fingerprint, connection=db)
        key = self._key(campaign_id, revision, fingerprint)
        package = self.drafts.require_approved_package(connection, campaign_id, revision, fingerprint)['package']
        existing = self._read(connection, key)
        if existing is not None:
            return existing
        plan = {
            'provider': self.provider.name, 'account_id': self.provider.account_id,
            'action': 'create_paused', 'status': 'PAUSED', 'title': package['title'],
            'objective': package['proposed_setup']['objective'], 'budget_micros': 0,
            'schedule': package['proposed_setup']['schedule'],
            'groups': [{'context': group['context'], 'title': group['title'],
                        'creative_version': group['creative_version'], 'destination': group['viewer_path'],
                        'placement_ids': [placement['demo_id'] for placement in group['placements']]}
                       for group in package['groups']],
        }
        # This adapter validates locally. Remote preflight must run outside this transaction.
        self.provider.validate(plan)
        record = {'id': package_fingerprint({'scope': key, 'plan': plan}), 'revision': revision,
                  'fingerprint': fingerprint, 'plan': plan, 'status': 'validated',
                  'approval': None, 'receipt': None, 'readback': None}
        connection.execute('INSERT INTO campaign_setups VALUES (?, ?, ?, ?, ?, ?)', (*key, json.dumps(record)))
        return record

    def _require_setup(self, db, key, setup_id):
        record = self._read(db, key)
        if (record is None or record['id'] != setup_id
                or package_fingerprint({'scope': key, 'plan': record['plan']}) != setup_id):
            raise PackageConflict('Validate and review this exact setup first.')
        plan = record['plan']
        if (plan['provider'], plan['account_id'], plan['action'], plan['status'], plan['budget_micros']) != (
                self.provider.name, self.provider.account_id, 'create_paused', 'PAUSED', 0):
            raise PackageConflict('The approved setup is unavailable for this provider and account.')
        return record

    def create(self, campaign_id, revision, fingerprint, setup_id):
        key = self._key(campaign_id, revision, fingerprint)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            record = self._require_setup(db, key, setup_id)
            if record['status'] != 'validated':
                return record
            self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)
            record['approval'] = {'actor_id': self.drafts.operator.id, 'approved_at': datetime.now(timezone.utc).isoformat()}
            record['status'] = 'creating'
            self._update(db, key, record)

        try:
            receipt = self.provider.create_paused(setup_id, record['plan'])
        except SetupProviderError:
            return self._save_receipt(key, setup_id, None)
        self._save_receipt(key, setup_id, receipt)
        return self.reconcile(campaign_id, revision, fingerprint, setup_id)

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
        key = self._key(campaign_id, revision, fingerprint)
        with closing(sqlite3.connect(self.path)) as db:
            record = self._require_setup(db, key, setup_id)
        if record['approval'] is None:
            raise PackageConflict('Approve creation before reading back a setup.')
        if record['status'] in {'verified', 'mismatch'}:
            return record
        try:
            observed = self.provider.readback(setup_id, record['plan']['account_id'])
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
            expected_contexts = [group['context'] for group in record['plan']['groups']]
            matches = (observed['configuration'] == record['plan']
                       and [group['context'] for group in observed_groups] == expected_contexts
                       and (receipt is None or observed_id == receipt['campaign_id']))
            record.update(status='verified' if matches else 'mismatch', readback=observed)
            self._update(db, key, record)
            return record
