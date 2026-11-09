"""Read scoped Demand Gen delivery from the Google Ads test account."""
from datetime import datetime, timedelta, timezone
from functools import partial
import re

from campaign_agent.campaign_setup import SetupProviderError
from .google_ads_sandbox import GoogleAdsSandbox, RESOURCE_ID, VIDEO_ID, query_rows, verify_test_account


PLACEMENT_LIMIT = 200
METRIC_FIELDS = ('impressions', 'clicks', 'cost_micros')
METRICS = ', '.join('metrics.' + field for field in METRIC_FIELDS)


def _metrics(row):
    values = row.get('metrics', {})
    result = {}
    for field in METRIC_FIELDS:
        # Google JSON omits default values on returned rows. A missing row is handled separately.
        value = values.get('costMicros' if field == 'cost_micros' else field, 0)
        if type(value) not in (int, str) or not re.fullmatch(r'[0-9]{1,19}', str(value)):
            raise ValueError('Invalid Google Ads metric.')
        result[field] = int(value)
    return result


class GoogleAdsReporting:
    provider = GoogleAdsSandbox.name

    def __init__(self, manager_id, account_id, connect):
        if (not all(isinstance(value, str) and re.fullmatch(r'[0-9]{10}', value)
                    for value in (manager_id, account_id)) or manager_id == account_id):
            raise ValueError('Configure distinct Google Ads test manager and customer IDs.')
        self.manager_id, self.account_id, self.connect = manager_id, account_id, connect

    def snapshot(self, binding):
        campaign_id = binding['campaign_id']
        ids = [group['ad_group_id'] for group in binding['groups']]
        if (binding['account_id'] != self.account_id or not ids
                or not all(RESOURCE_ID.fullmatch(value) for value in [campaign_id, *ids])):
            raise ValueError('Choose the verified Google Ads test campaign.')
        now = datetime.now(timezone.utc)
        start, end = (now.date() - timedelta(days=6)).isoformat(), now.date().isoformat()
        condition = (f' WHERE campaign.id = {campaign_id} AND ad_group.id IN ({", ".join(ids)})'
                     f" AND segments.date BETWEEN '{start}' AND '{end}'")
        totals, placements = {}, []
        coverage, placement_coverage = 'unavailable', 'unavailable'
        try:
            with self.connect() as post:
                query = partial(query_rows, post)
                verify_test_account(query, self.manager_id, self.account_id)
                search = partial(query, self.account_id)
                rows = search('SELECT campaign.id, ad_group.id, ' + METRICS + ' FROM ad_group' + condition)
                totals = self._totals(rows, campaign_id, ids)
                coverage = 'empty' if not totals else 'complete' if len(totals) == len(ids) else 'partial'
                rows = search('SELECT campaign.id, ad_group.id, detail_placement_view.placement, '
                              'detail_placement_view.placement_type, ' + METRICS
                              + ' FROM detail_placement_view' + condition + f' LIMIT {PLACEMENT_LIMIT + 1}')
                placements, placement_coverage = self._placements(rows, campaign_id, ids, totals, coverage)
        except (SetupProviderError, ValueError, KeyError, TypeError, AttributeError, ImportError, OSError):
            # Keep any independently verified totals when the placement view fails.
            pass
        has_delivery = any(any(metrics.values()) for metrics in totals.values()) or any(
            any(row['metrics'].values()) for row in placements)
        return {
            'source': 'Google Ads test account', 'grain': 'Ad group', 'placement_grain': 'Ad group and video',
            'window': {'start': start, 'end': end}, 'captured_at': now.isoformat(), 'currency': 'GBP',
            'coverage': coverage, 'placement_coverage': placement_coverage, 'has_delivery': has_delivery,
            'placements': placements,
            'groups': [{**group, 'metrics': totals.get(group['ad_group_id'])} for group in binding['groups']],
        }

    @staticmethod
    def _group_id(row, campaign_id, ids):
        group_id = str(row['adGroup']['id'])
        if str(row['campaign']['id']) != campaign_id or group_id not in ids:
            raise ValueError('A delivery row is outside the verified campaign.')
        return group_id

    def _totals(self, rows, campaign_id, ids):
        totals = {}
        for row in rows:
            group_id = self._group_id(row, campaign_id, ids)
            if group_id in totals:
                raise ValueError('Google returned duplicate ad-group totals.')
            totals[group_id] = _metrics(row)
        return totals

    def _placements(self, rows, campaign_id, ids, totals, coverage):
        if not rows:
            return [], 'empty'
        placements = []
        seen = set()
        reported = {group_id: dict.fromkeys(METRIC_FIELDS, 0) for group_id in ids}
        partial_coverage = coverage != 'complete' or len(rows) > PLACEMENT_LIMIT
        for row in rows[:PLACEMENT_LIMIT]:
            group_id = self._group_id(row, campaign_id, ids)
            detail = row['detailPlacementView']
            placement = detail.get('placement')
            if isinstance(placement, str) and placement.lower() == 'other':
                placement, kind = 'Other', 'other'
                partial_coverage = True
            elif detail.get('placementType') == 'YOUTUBE_VIDEO' and isinstance(placement, str) and VIDEO_ID.fullmatch(placement):
                kind = 'video'
            else:
                partial_coverage = True
                continue
            identity = (group_id, placement)
            if identity in seen:
                raise ValueError('Google returned duplicate placement rows.')
            seen.add(identity)
            metrics = _metrics(row)
            for field, value in metrics.items():
                reported[group_id][field] += value
            placements.append({'ad_group_id': group_id, 'placement': placement, 'kind': kind, 'metrics': metrics})
        partial_coverage |= any(reported[group_id] != total for group_id, total in totals.items())
        return placements, 'partial' if partial_coverage else 'complete'
