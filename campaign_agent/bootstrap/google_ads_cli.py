#!/usr/bin/env python3
"""Validate, create or reconcile a paused Demand Gen setup in a Google Ads test account."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if not __package__:
    sys.path.insert(0, str(ROOT))

from campaign_agent.adapters.google_ads_sandbox import GoogleAdsSandbox, google_transport
from campaign_agent.bootstrap.runtime import create_drafts, create_setup
from campaign_agent.ports.campaign_effects import SetupProviderError
from campaign_agent.ports.storage_errors import StorageError
from campaign_agent.application.campaigns import DEFAULT_DRAFT_PATH

def main():
    parser = argparse.ArgumentParser(prog='google_ads_sandbox.py', description=__doc__)
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
        drafts = create_drafts(args.draft_db, live=False)
        with requests.Session() as session:
            session.trust_env = False
            provider = GoogleAdsSandbox(config['manager_id'], config['account_id'], config['creatives'], logo,
                                        google_transport(config, session, ROOT / '.local/google'), viewer_origin=config.get('viewer_origin'))
            setup = create_setup(drafts, provider)
            reference = drafts.campaign_id, args.revision, args.fingerprint
            if args.command == 'validate':
                result = setup.validate(*reference)
            elif args.command == 'create-paused':
                result = setup.create(*reference, args.setup_id)
            else:
                result = setup.reconcile(*reference, args.setup_id)
        print(json.dumps(result, indent=2))
        return 0 if result['status'] in {'validated', 'verified'} else 1
    except (ImportError, OSError, KeyError, TypeError, ValueError, SetupProviderError, StorageError) as error:
        print(f'Sandbox setup stopped: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
