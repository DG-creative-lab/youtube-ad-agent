"""Authored delivery and comparison counts for a verified simulated setup."""
from datetime import datetime, timedelta, timezone


SCENARIOS = ('wait', 'propose')


def snapshot(binding, scenario):
    now = datetime.now(timezone.utc)
    day = now.date()
    groups = []
    for group in binding['groups']:
        active = scenario == 'propose' and group['creative_version'] == 'editing-voiceover-v1'
        groups.append({
            'ad_group_id': group['ad_group_id'],
            'metrics': {'impressions': 120 if active else 0, 'clicks': 6 if active else 0, 'cost_micros': 0},
            'fixture_activity': {'arrivals': 4 if active else 0, 'completions': 1 if active else 0},
        })
    return {
        'source': 'Authored delivery fixture', 'demo_scenario': scenario,
        'window': {'start': str(day - timedelta(days=7)), 'end': str(day - timedelta(days=1)), 'time_zone': 'UTC'},
        'coverage': 'complete', 'placement_coverage': 'unavailable',
        'has_delivery': any(group['metrics']['impressions'] for group in groups),
        'placements': [], 'grain': 'Ad group', 'placement_grain': 'Ad group and video', 'currency': 'GBP',
        'captured_at': now.isoformat(), 'groups': groups,
    }
