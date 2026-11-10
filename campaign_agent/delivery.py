"""Bind Google Ads delivery snapshots to a current, verified campaign setup."""
from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
from typing import Protocol

from scripts.campaign_drafts import PackageConflict
from .access import LOCAL_BRAND
from .campaign_setup import CampaignSetup
from .handoff import package_fingerprint
from .measurement import ViewerMeasurement


class CampaignReporting(Protocol):
    provider: str
    manager_id: str
    account_id: str

    def snapshot(self, binding: dict) -> dict: ...


class CampaignDelivery:
    def __init__(self, drafts, simulated_setup, reporting: CampaignReporting | None = None):
        self.drafts, self.simulated_setup, self.reporting = drafts, simulated_setup, reporting
        with closing(sqlite3.connect(drafts.path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS campaign_delivery_reports (
                id TEXT PRIMARY KEY, setup_id TEXT NOT NULL, snapshot TEXT NOT NULL)''')

    def binding(self, db, campaign_id, revision, fingerprint):
        scope = self.drafts._package_scope(campaign_id, revision)
        package = self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)['package']
        if self.reporting is None:
            key = self.simulated_setup._key(campaign_id, revision, fingerprint)
        else:
            key = (*scope, revision, fingerprint, self.reporting.provider, self.reporting.account_id)
        setup = CampaignSetup._read(db, key)
        if not setup or setup['status'] != 'verified' or not setup['approval']:
            return None
        links = {link['context']: link for link in setup.get('viewer_links', [])}
        if (self.reporting is None and not links) or (
                self.reporting is not None and setup['plan'].get('manager_id') != self.reporting.manager_id):
            return None
        observed = setup['readback']
        configuration = observed['configuration']
        groups = {group['context']: group for group in configuration['groups']}
        approved = {group['context']: group for group in package['groups']}
        bound_groups = []
        for row in observed['groups']:
            context = row['context']
            group, config = approved[context], groups[context]
            bound_groups.append({
                'name': group['title'], 'creative_version': group['creative_version'],
                'ad_group_id': row['ad_group_id'], 'ad_id': row['ad_id'],
                'configured_videos': config['placement_ids'] if self.reporting is None else config['placements'],
                'viewer_link': links.get(context),
            })
        return {
            'setup_id': setup['id'], 'account_id': configuration['account_id'], 'campaign_id': observed['campaign_id'],
            'groups': bound_groups,
        }

    def read(self, campaign_id, revision, fingerprint):
        enabled = self.reporting is not None
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute('BEGIN')
            binding = self.binding(db, campaign_id, revision, fingerprint)
            if binding is None:
                return {'enabled': enabled, 'available': False, 'report': None, 'groups': []}
            row = db.execute('SELECT snapshot FROM campaign_delivery_reports WHERE setup_id=? ORDER BY rowid DESC LIMIT 1',
                             (binding['setup_id'],)).fetchone()
            return {'enabled': enabled, 'available': True, 'report': json.loads(row[0]) if row else None,
                    'groups': binding['groups']}

    def capture(self, campaign_id, revision, fingerprint, *, setup_id=None):
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute('BEGIN')
            binding = self.binding(db, campaign_id, revision, fingerprint)
        if binding is None or (setup_id is not None and binding['setup_id'] != setup_id):
            raise PackageConflict('Verify the Google Ads setup for this approved package before reviewing delivery.')
        if self.reporting is not None:
            report = self.reporting.snapshot(binding)
        else:
            report = {'source': 'Offline rehearsal', 'window': None, 'coverage': 'unavailable',
                      'placement_coverage': 'unavailable', 'has_delivery': False, 'placements': [],
                      'grain': 'Ad group', 'placement_grain': 'Ad group and video', 'currency': None,
                      'captured_at': datetime.now(timezone.utc).isoformat(),
                      'groups': [{**group, 'metrics': None} for group in binding['groups']]}
        return {**report, 'binding': binding}

    def save(self, db, campaign_id, revision, fingerprint, report):
        binding = self.binding(db, campaign_id, revision, fingerprint)
        if binding is None or binding != report['binding']:
            raise PackageConflict('The Google Ads setup changed. Review delivery again from the current package.')
        metrics = {group['ad_group_id']: group['metrics'] for group in report['groups']}
        groups = []
        for group in binding['groups']:
            link = group['viewer_link']
            activity = ViewerMeasurement.ad_link_activity(db, LOCAL_BRAND, link) if link else None
            groups.append({**group, 'metrics': metrics.get(group['ad_group_id']), 'viewer_activity': activity})
        report = {**report, 'revision': revision, 'fingerprint': fingerprint, 'groups': groups}
        report['id'] = package_fingerprint(report)
        db.execute('INSERT INTO campaign_delivery_reports VALUES (?,?,?) ON CONFLICT(id) DO NOTHING',
                   (report['id'], binding['setup_id'], json.dumps(report)))
        return report

    def review(self, campaign_id, revision, fingerprint):
        report = self.capture(campaign_id, revision, fingerprint)
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            return self.save(db, campaign_id, revision, fingerprint, report)


def _delivery_summary(report):
    if report['window'] is None:
        return 'Offline rehearsal. Google Ads delivery is unavailable for the simulated setup.'
    if report['coverage'] == 'unavailable':
        return 'Google Ads delivery could not be read. Try reviewing again.'
    if report['coverage'] == 'empty' and not report['has_delivery']:
        return 'No delivery data is available for this test campaign. Wait for delivery evidence before proposing a change.'
    if report['coverage'] in {'partial', 'empty'}:
        return 'Ad-group delivery is incomplete. Review the available rows in Google Ads delivery.'
    if not report['has_delivery']:
        return 'Google Ads reports zero impressions, clicks and spend for both ad groups. Wait for delivery evidence before proposing a change.'
    return 'Google Ads returned ad-group delivery. Open Google Ads delivery to review the saved report.'


def delivery_message(report):
    summary = _delivery_summary(report)
    if not any(group.get('viewer_activity') is not None for group in report['groups']):
        return summary
    lines = ['Tagged viewer link activity includes all recorded visits, including rehearsals.']
    for group in report['groups']:
        activity = group['viewer_activity']
        if activity is None:
            lines.append(f"{group['name']}: tagged viewer activity unavailable.")
            continue
        metrics = group['metrics']
        delivery = 'Google Ads delivery unavailable'
        if metrics is not None:
            spend = metrics['cost_micros'] / 1_000_000
            delivery = f"Google Ads reported {metrics['impressions']} impressions, {metrics['clicks']} clicks and £{spend:.2f} spend"
        lines.append(f"{group['name']}: {delivery}. Viewer link arrivals: {activity['arrivals']}. "
                     f"Comparison completions: {activity['completions']}.")
    return ' '.join([summary, *lines])
