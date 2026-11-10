#!/usr/bin/env python3
"""Validate, create or reconcile a paused Demand Gen setup in a Google Ads test account."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from campaign_agent.adapters.google_ads_sandbox import API_VERSION, GoogleAdsSandbox
from campaign_agent.campaign_setup import CampaignSetup, SetupProviderError
from scripts.campaign_drafts import CampaignDrafts, DEFAULT_DRAFT_PATH

ADS_SCOPE = 'https://www.googleapis.com/auth/adwords'


def google_transport(config, session, *, read_only=False):
    # The optional Google libraries are loaded only for this CLI.
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    import requests

    token = json.loads((ROOT / '.local/google/google-ads-token.json').read_text())
    client = json.loads((ROOT / '.local/google/oauth-client.json').read_text())['installed']
    if (set(token.get('scopes', [])) != {ADS_SCOPE} or token.get('client_id') != client['client_id']
            or token.get('token_uri') != 'https://oauth2.googleapis.com/token'):
        raise ValueError('Use the configured Google Ads OAuth client and Ads-only grant.')
    credentials = Credentials.from_authorized_user_info(token)
    if not credentials.valid:
        try:
            credentials.refresh(Request())
        except Exception:
            raise SetupProviderError('The Google Ads grant could not be refreshed.') from None
        if credentials.granted_scopes and set(credentials.granted_scopes) != {ADS_SCOPE}:
            raise SetupProviderError('The refreshed OAuth grant has unexpected scopes.')

    def post(account, endpoint, body):
        if ((endpoint == 'googleAds:mutate' and (read_only or account != config['account_id']))
                or (endpoint == 'googleAds:searchStream' and account not in {config['manager_id'], config['account_id']})
                or endpoint not in {'googleAds:mutate', 'googleAds:searchStream'}):
            raise SetupProviderError('The request is outside the configured Google Ads sandbox.')
        try:
            response = session.post(
                f'https://googleads.googleapis.com/{API_VERSION}/customers/{account}/{endpoint}',
                headers={'Authorization': 'Bearer ' + credentials.token, 'login-customer-id': config['manager_id']},
                json=body, timeout=20, allow_redirects=False,
            )
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise SetupProviderError('The Google Ads request outcome could not be established.') from None
        if response.status_code != 200:
            # Return only bounded error codes and field names. Never print credentials or raw responses.
            errors = payload.get('error', {}).get('details', []) if isinstance(payload, dict) else []
            summary = [
                {'code': item.get('errorCode'), 'location': item.get('location')}
                for detail in errors for item in detail.get('errors', [])
            ]
            request_id = response.headers.get('request-id', 'unavailable')
            raise SetupProviderError(f'Google Ads rejected the request ({response.status_code}, {request_id}): {json.dumps(summary)}')
        return payload, response.headers.get('request-id')

    return post


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path, help='Private sandbox account and creative bindings JSON.')
    parser.add_argument('--draft-db', required=True, type=Path, help='Local database containing the approved test package.')
    parser.add_argument('--revision', required=True, type=int)
    parser.add_argument('--fingerprint', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('validate', help='Submit the full payload with validateOnly enabled.')
    for command, description in (
        ('create-paused', 'Approve the validated setup ID and create the paused test campaign.'),
        ('reconcile', 'Read back the same setup operation.'),
    ):
        action = commands.add_parser(command, help=description)
        action.add_argument('--setup-id', required=True)
    args = parser.parse_args()
    try:
        if args.draft_db.resolve() == DEFAULT_DRAFT_PATH.resolve() or not args.draft_db.is_file():
            raise ValueError('Choose an existing, separate sandbox database with an approved test package.')
        import requests
        config = json.loads(args.config.read_text())
        logo = (args.config.parent / config['logo_file']).read_bytes()
        drafts = CampaignDrafts(args.draft_db, live=False)
        with requests.Session() as session:
            session.trust_env = False
            provider = GoogleAdsSandbox(config['manager_id'], config['account_id'], config['creatives'], logo,
                                        google_transport(config, session), viewer_origin=config.get('viewer_origin'))
            setup = CampaignSetup(drafts, provider)
            reference = drafts.campaign_id, args.revision, args.fingerprint
            if args.command == 'validate':
                result = setup.validate(*reference)
            elif args.command == 'create-paused':
                result = setup.create(*reference, args.setup_id)
            else:
                result = setup.reconcile(*reference, args.setup_id)
        print(json.dumps(result, indent=2))
        return 0 if result['status'] in {'validated', 'verified'} else 1
    except (ImportError, OSError, KeyError, TypeError, ValueError, SetupProviderError) as error:
        print(f'Sandbox setup stopped: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
