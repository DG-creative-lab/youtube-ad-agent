"""Create and verify one paused Demand Gen setup in a Google Ads test account."""
import base64
import binascii
from hashlib import sha256
import re
from urllib.parse import urlsplit

from campaign_agent.campaign_setup import SetupProviderError
from campaign_agent.handoff import package_fingerprint

API_VERSION = 'v26'
TEST_BUDGET_MICROS = 10_000_000
VIDEO_ID = re.compile(r'[A-Za-z0-9_-]{11}')
RESOURCE_ID = re.compile(r'[1-9][0-9]{0,18}')
CHANNELS = {'youtubeInStream': True}
CHANNEL_FIELDS = ', '.join('ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.' + name
                           for name in ('discover', 'display', 'gmail', 'maps', 'youtube_in_feed',
                                        'youtube_in_stream', 'youtube_shorts'))
AD_FIELDS = ', '.join('ad_group_ad.ad.demand_gen_video_responsive_ad.' + name
                      for name in ('videos', 'logo_images', 'business_name', 'headlines', 'long_headlines', 'descriptions'))


def query_rows(post, account, query):
    payload, _ = post(account, 'googleAds:searchStream', {'query': query})
    if not isinstance(payload, list) or any(not isinstance(batch, dict) or 'error' in batch for batch in payload):
        raise SetupProviderError('Google Ads returned an incomplete read-back.')
    return [row for batch in payload for row in batch.get('results', [])]


def verify_test_account(query_rows, manager_id, account_id):
    query = 'SELECT customer.id, customer.test_account, customer.manager, customer.currency_code FROM customer'
    for account, manager in ((manager_id, True), (account_id, False)):
        rows = query_rows(account, query)
        customer = rows[0].get('customer', {}) if len(rows) == 1 else {}
        if (str(customer.get('id')) != account or customer.get('testAccount') is not True
                or customer.get('manager', False) is not manager):
            raise SetupProviderError('Google did not verify the configured test account.')
        if not manager and customer.get('currencyCode') != 'GBP':
            raise SetupProviderError('The Google Ads test client must use GBP.')
    rows = query_rows(manager_id,
                       'SELECT customer_client.id, customer_client.level, customer_client.test_account, '
                       'customer_client.manager FROM customer_client WHERE customer_client.id = ' + account_id)
    child = rows[0].get('customerClient', {}) if len(rows) == 1 else {}
    if (str(child.get('id')) != account_id or str(child.get('level')) != '1'
            or child.get('testAccount') is not True or child.get('manager', False) is not False):
        raise SetupProviderError('Google did not verify the test manager relationship.')


