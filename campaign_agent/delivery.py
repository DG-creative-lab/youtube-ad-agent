"""Bind Google Ads delivery snapshots to a current, verified campaign setup."""
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import json
import sqlite3
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from scripts.campaign_drafts import PackageConflict
from .access import LOCAL_BRAND
from .adapters import demo_delivery
from .campaign_setup import CampaignSetup
from .delivery_next_test import next_action, respect_correction
from .handoff import package_fingerprint
from .measurement import ViewerMeasurement


class CampaignReporting(Protocol):
    provider: str
    manager_id: str
    account_id: str

    def snapshot(self, binding: dict) -> dict: ...


def viewer_window(report):
    window = report['window']
    if not window or not window.get('time_zone'):
        return None
    try:
        zone = ZoneInfo(window['time_zone'])
        start = datetime.combine(date.fromisoformat(window['start']), time.min, zone)
        end = datetime.combine(date.fromisoformat(window['end']) + timedelta(days=1), time.min, zone)
        captured = datetime.fromisoformat(report['captured_at'])
        if not start < end <= captured:
            return None
    except (ValueError, KeyError, TypeError, ZoneInfoNotFoundError, OverflowError):
        return None
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


class CampaignDelivery:
    def __init__(self, drafts, simulated_setup, performance, reporting: CampaignReporting | None = None, *, demo_scenario=None):
        if demo_scenario is not None and (demo_scenario not in demo_delivery.SCENARIOS or reporting is not None):
            raise ValueError('Choose a portable demo scenario without live reporting.')
        self.drafts, self.simulated_setup = drafts, simulated_setup
        self.performance, self.reporting, self.demo_scenario = performance, reporting, demo_scenario
        with closing(sqlite3.connect(drafts.path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS campaign_delivery_reports (
                id TEXT PRIMARY KEY, setup_id TEXT NOT NULL, snapshot TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS campaign_delivery_recommendations (
                id TEXT PRIMARY KEY, report_id TEXT NOT NULL, snapshot TEXT NOT NULL)''')

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
            **({'demo_scenario': self.demo_scenario} if self.demo_scenario else {}),
        }

    def read(self, campaign_id, revision, fingerprint):
        enabled = self.reporting is not None
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute('BEGIN')
            binding = self.binding(db, campaign_id, revision, fingerprint)
            if binding is None:
                return {'enabled': enabled, 'available': False, 'report': None, 'recommendation': None, 'groups': []}
            report = self.saved_report(db, binding)
            recommendation = None
            if report:
                row = db.execute('SELECT snapshot FROM campaign_delivery_recommendations WHERE report_id=? '
                                 'ORDER BY rowid DESC LIMIT 1', (report['id'],)).fetchone()
                if row:
                    recommendation = json.loads(row[0])
                    if recommendation.get('creative_version'):
                        package = self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)['package']
                        current = self.performance.correction_for_comparison(db, package, recommendation['creative_version'])
                        recommendation['needs_refresh'] = current != recommendation.get('correction')
            return {'enabled': enabled, 'available': True, 'report': report, 'recommendation': recommendation,
                    **({'demo_scenario': self.demo_scenario} if self.demo_scenario else {}),
                    'groups': binding['groups']}

    @staticmethod
    def saved_report(db, binding):
        row = db.execute('''SELECT snapshot FROM campaign_delivery_reports WHERE setup_id=?
                         AND json_extract(snapshot, '$.binding.demo_scenario') IS ? ORDER BY rowid DESC LIMIT 1''',
                         (binding['setup_id'], binding.get('demo_scenario'))).fetchone()
        return json.loads(row[0]) if row else None

    def capture(self, campaign_id, revision, fingerprint, *, setup_id=None, demo_scenario=None):
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute('BEGIN')
            binding = self.binding(db, campaign_id, revision, fingerprint)
        if binding is None or (setup_id is not None and (binding['setup_id'] != setup_id
                                                        or binding.get('demo_scenario') != demo_scenario)):
            raise PackageConflict('Verify the Google Ads setup for this approved package before reviewing delivery.')
        if self.demo_scenario:
            report = demo_delivery.snapshot(binding, self.demo_scenario)
        elif self.reporting is not None:
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
        captured_groups = {group['ad_group_id']: group for group in report['groups']}
        window = None if self.demo_scenario else viewer_window(report)
        groups = []
        for group in binding['groups']:
            link = group['viewer_link']
            activity = ViewerMeasurement.ad_link_activity(db, LOCAL_BRAND, link) if link else None
            window_activity = ViewerMeasurement.ad_link_window_activity(db, LOCAL_BRAND, link, *window) if link and window else None
            captured = captured_groups.get(group['ad_group_id'], {})
            groups.append({**group, 'metrics': captured.get('metrics'),
                           'viewer_activity': activity, 'window_activity': window_activity,
                           **({'fixture_activity': captured['fixture_activity']} if self.demo_scenario else {})})
        report = {**report, 'revision': revision, 'fingerprint': fingerprint, 'groups': groups}
        report['id'] = package_fingerprint(report)
        db.execute('INSERT INTO campaign_delivery_reports VALUES (?,?,?) ON CONFLICT(id) DO NOTHING',
                   (report['id'], binding['setup_id'], json.dumps(report)))
        return report

    def recommend(self, campaign_id, revision, fingerprint, report_id, *, connection=None):
        if connection is None:
            with closing(sqlite3.connect(self.drafts.path)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                return self.recommend(campaign_id, revision, fingerprint, report_id, connection=db)
        db = connection
        binding = self.binding(db, campaign_id, revision, fingerprint)
        report = self.saved_report(db, binding) if binding else None
        if report is None or report['id'] != report_id:
            raise PackageConflict('Use the latest saved delivery review for the approved package.')
        proposal = next_action(report)
        if proposal.get('creative_version'):
            package = self.drafts.require_approved_package(db, campaign_id, revision, fingerprint)['package']
            correction = self.performance.correction_for_comparison(db, package, proposal['creative_version'])
            proposal = respect_correction(proposal, correction)
        record = {**proposal, 'report_id': report_id, 'window': report['window']}
        record['id'] = package_fingerprint(record)
        db.execute('INSERT INTO campaign_delivery_recommendations VALUES (?,?,?) ON CONFLICT(id) DO NOTHING',
                   (record['id'], report_id, json.dumps(record)))
        return record

    def review(self, campaign_id, revision, fingerprint):
        report = self.capture(campaign_id, revision, fingerprint)
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            return self.save(db, campaign_id, revision, fingerprint, report)


def _delivery_summary(report):
    if report.get('demo_scenario'):
        return ('Authored delivery fixture for the simulated setup. '
                + ('It shows ad-group delivery.' if report['has_delivery'] else 'It shows zero delivery.'))
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
            source = 'The fixture shows' if report.get('demo_scenario') else 'Google Ads reported'
            delivery = f"{source} {metrics['impressions']} impressions, {metrics['clicks']} clicks and £{spend:.2f} spend"
        lines.append(f"{group['name']}: {delivery}. Viewer link arrivals: {activity['arrivals']}. "
                     f"Comparison completions: {activity['completions']}.")
        fixture_activity = group.get('fixture_activity')
        if fixture_activity is not None:
            lines.append(f"Authored window arrivals: {fixture_activity['arrivals']}. "
                         f"Completions: {fixture_activity['completions']}.")
        window_activity = group.get('window_activity')
        if window_activity is not None:
            lines.append(f"Same-window eligible arrivals: {window_activity['arrivals']}. "
                         f"Completions: {window_activity['completions']}. "
                         f"Rehearsal arrivals: {window_activity['rehearsal_arrivals']}.")
    return ' '.join([summary, *lines])
