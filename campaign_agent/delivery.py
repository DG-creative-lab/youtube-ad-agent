"""Bind Google Ads delivery snapshots to a current, verified campaign setup."""
from contextlib import closing
import json
import sqlite3
from typing import Protocol

from scripts.campaign_drafts import PackageConflict
from .campaign_setup import CampaignSetup
from .handoff import package_fingerprint


class CampaignReporting(Protocol):
    provider: str
    manager_id: str
    account_id: str

    def snapshot(self, binding: dict) -> dict: ...


class CampaignDelivery:
    def __init__(self, drafts, reporting: CampaignReporting | None = None):
        self.drafts, self.reporting = drafts, reporting
        if reporting is not None:
            with closing(sqlite3.connect(drafts.path)) as db, db:
                db.execute('''CREATE TABLE IF NOT EXISTS campaign_delivery_reports (
                    id TEXT PRIMARY KEY, setup_id TEXT NOT NULL, snapshot TEXT NOT NULL)''')

    def binding(self, db, campaign_id, revision, fingerprint):
        if self.reporting is None:
            return None
        scope = self.drafts._package_scope(campaign_id, revision)
        package = self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)['package']
        key = (*scope, revision, fingerprint, self.reporting.provider, self.reporting.account_id)
        setup = CampaignSetup._read(db, key)
        if (not setup or setup['status'] != 'verified' or not setup['approval']
                or setup['plan'].get('manager_id') != self.reporting.manager_id):
            return None
        observed = setup['readback']
        configuration = observed['configuration']
        groups = {group['context']: group for group in configuration['groups']}
        creatives = {group['context']: group['creative_version'] for group in package['groups']}
        return {
            'setup_id': setup['id'], 'account_id': configuration['account_id'], 'campaign_id': observed['campaign_id'],
            'groups': [{'name': groups[row['context']]['name'], 'creative_version': creatives[row['context']],
                        'ad_group_id': row['ad_group_id'], 'configured_videos': groups[row['context']]['placements']}
                       for row in observed['groups']],
        }

    def read(self, campaign_id, revision, fingerprint):
        enabled = self.reporting is not None
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute('BEGIN')
            binding = self.binding(db, campaign_id, revision, fingerprint)
            if binding is None:
                return {'enabled': enabled, 'available': False, 'report': None}
            row = db.execute('SELECT snapshot FROM campaign_delivery_reports WHERE setup_id=? ORDER BY rowid DESC LIMIT 1',
                             (binding['setup_id'],)).fetchone()
            return {'enabled': enabled, 'available': True, 'report': json.loads(row[0]) if row else None}

    def capture(self, campaign_id, revision, fingerprint, *, setup_id=None):
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute('BEGIN')
            binding = self.binding(db, campaign_id, revision, fingerprint)
        if binding is None or (setup_id is not None and binding['setup_id'] != setup_id):
            raise PackageConflict('Verify the Google Ads setup for this approved package before reviewing delivery.')
        return {**self.reporting.snapshot(binding), 'binding': binding}

    def save(self, db, campaign_id, revision, fingerprint, report):
        binding = self.binding(db, campaign_id, revision, fingerprint)
        if binding is None or binding != report['binding']:
            raise PackageConflict('The Google Ads setup changed. Review delivery again from the current package.')
        report = {**report, 'revision': revision, 'fingerprint': fingerprint}
        report['id'] = package_fingerprint(report)
        db.execute('INSERT INTO campaign_delivery_reports VALUES (?,?,?) ON CONFLICT(id) DO NOTHING',
                   (report['id'], binding['setup_id'], json.dumps(report)))
        return report

    def review(self, campaign_id, revision, fingerprint):
        report = self.capture(campaign_id, revision, fingerprint)
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            return self.save(db, campaign_id, revision, fingerprint, report)


def delivery_message(report):
    if report['coverage'] == 'unavailable':
        return 'Google Ads delivery could not be read. Try reviewing again.'
    if report['coverage'] == 'empty' and not report['has_delivery']:
        return 'No delivery data is available for this test campaign. Wait for delivery evidence before proposing a change.'
    if report['coverage'] in {'partial', 'empty'}:
        return 'Ad-group delivery is incomplete. Review the available rows in Google Ads delivery.'
    if not report['has_delivery']:
        return 'Google Ads reports zero impressions, clicks and spend for both ad groups. Wait for delivery evidence before proposing a change.'
    return 'Google Ads returned ad-group delivery. Open Google Ads delivery to review the saved report.'
