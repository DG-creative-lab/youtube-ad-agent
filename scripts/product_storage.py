#!/usr/bin/env python3
"""Operator-only offline migrations and private backup/restore; no network calls."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from campaign_agent.migrations import migrate_path, versions
from campaign_agent.recovery import backup_store, readonly, restore_store, verify_backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('migrate', 'status', 'backup'):
        sub = commands.add_parser(command)
        sub.add_argument('--db', type=Path, required=True)
        if command == 'backup':
            sub.add_argument('--assets', type=Path, required=True)
            sub.add_argument('--out', type=Path, required=True)
    sub = commands.add_parser('restore')
    sub.add_argument('--backup', type=Path, required=True)
    sub.add_argument('--out', type=Path, required=True)
    sub = commands.add_parser('verify')
    sub.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'migrate':
            result = {'schema_version': migrate_path(args.db)}
        elif args.command == 'status':
            with closing(readonly(args.db)) as db:
                result = {'schema_version': versions(db)}
        elif args.command == 'backup':
            result = backup_store(args.db, args.assets, args.out)
        elif args.command == 'restore':
            result = restore_store(args.backup, args.out)
        else:
            result = verify_backup(args.backup)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
