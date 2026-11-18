"""Build the native runtime dependencies for the supported launchers."""
from functools import partial

from campaign_agent.access import LOCAL_CONTEXT, LOCAL_OPERATOR
from campaign_agent.adapters import demo_delivery
from campaign_agent.adapters.catalogue_cache import CatalogueCache
from campaign_agent.adapters.openrouter_instructions import OpenRouterInstructions
from campaign_agent.adapters.openrouter_reviews import OpenRouterPlanner, OpenRouterReviews
from campaign_agent.adapters.sample_reporting import SampleCampaignReporting
from campaign_agent.adapters.simulated_setup import SimulatedCampaignSetup
from campaign_agent.agent.planning_models import SimulatedPlanner, planner_request_body
from campaign_agent.agent.run import AgentRuntime, RecordedInference
from campaign_agent.application.campaigns import DEFAULT_DRAFT_PATH
from campaign_agent.placement_discovery import SimulatedClassifier
from campaign_agent.performance import CampaignPerformance
from campaign_agent.provider_sessions import ProviderSessions


def create_runtime(path=DEFAULT_DRAFT_PATH, operator=LOCAL_OPERATOR, model=None, *, media_dir=None,
                   openrouter_models=(), review_transport=None, openrouter_draft_models=(), draft_transport=None,
                   main_models=(), main_transport=None, planner_simulator=None, placement_classifier=None,
                   reporting=None, planner_model=None, instruction_reviewer=None, instruction_drafter=None,
                   demo_scenario=None, context=LOCAL_CONTEXT, campaign_id=None, access=None, examples=None,
                   viewer_links=None, web=False, initialize=True, setup_provider=None) -> AgentRuntime:
    def make_setup():
        if setup_provider is not None:
            return setup_provider
        return SimulatedCampaignSetup(path, initialize=initialize)

    def make_planner():
        if planner_model is not None:
            return planner_model
        return OpenRouterPlanner(main_models, transport=main_transport, request_body=planner_request_body)

    def make_reviewer():
        if instruction_reviewer is not None:
            return instruction_reviewer
        return OpenRouterReviews(openrouter_models, transport=review_transport)

    def make_drafter():
        if instruction_drafter is not None:
            return instruction_drafter
        return OpenRouterInstructions(openrouter_draft_models, transport=draft_transport)

    demo_report = None
    if demo_scenario is not None:
        if demo_scenario not in demo_delivery.SCENARIOS or reporting is not None:
            raise ValueError('Choose a portable demo scenario without live reporting.')
        demo_report = partial(demo_delivery.snapshot, scenario=demo_scenario)

    runtime = AgentRuntime(
        path, operator, model or RecordedInference(), make_setup_provider=make_setup,
        make_sample_reporting=SampleCampaignReporting, make_main_model=make_planner,
        make_reviewer=make_reviewer, make_drafter=make_drafter, media_dir=media_dir,
        planner_simulator=SimulatedPlanner() if planner_simulator is None else planner_simulator,
        placement_classifier=SimulatedClassifier() if placement_classifier is None else placement_classifier,
        reporting=reporting, demo_scenario=demo_scenario, demo_report=demo_report, context=context,
        campaign_id=campaign_id, access=access, examples=examples, viewer_links=viewer_links,
        web=web, initialize=initialize,
    )
    # Only this composition constructs and qualifies the native foreground adapters.
    # The explicit replacement arguments take the offline-only application path.
    runtime.planner.foreground_compatible = planner_model is None
    runtime.structured_foreground_compatible = instruction_reviewer is None and instruction_drafter is None
    return runtime


def create_provider_sessions(path, **options) -> ProviderSessions:
    return ProviderSessions(path, cache=CatalogueCache(), **options)


def create_performance(drafts, viewer, *, initialize=True) -> CampaignPerformance:
    return CampaignPerformance(drafts, viewer, SampleCampaignReporting(), initialize=initialize)
