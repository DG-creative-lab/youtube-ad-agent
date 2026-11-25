"""Run the authored local planner command line."""
import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

from campaign_agent.application.campaigns import DEFAULT_DRAFT_PATH
from campaign_agent.bootstrap.local import create_local_planner as create_local_planner
from campaign_agent.bootstrap.runtime import DEMO_CATALOG, create_provider_sessions as _provider_sessions
from campaign_agent.ports.storage_errors import StorageError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the authored local placement workflow through its selected unit of work.')
    parser.add_argument('--store', type=Path, default=DEFAULT_DRAFT_PATH)
    parser.add_argument('--media-dir', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('demo')
    demo.add_argument('--catalog', type=Path, default=DEMO_CATALOG)
    demo.add_argument('--request', default='Find placements for the saved campaign.')
    demo.add_argument('--run-id')
    demo.add_argument('--session-id')
    status = sub.add_parser('status')
    status.add_argument('run_id')
    server = sub.add_parser('serve')
    server.add_argument('--port', type=int, default=4173)
    server.add_argument('--viewer-port', type=int, default=8000)
    resume = sub.add_parser('resume')
    resume.add_argument('run_id')
    args = parser.parse_args(argv)
    try:
        if args.command == 'serve':
            from scripts.placement_review import serve
            serve(args.port, False, args.store, viewer_port=args.viewer_port,
                  runtime_factory=create_local_planner, provider_sessions_factory=_provider_sessions,
                  media_dir=args.media_dir)
            return 0
        runtime = create_local_planner(args.store, media_dir=args.media_dir)
        if args.command == 'demo':
            catalog = runtime.planner.catalogs.register('Authored local catalogue', json.loads(args.catalog.read_text()))
            run = runtime.planner.start(args.request, 'simulated', args.session_id or uuid4().hex,
                                args.run_id or uuid4().hex, catalog, draft_permission='placements')
        else:
            run = args.run_id
        result = runtime.read(run) if args.command == 'status' else runtime.resume(run)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except StorageError as error:
        print(json.dumps({'error': str(error), 'code': error.kind}), file=sys.stderr)
        return 1
    except (PermissionError, ValueError, RuntimeError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
