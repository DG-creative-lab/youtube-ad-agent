"""Zero-cost native placement composition and CLI.

Run: python -m campaign_agent.bootstrap.planner --store PATH --media-dir PATH demo
The existing planner UI is available through the serve subcommand.
"""
import argparse
from contextvars import ContextVar
import json
from pathlib import Path
import sqlite3
import sys
from time import time, monotonic
from uuid import uuid4

from campaign_agent.access import LOCAL_CONTEXT, LOCAL_OPERATOR
from campaign_agent.application.access import PlacementAccess, PlacementCommandState
from campaign_agent.application.campaigns import BRIEF, POLICY, DEFAULT_DRAFT_PATH
from campaign_agent.application.planner_runtime import PlacementRuntime
from campaign_agent.agent.planning_models import SimulatedPlanner
from campaign_agent.agent.run import AgentRuntime
from campaign_agent.access import require_access
from campaign_agent.bootstrap.placement_router import PlacementRouter
from campaign_agent.creatives import EXAMPLES
from campaign_agent.handoff import MEDIA_DIR, DEMO_MEDIA_DIR
from campaign_agent.placement_discovery import SimulatedClassifier
from campaign_agent.adapters.local_access import LocalDemoAccess
from campaign_agent.adapters.local_media import LocalMedia
from campaign_agent.adapters.simulated_setup import SimulatedCampaignSetup
from campaign_agent.adapters.local_placement_authority import LocalPlacementAuthority
from campaign_agent.adapters.sqlite_planner import SQLitePlacementStorage, SafePlannerReceipts, _storage_failure
from campaign_agent.adapters.sqlite_planner_startup import SQLiteLocalPlannerStartup
from campaign_agent.ports.planner_startup import LocalPlannerStartup
from campaign_agent.adapters.sqlite_schema import SchemaConflict
from campaign_agent.ports.storage_errors import StorageError
from campaign_agent.model_catalogue import CatalogueCache
from campaign_agent.provider_sessions import ProviderSessions


class _CommandScope:
    """Command-local application facts; never a database or driver handle."""
    def __init__(self):
        self._state = ContextVar('placement_command_state', default=None)

    def get(self):
        value = self._state.get()
        if value is None:
            value = PlacementCommandState()
            self._state.set(value)
        return value

    def set(self, state):
        self._state.set(state)


def _provider_sessions(path, **options):
    return ProviderSessions(path, cache=CatalogueCache(), **options)


def create_local_planner(path=DEFAULT_DRAFT_PATH, operator=LOCAL_OPERATOR, *, media_dir=None, examples=EXAMPLES,
                         context=LOCAL_CONTEXT, campaign_id=None, simulator=None, classifier=None,
                         authority=None, clock=time, monotonic_clock=monotonic,
                         initialize=True, **options):
    """Compose the existing runtime with its local placement commands on typed units."""
    if context != LOCAL_CONTEXT or operator != LOCAL_OPERATOR or options.get('access') is not None:
        raise PermissionError('This composition requires the explicit local demo identity.')
    campaign_id = campaign_id or 'tts-sample'
    if campaign_id not in {'tts-sample', 'tts-catalog'}:
        raise PermissionError('This composition supports the original authored demo campaigns only.')
    path = Path(path)
    examples = tuple(examples)
    media_dir = media_dir if media_dir is not None else (MEDIA_DIR if MEDIA_DIR.is_dir() else DEMO_MEDIA_DIR)
    if not isinstance(media_dir, (str, Path)):
        raise ValueError('The authored local planner requires a filesystem media directory.')
    authority = authority if authority is not None else LocalPlacementAuthority(path, clock=clock, monotonic_clock=monotonic_clock)
    seed = {'campaign_id': campaign_id, 'revision': 1, 'brief': BRIEF, 'policy': POLICY, 'placements': []}
    try:
        if initialize:
            startup: LocalPlannerStartup = SQLiteLocalPlannerStartup(path)
            startup.initialize(context=context, campaign_id=campaign_id,
                                     seed_snapshot=json.dumps(seed), examples=examples,
                                     authorize=lambda capability: require_access(operator, context, authority,
                                                                                capability, campaign_id))
    except sqlite3.Error as error:
        raise _storage_failure(error) from None
    except OSError:
        raise StorageError('invalid', 'The local placement store is unavailable.') from None
    except SchemaConflict:
        raise StorageError('invalid', 'Stored migration history requires explicit reconciliation.') from None
    simulator = simulator if simulator is not None else options.pop('planner_simulator', None)
    classifier = classifier if classifier is not None else options.pop('placement_classifier', None)
    simulator = simulator if simulator is not None else SimulatedPlanner()
    classifier = classifier if classifier is not None else SimulatedClassifier()
    options.pop('access', None)
    runtime = AgentRuntime(path, operator=operator, media_dir=media_dir, examples=examples, context=context,
                           campaign_id=campaign_id, planner_simulator=simulator, placement_classifier=classifier,
                           setup_provider=SimulatedCampaignSetup(path, initialize=False),
                           access=LocalDemoAccess(), initialize=False, **options)
    access = PlacementAccess(authority, context, operator.id, campaign_id,
                             clock=clock, monotonic_clock=monotonic_clock, command_scope=_CommandScope(),
                             local_validate=lambda: operator.require_brand(context.scope))
    placement = PlacementRuntime(context=context, operator=operator, campaign_id=campaign_id, access=access,
                                 storage=SQLitePlacementStorage(path), receipts=SafePlannerReceipts(path),
                                 media=LocalMedia(media_dir), examples=examples,
                                 simulator=simulator, classifier=classifier)
    original_access = runtime.drafts.access
    runtime.drafts._placement_commands = (placement.drafts, lambda: (
        runtime.foreground is None and runtime.drafts.access is original_access
        and runtime.operator == operator and runtime.drafts.context == context
        and runtime.drafts.campaign_id == campaign_id))
    runtime.planner = PlacementRouter(runtime.planner, placement, runtime)
    return runtime


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the authored local placement workflow through its selected unit of work.')
    parser.add_argument('--store', type=Path, default=DEFAULT_DRAFT_PATH)
    parser.add_argument('--media-dir', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('demo')
    demo.add_argument('--catalog', type=Path, default=Path(__file__).resolve().parents[2] / 'examples/placement-review/catalog.json')
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
        runtime = create_local_planner(args.store, media_dir=args.media_dir)
        if args.command == 'serve':
            from scripts.placement_review import serve
            serve(args.port, False, args.store, viewer_port=args.viewer_port,
                  runtime_factory=create_local_planner, provider_sessions_factory=_provider_sessions,
                  initialize=False, media_dir=args.media_dir)
            return 0
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