class GoogleAdsSandbox:
    name = 'google-ads-sandbox'
    local_validation = False

    def __init__(self, manager_id, account_id, creatives, logo, post):
        if not all(isinstance(value, str) and re.fullmatch(r'[0-9]{10}', value)
                   for value in (manager_id, account_id)) or manager_id == account_id:
            raise ValueError('Configure distinct Google Ads test manager and customer IDs.')
        if not logo.startswith(b'\x89PNG\r\n\x1a\n') or len(logo) > 512_000:
            raise ValueError('Use a PNG test logo of up to 512 KB.')
        self.manager_id, self.account_id = manager_id, account_id
        self.creatives, self.logo, self.post = creatives, logo, post

    def prepare(self, package, fingerprint):
        groups = []
        if len(package['groups']) != 2:
            raise ValueError('The sandbox requires exactly two approved creative groups.')
        for group in package['groups']:
            creative = self.creatives.get(group['creative_version'])
            if not isinstance(creative, dict) or set(creative) != {
                    'video_id', 'destination', 'headline', 'long_headline', 'description'}:
                raise ValueError('Supply a test video, destination and copy for each approved creative version.')
            limits = {'headline': 40, 'long_headline': 90, 'description': 90}
            if any(not isinstance(creative[key], str) or not 1 <= len(creative[key].strip()) <= limit
                   for key, limit in limits.items()):
                raise ValueError('Use short, nonempty test ad copy.')
            if not isinstance(creative['video_id'], str) or not VIDEO_ID.fullmatch(creative['video_id']):
                raise ValueError('Use a valid YouTube test creative ID.')
            url = creative['destination']
            if not isinstance(url, str) or not re.fullmatch(r'\S+', url):
                raise ValueError('Use a public HTTPS destination for each test ad.')
            destination = urlsplit(url)
            if (destination.scheme != 'https' or not destination.hostname
                    or not re.fullmatch(r'(?:[a-z0-9-]+\.)+[a-z]{2,63}', destination.hostname)
                    or destination.hostname.endswith(('.local', '.localhost', '.internal', '.invalid'))
                    or destination.username or destination.password or destination.fragment):
                raise ValueError('Use a public HTTPS destination for each test ad.')
            placements = group['placements']
            if (not 1 <= len(placements) <= 20
                    or any(p['source'] not in {'creator_supplied', 'licensed'} or not VIDEO_ID.fullmatch(p['demo_id'])
                           for p in placements)):
                raise ValueError('Use 1–20 registered, non-fictional video placements per test group.')
            groups.append({
                'context': group['context'], 'name': group['title'], 'status': 'ENABLED',
                'ad_status': 'ENABLED', 'channels': CHANNELS, 'optimized_targeting': False,
                'placements': sorted((p['demo_id'] for p in placements)),
                'business_name': 'Campaign Setup Sandbox', **creative,
            })
        if set(groups[0]['placements']) & set(groups[1]['placements']):
            raise ValueError('Use distinct placement lists for the two test ad groups.')
        logo_name = 'Campaign Sandbox Logo ' + sha256(self.logo).hexdigest()[:24]
        expected = {
            'account_id': self.account_id, 'status': 'PAUSED', 'campaign_type': 'DEMAND_GEN',
            'budget_micros': TEST_BUDGET_MICROS, 'shared_budget': False, 'currency': 'GBP',
            'logo_name': logo_name, 'groups': groups,
        }
        correlation = package_fingerprint({'package': fingerprint, 'expected': expected})[:24]
        expected['name'] = 'Campaign Agent Sandbox ' + correlation
        logo_data = base64.b64encode(self.logo).decode('ascii')
        return {'provider': self.name, 'account_id': self.account_id, 'manager_id': self.manager_id,
                'api_version': API_VERSION, 'action': 'create_paused', 'status': 'PAUSED',
                'budget_micros': TEST_BUDGET_MICROS, 'expected_readback': expected,
                'mutate_operations': self._operations(expected, logo_data)}

    def _operations(self, expected, logo_data):
        prefix = f'customers/{self.account_id}/'
        budget, campaign = prefix + 'campaignBudgets/-1', prefix + 'campaigns/-2'
        logo = prefix + 'assets/-3'
        operations = [
            {'campaignBudgetOperation': {'create': {
                'resourceName': budget, 'name': expected['name'] + ' budget',
                'amountMicros': str(TEST_BUDGET_MICROS), 'explicitlyShared': False, 'deliveryMethod': 'STANDARD',
            }}},
            {'campaignOperation': {'create': {
                'resourceName': campaign, 'name': expected['name'], 'campaignBudget': budget,
                'advertisingChannelType': 'DEMAND_GEN', 'status': 'PAUSED', 'targetSpend': {},
                'containsEuPoliticalAdvertising': 'DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING',
            }}},
            {'assetOperation': {'create': {
                'resourceName': logo, 'name': expected['logo_name'], 'type': 'IMAGE', 'imageAsset': {'data': logo_data},
            }}},
        ]
        for index, group in enumerate(expected['groups']):
            group_ref, video_ref = prefix + f'adGroups/{-4 - 2 * index}', prefix + f'assets/{-5 - 2 * index}'
            operations.extend([
                {'adGroupOperation': {'create': {
                    'resourceName': group_ref, 'campaign': campaign, 'name': group['name'],
                    'status': 'ENABLED', 'optimizedTargetingEnabled': False,
                    'demandGenAdGroupSettings': {'channelControls': {'selectedChannels': CHANNELS}},
                }}},
                {'assetOperation': {'create': {
                    'resourceName': video_ref, 'type': 'YOUTUBE_VIDEO',
                    'youtubeVideoAsset': {'youtubeVideoId': group['video_id']},
                }}},
                {'adGroupAdOperation': {'create': {
                    'adGroup': group_ref, 'status': 'ENABLED', 'ad': {
                        'name': group['name'] + ' sandbox ad', 'finalUrls': [group['destination']],
                        'demandGenVideoResponsiveAd': {
                            'businessName': {'text': group['business_name']}, 'videos': [{'asset': video_ref}],
                            'logoImages': [{'asset': logo}], 'headlines': [{'text': group['headline']}],
                            'longHeadlines': [{'text': group['long_headline']}],
                            'descriptions': [{'text': group['description']}],
                        },
                    },
                }}},
            ])
            operations.extend({'adGroupCriterionOperation': {'create': {
                'adGroup': group_ref, 'negative': False, 'status': 'ENABLED', 'youtubeVideo': {'videoId': target},
            }}} for target in group['placements'])
        return operations

    def _checked_operations(self, plan):
        if (plan['provider'], plan['account_id'], plan['manager_id'], plan['api_version'],
                plan['action'], plan['status'], plan['budget_micros']) != (
                self.name, self.account_id, self.manager_id, API_VERSION, 'create_paused', 'PAUSED', TEST_BUDGET_MICROS):
            raise SetupProviderError('This setup is outside the configured paused test account.')
        expected = plan['expected_readback']
        if (expected['account_id'] != self.account_id or expected['status'] != 'PAUSED'
                or not re.fullmatch(r'Campaign Agent Sandbox [0-9a-f]{24}', expected['name'])):
            raise SetupProviderError('The sandbox campaign identity or status is invalid.')
        operations = plan['mutate_operations']
        try:
            data = operations[2]['assetOperation']['create']['imageAsset']['data']
            logo_name = 'Campaign Sandbox Logo ' + sha256(base64.b64decode(data, validate=True)).hexdigest()[:24]
        except (IndexError, KeyError, TypeError, binascii.Error):
            raise SetupProviderError('The approved test logo is unavailable.') from None
        if logo_name != expected['logo_name'] or operations != self._operations(expected, data):
            raise SetupProviderError('The Google Ads request differs from the approved setup.')
        return operations

    def _query(self, account, query):
        return query_rows(self.post, account, query)

    def _verify_account(self):
        verify_test_account(self._query, self.manager_id, self.account_id)

    def validate(self, plan):
        operations = self._checked_operations(plan)
        self._verify_account()
        result, request_id = self.post(self.account_id, 'googleAds:mutate', {
            'validateOnly': True, 'partialFailure': False, 'mutateOperations': operations,
        })
        if not isinstance(result, dict) or any(result.get(field) for field in (
                'mutateOperationResponses', 'partialFailureError', 'error')):
            raise SetupProviderError('Google did not return a clean validation-only response.')
        return request_id

    def create_paused(self, operation_id, plan):
        operations = self._checked_operations(plan)
        self._verify_account()
        if self._campaign(plan['expected_readback']['name']):
            raise SetupProviderError('A campaign with this operation name already exists. Read it back.')
        result, request_id = self.post(self.account_id, 'googleAds:mutate', {
            'validateOnly': False, 'partialFailure': False, 'mutateOperations': operations,
        })
        try:
            responses = result['mutateOperationResponses']
            if len(responses) != len(operations) or result.get('partialFailureError'):
                raise ValueError
            reference = responses[1]['campaignResult']['resourceName']
            prefix = f'customers/{self.account_id}/campaigns/'
            if not reference.startswith(prefix) or not RESOURCE_ID.fullmatch(reference[len(prefix):]):
                raise ValueError
            return {'campaign_id': reference[len(prefix):], 'request_id': request_id}
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            raise SetupProviderError('The creation response did not identify the test campaign.') from None

    def _campaign(self, name):
        rows = self._query(self.account_id,
                           'SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type, '
                           'campaign_budget.amount_micros, campaign_budget.explicitly_shared, customer.currency_code '
                           f"FROM campaign WHERE campaign.name = '{name}'")
        if len(rows) > 1:
            raise SetupProviderError('More than one campaign matched this operation name.')
        return rows[0] if rows else None

    def readback(self, operation_id, plan):
        self._checked_operations(plan)
        self._verify_account()
        expected = plan['expected_readback']
        row = self._campaign(expected['name'])
        if row is None:
            return None
        try:
            return self._read_configuration(operation_id, expected, row)
        except (KeyError, TypeError, ValueError, IndexError):
            raise SetupProviderError('Google returned incomplete campaign, ad or placement data.') from None

    def _read_configuration(self, operation_id, expected, row):
        campaign = row['campaign']
        campaign_id = str(campaign['id'])
        if not RESOURCE_ID.fullmatch(campaign_id):
            raise ValueError
        condition = f" WHERE campaign.id = {campaign_id}"
        groups = self._query(self.account_id, 'SELECT ad_group.id, ad_group.name, ad_group.status, '
                             'ad_group.optimized_targeting_enabled, ' + CHANNEL_FIELDS +
                             ' FROM ad_group' + condition + " AND ad_group.status != 'REMOVED'")
        ads = self._query(self.account_id, 'SELECT ad_group.id, ad_group_ad.status, ad_group_ad.ad.id, '
                          'ad_group_ad.ad.final_urls, ' + AD_FIELDS +
                          ' FROM ad_group_ad' + condition + " AND ad_group_ad.status != 'REMOVED'")
        targets = self._query(self.account_id, 'SELECT ad_group.id, ad_group_criterion.type, ad_group_criterion.status, '
                              'ad_group_criterion.negative, ad_group_criterion.youtube_video.video_id '
                              'FROM ad_group_criterion' + condition + " AND ad_group_criterion.status != 'REMOVED'")
        configuration = {'account_id': self.account_id, 'name': campaign['name'], 'status': campaign['status'],
                         'campaign_type': campaign['advertisingChannelType'],
                         'budget_micros': int(row['campaignBudget']['amountMicros']),
                         'shared_budget': row['campaignBudget'].get('explicitlyShared', False),
                         'currency': row['customer']['currencyCode'], 'groups': []}
        references, asset_names = {}, set()
        for ad_row in ads:
            ad = ad_row['adGroupAd']['ad']['demandGenVideoResponsiveAd']
            asset_names.update(link['asset'] for field in ('videos', 'logoImages') for link in ad[field])
        prefix = f'customers/{self.account_id}/assets/'
        if any(not name.startswith(prefix) or not RESOURCE_ID.fullmatch(name[len(prefix):]) for name in asset_names):
            raise ValueError
        assets = {}
        if asset_names:
            values = ', '.join("'" + name + "'" for name in sorted(asset_names))
            for asset_row in self._query(self.account_id, 'SELECT asset.resource_name, asset.name, asset.type, '
                                         'asset.youtube_video_asset.youtube_video_id '
                                         f'FROM asset WHERE asset.resource_name IN ({values})'):
                asset = asset_row['asset']
                assets[asset['resourceName']] = asset
        contexts = {group['name']: group['context'] for group in expected['groups']}
        logo_names = set()
        for group_row in groups:
            group = group_row['adGroup']
            group_id = str(group['id'])
            if not RESOURCE_ID.fullmatch(group_id) or group_id in references:
                raise ValueError
            name = group['name']
            context = contexts.get(name, 'unexpected-group')
            matching_ads = [entry['adGroupAd'] for entry in ads if str(entry['adGroup']['id']) == group_id]
            if len(matching_ads) != 1:
                # An empty or duplicate ad binding cannot be reconciled as a complete read.
                raise ValueError
            ad_row = matching_ads[0]
            ad = ad_row['ad']
            if not RESOURCE_ID.fullmatch(str(ad['id'])):
                raise ValueError
            responsive = ad['demandGenVideoResponsiveAd']
            selected = group['demandGenAdGroupSettings']['channelControls'].get('selectedChannels', {})
            positive = []
            for target in targets:
                if str(target['adGroup']['id']) != group_id:
                    continue
                criterion = target['adGroupCriterion']
                if (criterion['type'] == 'YOUTUBE_VIDEO' and criterion['status'] == 'ENABLED'
                        and not criterion.get('negative', False)):
                    positive.append(criterion['youtubeVideo']['videoId'])
                else:
                    positive.append('unexpected:' + criterion['type'])
            video_asset, = responsive['videos']
            logo_asset, = responsive['logoImages']
            video = assets[video_asset['asset']]
            logo = assets[logo_asset['asset']]
            if video['type'] != 'YOUTUBE_VIDEO' or logo['type'] != 'IMAGE':
                raise ValueError
            logo_names.add(logo['name'])
            destination, = ad['finalUrls']
            headline, = responsive['headlines']
            long_headline, = responsive['longHeadlines']
            description, = responsive['descriptions']
            configuration['groups'].append({
                'context': context, 'name': name, 'status': group['status'], 'ad_status': ad_row['status'],
                'channels': {key: value for key, value in selected.items() if value is True},
                'optimized_targeting': group.get('optimizedTargetingEnabled', False),
                'placements': sorted(positive), 'video_id': video['youtubeVideoAsset']['youtubeVideoId'],
                'destination': destination, 'business_name': responsive['businessName']['text'],
                'headline': headline['text'], 'long_headline': long_headline['text'], 'description': description['text'],
            })
            references[group_id] = {'context': context, 'ad_group_id': group_id, 'ad_id': str(ad['id'])}
        order = {group['context']: index for index, group in enumerate(expected['groups'])}
        def context_order(group):
            return order.get(group['context'], len(order))
        configuration['groups'].sort(key=context_order)
        configuration['logo_name'] = ', '.join(sorted(logo_names))
        return {'operation_id': operation_id, 'campaign_id': campaign_id, 'configuration': configuration,
                'groups': sorted(references.values(), key=context_order)}
