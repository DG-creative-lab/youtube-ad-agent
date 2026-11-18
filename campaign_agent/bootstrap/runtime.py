"""Explicit startup and dependency assembly for the native campaign runtime."""
from functools import partial
import json
from pathlib import Path
from time import time_ns
from uuid import uuid4

from campaign_agent.access import LOCAL_CONTEXT, LOCAL_OPERATOR
from campaign_agent.adapters import demo_delivery, sqlite_planner_startup as startup
from campaign_agent.adapters.catalogue_cache import CatalogueCache
from campaign_agent.adapters.local_access import LocalDemoAccess
from campaign_agent.adapters.openrouter_instructions import OpenRouterInstructions
from campaign_agent.adapters.openrouter_reviews import OpenRouterPlanner, OpenRouterReviews
from campaign_agent.adapters.simulated_setup import SimulatedCampaignSetup
from campaign_agent.adapters.sqlite_drafts import SQLiteDraftRepository, SQLiteDraftStorage
from campaign_agent.adapters.sqlite_planner import (
    SQLiteCatalogStorage, SQLiteConversationStorage, SQLitePlacementCommitStorage,
    SQLitePlannerLifecycleStorage, SQLitePlannerReadStorage,
)
from campaign_agent.adapters.sqlite_schema import migrate_path
from campaign_agent.adapters.sqlite_setup_delivery import SQLiteSetupDeliveryStorage
from campaign_agent.adapters.sqlite_viewer import SQLiteViewerStorage
from campaign_agent.agent.planner import PlacementAgent
from campaign_agent.agent.planning_models import SimulatedPlanner, planner_request_body
from campaign_agent.agent.run import AgentRuntime, RecordedInference
from campaign_agent.application.campaigns import BRIEF, POLICY, DEFAULT_DRAFT_PATH, CampaignDrafts
from campaign_agent.assets import AssetStore
from campaign_agent.bootstrap.evidence import create_experiments, create_performance as create_performance
from campaign_agent.campaign_setup import CampaignSetup
from campaign_agent.creatives import EXAMPLES
from campaign_agent.delivery import CampaignDelivery
from campaign_agent.learning import InstructionFindings
from campaign_agent.measurement import ViewerMeasurement
from campaign_agent.placement_discovery import PlacementDiscovery, SimulatedClassifier
from campaign_agent.provider_sessions import ProviderSessions
from campaign_agent.staff import StaffSessions

ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / '.local/viewer-media'
DEMO_MEDIA_DIR = ROOT / 'examples/viewer-media'
DEMO_CATALOG = ROOT / 'examples/placement-review/catalog.json'


def draft_seed(campaign_id):
    return json.dumps({'campaign_id': campaign_id, 'revision': 1, 'brief': BRIEF,
                       'policy': POLICY, 'placements': []})


class _NativeCampaignDrafts(CampaignDrafts):
    """Bridge retained workflows that own a native transaction with sibling writes."""

    _repository = staticmethod(SQLiteDraftRepository)

    def __init__(self, path, live, operator, **options):
        self.path = Path(path)
        super().__init__(live, operator, storage=SQLiteDraftStorage(self.path), new_id=lambda: uuid4().hex,
                         **options)

    def _read(self, db, revision=None):
        return self.read_from(self._repository(db), revision)

    def _package_review(self, db, campaign_id, revision):
        return self._review_from(self._repository(db), campaign_id, revision)

    def require_approved_package(self, db, campaign_id, revision, fingerprint):
        return self.require_approved_from(self._repository(db), campaign_id, revision, fingerprint)

    def write_unit(self):
        return self._storage.legacy_write()

    def save(self, payload, *, connection=None, repository=None):
        if connection is not None:
            if repository is not None:
                raise ValueError("Choose one draft transaction source.")
            repository = self._repository(connection)
        return super().save(payload, repository=repository)


def create_drafts(path, live, operator=LOCAL_OPERATOR, *, media_dir=None, context=LOCAL_CONTEXT,
                  campaign_id=None, access=None, examples=None, initialize=True):
    if media_dir is None:
        media_dir = MEDIA_DIR if MEDIA_DIR.is_dir() else DEMO_MEDIA_DIR
    drafts = _NativeCampaignDrafts(path, live, operator, context=context, media_dir=media_dir,
                                   campaign_id=campaign_id, examples=examples,
                                   access=LocalDemoAccess() if access is None else access)
    drafts.require('youtube:campaign.read')
    if initialize:
        startup.initialize_drafts(drafts.path, context=context, campaign_id=drafts.campaign_id,
                                  seed_snapshot=draft_seed(drafts.campaign_id), authorize=drafts.require, live=live)
    return drafts


class _NativeCampaignSetup(CampaignSetup):
    """Retain same-transaction validation inside the existing native agent turn."""

    def validate(self, campaign_id, revision, fingerprint, *, connection=None):
        if connection is None:
            return super().validate(campaign_id, revision, fingerprint)
        return self.validate_from(self.storage.borrow(connection), campaign_id, revision, fingerprint)


class _NativeCampaignDelivery(CampaignDelivery):
    """Use the planner's existing transaction for report and sibling turn writes."""

    def binding(self, db, campaign_id, revision, fingerprint):
        return self.binding_from(self.storage.borrow(db), campaign_id, revision, fingerprint)

    def saved_report(self, db, binding):
        return self.saved_report_from(self.storage.borrow(db), binding)

    def save(self, db, campaign_id, revision, fingerprint, report):
        return self.save_from(self.storage.borrow(db), campaign_id, revision, fingerprint, report)

    def recommend(self, campaign_id, revision, fingerprint, report_id, *, connection=None):
        if connection is None:
            return super().recommend(campaign_id, revision, fingerprint, report_id)
        return self.recommend_from(self.storage.borrow(connection), campaign_id, revision, fingerprint, report_id)


