"""Assemble the native staff and public applications before serving either origin."""
from functools import partial
from secrets import token_urlsafe
from time import time

from campaign_agent.adapters.gateplane import GateplaneAccess
from campaign_agent.adapters.sqlite_access import SQLiteCampaignAccessStorage
from campaign_agent.adapters.sqlite_planner_startup import (
    bind_campaign, initialize_drafts, initialize_publications, initialize_runtime_schema,
)
from campaign_agent.adapters.sqlite_viewer import SQLiteViewerStorage
from campaign_agent.bootstrap.runtime import create_provider_sessions, create_runtime, create_viewer, draft_seed
from campaign_agent.hosted import HostedApplication
from campaign_agent.publications import Publications


def initialize_hosted_storage(path):
    initialize_drafts(path)
    initialize_runtime_schema(path)
    initialize_publications(path)


def create_hosted_runtime(path, operator, *, context, campaign_id, access, **options):
    runtime = create_runtime(path, operator, context=context, campaign_id=campaign_id, access=access,
                             initialize=False, **options)
    drafts = runtime.drafts
    bind_campaign(path, context=context, campaign_id=campaign_id, seed_snapshot=draft_seed(campaign_id),
                  authorize=drafts.require)
    return runtime


def create_hosted_application(path, sessions, client, assets, *, provider_metadata=None, provider_profiles=(),
                              authority_factory=None, initialize=True, **options):
    if authority_factory is None:
        authority_factory = partial(GateplaneAccess, campaign_access=SQLiteCampaignAccessStorage(path))
    # Validate transport configuration before starting the store.
    providers = create_provider_sessions(path, initialize=False, metadata=provider_metadata,
                                         profiles=provider_profiles)
    publications = Publications(
        SQLiteViewerStorage(path), assets,
        lambda examples, campaign: create_viewer(path, examples, campaign_id=campaign, initialize=False),
        clock=time, new_token=lambda: token_urlsafe(32),
    )
    app = HostedApplication(path, sessions, client, assets, publications=publications,
                            provider_sessions=providers,
                            authority_factory=authority_factory, runtime_factory=create_hosted_runtime,
                            provider_metadata=provider_metadata, **options)
    if initialize:
        initialize_hosted_storage(path)
    return app
