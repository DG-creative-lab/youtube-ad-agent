"""Compose the authored local placement graph and its native fallback."""
from contextvars import ContextVar
from pathlib import Path
import sqlite3
from time import time, monotonic

from campaign_agent.access import LOCAL_CONTEXT, LOCAL_OPERATOR, require_access
from campaign_agent.application.access import PlacementAccess, PlacementCommandState
from campaign_agent.application.campaigns import DEFAULT_DRAFT_PATH
from campaign_agent.application.planner_runtime import PlacementRuntime
from campaign_agent.agent.planning_models import SimulatedPlanner
from campaign_agent.bootstrap.runtime import DEMO_MEDIA_DIR, MEDIA_DIR, create_runtime, draft_seed
from campaign_agent.bootstrap.placement_router import PlacementRouter
from campaign_agent.creatives import EXAMPLES
from campaign_agent.placement_discovery import SimulatedClassifier
from campaign_agent.adapters.local_access import LocalDemoAccess
from campaign_agent.adapters.local_media import LocalMedia
from campaign_agent.adapters.local_placement_authority import LocalPlacementAuthority
from campaign_agent.adapters.sqlite_planner import SQLitePlacementStorage, SafePlannerReceipts, _storage_failure
from campaign_agent.adapters.sqlite_planner_startup import SQLiteLocalPlannerStartup
from campaign_agent.ports.planner_startup import LocalPlannerStartup
from campaign_agent.ports.storage_errors import StorageError
from campaign_agent.adapters.sqlite_schema import SchemaConflict


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
    try:
        if initialize:
            startup: LocalPlannerStartup = SQLiteLocalPlannerStartup(path)
            startup.initialize(context=context, campaign_id=campaign_id,
                                     seed_snapshot=draft_seed(campaign_id), examples=examples,
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
    runtime = create_runtime(path, operator=operator, media_dir=media_dir, examples=examples, context=context,
                           campaign_id=campaign_id, planner_simulator=simulator, placement_classifier=classifier,
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
