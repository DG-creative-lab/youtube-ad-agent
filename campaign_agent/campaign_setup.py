"""Validate, approve and verify one paused setup per package and provider account."""
from datetime import datetime, timezone
import json
import re
from urllib.parse import urlsplit

from .domain.fingerprints import package_fingerprint
from .ports.campaign_effects import SetupProvider as SetupProvider, SetupProviderError as SetupProviderError
from .ports.setup_delivery import SetupDeliveryReader, SetupDeliveryStorage, SetupDeliveryWriter, SetupKey
from campaign_agent.domain.errors import PackageConflict


def _valid_resource_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'\S+', value) is not None


class CampaignSetup:
    def __init__(self, drafts, provider: SetupProvider, storage: SetupDeliveryStorage, *, viewer_links=None):
        self.drafts, self.provider = drafts, provider
        self.storage, self.viewer_links = storage, viewer_links

    def _key(self, campaign_id, revision, fingerprint) -> SetupKey:
        scope = self.drafts._package_scope(campaign_id, revision)
        if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
            raise ValueError('Choose a valid package fingerprint.')
        return *scope, revision, fingerprint, self.provider.name, self.provider.account_id

    @staticmethod
    def read_from(records: SetupDeliveryReader, key: SetupKey):
        row = records.setup_snapshot_row(key)
        return json.loads(row[0]) if row is not None else None

    def read(self, campaign_id, revision, fingerprint):
        key = self._key(campaign_id, revision, fingerprint)
        with self.storage.read() as records:
            self.drafts._require_owner(records.drafts)
            return self.read_from(records, key)

    def validate(self, campaign_id, revision, fingerprint):
        self.drafts.require("youtube:setup.manage")
        key = self._key(campaign_id, revision, fingerprint)
        if self.provider.local_validation:
            with self.storage.write() as unit:
                record = self.validate_from(unit, campaign_id, revision, fingerprint)
                unit.commit()
                return record

        with self.storage.read() as records:
            record, plan, links = self._prepare(records, key)
        if record is not None:
            return record
        self.drafts.require("youtube:setup.manage")
        validation_id = self.provider.validate(plan)
        with self.storage.write() as unit:
            self.drafts.require_approved_from(unit.drafts, campaign_id, revision, fingerprint)
            existing = self.read_from(unit, key)
            if existing is not None:
                existing = self._require_setup(unit, key, existing['id'])
                self._require_current_destinations(unit, key, existing)
                return existing
            record = self._save_validated(unit, key, plan, links, validation_id)
            unit.commit()
            return record

    def validate_from(self, records: SetupDeliveryWriter, campaign_id, revision, fingerprint):
        self.drafts.require("youtube:setup.manage")
        key = self._key(campaign_id, revision, fingerprint)
        if not self.provider.local_validation:
            raise ValueError('Validate the Google Ads setup from the sandbox CLI.')
        existing, plan, links = self._prepare(records, key)
        if existing is not None:
            return existing
        self.provider.validate(plan)
        return self._save_validated(records, key, plan, links)

    def _prepare(self, records: SetupDeliveryReader, key: SetupKey):
        campaign_id, revision, fingerprint = key[2:5]
        package = self.drafts.require_approved_from(records.drafts, campaign_id, revision, fingerprint)['package']
        existing = self.read_from(records, key)
        if existing is not None:
            existing = self._require_setup(records, key, existing['id'])
            self._require_current_destinations(records, key, existing)
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
            links = self.viewer_links(package, records.publication_rows(key[:5]))
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

    def _require_current_destinations(self, records: SetupDeliveryReader, key: SetupKey, record):
        if self.viewer_links is None:
            return
        package = self.drafts.require_approved_from(records.drafts, *key[2:5])['package']
        links = self.viewer_links(package, records.publication_rows(key[:5]))
        if self._used_viewer_links(record['plan'], links) != record.get('viewer_links', []):
            raise PackageConflict('The saved public comparison destinations no longer match this package. '
                                  'Prepare and approve a new package revision before exporting and validating.')

    @staticmethod
    def _setup_id(key, plan):
        # The plan already binds the provider and account. Preserve IDs issued before the journal migration.
        return package_fingerprint({'scope': key[:5], 'plan': plan})

    def _save_validated(self, records: SetupDeliveryWriter, key: SetupKey, plan, links, validation_id=None):
        self.drafts.require("youtube:setup.manage")
        revision, fingerprint = key[3:5]
        record = {'id': self._setup_id(key, plan), 'revision': revision,
                  'fingerprint': fingerprint, 'plan': plan, 'status': 'validated',
                  'approval': None, 'receipt': None, 'readback': None}
        if validation_id:
            record['validation_request_id'] = validation_id
        if links:
            record['viewer_links'] = links
        self._require_current_destinations(records, key, record)
        records.add_setup(key, json.dumps(record))
        return record

    def _require_setup(self, records: SetupDeliveryReader, key: SetupKey, setup_id):
        self.drafts._require_owner(records.drafts)
        record = self.read_from(records, key)
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
        with self.storage.write() as records:
            record = self._require_setup(records, key, setup_id)
            if record['status'] != 'validated':
                return record
            self.drafts.require_approved_from(records.drafts, campaign_id, revision, fingerprint)
            self.drafts.require("youtube:setup.manage")
            self._require_current_destinations(records, key, record)
            record['approval'] = {'actor_id': self.drafts.operator.id, 'approved_at': datetime.now(timezone.utc).isoformat()}
            record['status'] = 'creating'
            records.update_setup(key, json.dumps(record))
            records.commit()

        try:
            self.drafts.require("youtube:setup.manage")
            # The journal reservation and a potentially slow access check are not
            # evidence that the exact saved destinations are still usable now.
            with self.storage.read() as records:
                self._require_current_destinations(records, key, record)
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
        with self.storage.write() as records:
            record = self._require_setup(records, key, setup_id)
            if (record['status'] == 'creating' and record['approval'] == reservation
                    and record['receipt'] is None and record['readback'] is None):
                record.update(status='validated', approval=None)
                records.update_setup(key, json.dumps(record))
                records.commit()

    def _save_receipt(self, key, setup_id, receipt):
        with self.storage.write() as records:
            record = self._require_setup(records, key, setup_id)
            if record['status'] == 'creating':
                record.update(status='created' if receipt else 'unknown', receipt=receipt)
                records.update_setup(key, json.dumps(record))
                records.commit()
            elif receipt is not None and record['receipt'] is None and record['readback'] is not None:
                record['receipt'] = receipt
                if record['readback']['campaign_id'] != receipt['campaign_id']:
                    record['status'] = 'mismatch'
                records.update_setup(key, json.dumps(record))
                records.commit()
            return record

    def reconcile(self, campaign_id, revision, fingerprint, setup_id):
        self.drafts.require("youtube:setup.manage")
        key = self._key(campaign_id, revision, fingerprint)
        with self.storage.read() as records:
            record = self._require_setup(records, key, setup_id)
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
        with self.storage.write() as records:
            record = self._require_setup(records, key, setup_id)
            if record['status'] in {'verified', 'mismatch'}:
                return record
            receipt = record['receipt']
            expected = record['plan'].get('expected_readback', record['plan'])
            expected_contexts = [group['context'] for group in expected['groups']]
            matches = (observed['configuration'] == expected
                       and [group['context'] for group in observed_groups] == expected_contexts
                       and (receipt is None or observed_id == receipt['campaign_id']))
            record.update(status='verified' if matches else 'mismatch', readback=observed)
            records.update_setup(key, json.dumps(record))
            records.commit()
            return record