class _NativeViewerMeasurement(ViewerMeasurement):
    """Borrow the existing SQLite transaction for experiment and review siblings."""

    def __init__(self, path, examples, *, campaign_id):
        super().__init__(SQLiteViewerStorage(path), examples, campaign_id=campaign_id,
                         clock_ms=lambda: time_ns() // 1_000_000, new_visit_id=lambda: uuid4().hex)

    def connect(self):
        return self.storage.legacy_connect()

    def open_example(self, creative_ref, example_ref=None, visit_id=None, *, connection=None, **options):
        if connection is not None:
            return self.open_from(self.storage.borrow(connection), creative_ref, example_ref, visit_id, **options)
        return super().open_example(creative_ref, example_ref, visit_id, **options)

    def record(self, creative_ref, visit_id, example_ref, event_id, kind, take, *, connection=None):
        if connection is not None:
            return self.record_from(self.storage.borrow(connection), creative_ref, visit_id, example_ref,
                                    event_id, kind, take)
        return super().record(creative_ref, visit_id, example_ref, event_id, kind, take)


def create_runtime(path=DEFAULT_DRAFT_PATH, operator=LOCAL_OPERATOR, model=None, *, media_dir=None,
                   openrouter_models=(), review_transport=None, openrouter_draft_models=(), draft_transport=None,
                   main_models=(), main_transport=None, planner_simulator=None, placement_classifier=None,
                   reporting=None, planner_model=None, instruction_reviewer=None, instruction_drafter=None,
                   demo_scenario=None, context=LOCAL_CONTEXT, campaign_id=None, access=None, examples=None,
                   viewer_links=None, web=False, initialize=True, setup_provider=None) -> AgentRuntime:
    demo_report = None
    if demo_scenario is not None:
        if demo_scenario not in demo_delivery.SCENARIOS or reporting is not None:
            raise ValueError('Choose a portable demo scenario without live reporting.')
        demo_report = partial(demo_delivery.snapshot, scenario=demo_scenario)

    operator.require_brand(context.scope)
    drafts = create_drafts(path, False, operator, media_dir=media_dir, context=context, campaign_id=campaign_id,
                           access=access, examples=examples, initialize=initialize)
    path = drafts.path
    if initialize:
        startup.initialize_runtime_schema(path, simulated_setup=setup_provider is None)
    setup_storage = SQLiteSetupDeliveryStorage(path)
    setup = _NativeCampaignSetup(drafts, SimulatedCampaignSetup(path) if setup_provider is None else setup_provider,
                                 setup_storage, viewer_links=viewer_links)
    viewer = _NativeViewerMeasurement(path, drafts.examples, campaign_id=drafts.campaign_id)
    performance = create_performance(drafts, viewer, initialize=False)
    delivery = _NativeCampaignDelivery(drafts, setup, performance, setup_storage, reporting,
                                       demo_scenario=demo_scenario, demo_report=demo_report)
    tests = create_experiments(drafts, viewer, performance)
    reviewer = (OpenRouterReviews(openrouter_models, transport=review_transport)
                if instruction_reviewer is None else instruction_reviewer)
    drafter = (OpenRouterInstructions(openrouter_draft_models, transport=draft_transport)
               if instruction_drafter is None else instruction_drafter)
    runtime = AgentRuntime(drafts, model or RecordedInference(), setup=setup, performance=performance,
                           delivery=delivery, instruction_tests=tests, instruction_findings=InstructionFindings(tests, tests.storage),
                           reviewer=reviewer, drafter=drafter, demo_catalog=DEMO_CATALOG, web=web)
    remote = (OpenRouterPlanner(main_models, transport=main_transport, request_body=planner_request_body)
              if planner_model is None else planner_model)
    runtime.planner = PlacementAgent(
        runtime, remote=remote, catalogs=PlacementDiscovery(drafts, SQLiteCatalogStorage(path)),
        simulator=SimulatedPlanner() if planner_simulator is None else planner_simulator,
        classifier=SimulatedClassifier() if placement_classifier is None else placement_classifier,
        receipts=SQLitePlannerLifecycleStorage(path), commit_storage=SQLitePlacementCommitStorage(path),
        read_storage=SQLitePlannerReadStorage(path), conversations=SQLiteConversationStorage(path),
    )
    # Only the native adapters this root constructed are qualified for foreground.
    runtime.planner.foreground_compatible = planner_model is None
    runtime.structured_foreground_compatible = instruction_reviewer is None and instruction_drafter is None
    return runtime


def create_provider_sessions(path, *, initialize=True, **options) -> ProviderSessions:
    if initialize:
        migrate_path(path)
    return ProviderSessions(path, cache=CatalogueCache(), **options)


def create_viewer(path, examples=EXAMPLES, *, campaign_id='tts-sample', initialize=True):
    if initialize:
        startup.initialize_viewer(path)
    return _NativeViewerMeasurement(path, examples, campaign_id=campaign_id)


def create_setup(drafts, provider, *, viewer_links=None):
    startup.initialize_campaign_setup(drafts.path)
    return _NativeCampaignSetup(drafts, provider, SQLiteSetupDeliveryStorage(drafts.path), viewer_links=viewer_links)


def create_simulated_setup(path):
    startup.initialize_simulated_setup(path)
    return SimulatedCampaignSetup(path)


def create_asset_store(path, root):
    store = AssetStore(path, root)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    migrate_path(store.path)
    return store


def create_staff_sessions(path, verifier, **options):
    sessions = StaffSessions(path, verifier, **options)
    startup.initialize_staff_sessions(path)
    return sessions
