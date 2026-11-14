"""Advisory capability metadata; execution authority stays in application commands."""
from contextlib import closing
from dataclasses import dataclass
import sqlite3

from campaign_agent.workspaces import verify


READ = 'youtube:campaign.read'
RUN = 'youtube:agent.run'


@dataclass(frozen=True)
class Capability:
    id: str
    title: str
    description: str
    effects: tuple[str, ...]
    prerequisites: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = (READ, RUN)
    required_draft_permission: str | None = None
    kind: str = 'model_tool'
    mode: str = 'application'


# These definitions describe existing handlers; they do not register or authorize tools.
CAPABILITIES = (
    Capability('read_campaign', 'Read the campaign',
        'Inspect the saved brief, rules and placements.', ('read',)),
    Capability('inspect_catalog', 'Inspect a placement catalog',
        'Read a bounded preview of the catalog bound to the request.', ('read',), ('bound_catalog',)),
    Capability('classify_catalog', 'Classify placements',
        'Classify a permitted catalog with the simulated specialist; accuracy is not verified.',
        ('compute', 'derived_record_write'), ('bound_catalog',), mode='simulated_specialist'),
    Capability('validate_campaign_setup', 'Validate a paused setup',
        'Save simulated paused-setup validation for buyer review; never create or launch ads.',
        ('compute', 'derived_record_write'), ('approved_package', 'valid_destinations'),
        (READ, RUN, 'youtube:setup.manage'), mode='simulated_setup'),
    Capability('review_performance', 'Review campaign performance',
        'Save a review separating sample delivery from observed local viewer activity.',
        ('read', 'derived_record_write'), ('approved_package', 'current_activity'),
        (READ, RUN, 'youtube:review.write'), mode='sample_performance'),
    Capability('load_experiment_evidence', 'Read experiment evidence',
        'Read assigned outcomes for the instruction experiment bound to the request.',
        ('read',), ('approved_package', 'bound_instruction_experiment')),
    Capability('assess_instruction_experiment', 'Assess an instruction experiment',
        'Save an evidence-checked assessment using supported reason codes.',
        ('read', 'derived_record_write'), ('loaded_assigned_evidence', 'current_correction'),
        (READ, RUN, 'youtube:review.write')),
    Capability('prepare_next_test', 'Prepare an instruction test',
        'Save an unapproved wording revision from approved neutral instruction components.',
        ('draft_write',), ('approved_package', 'eligible_current_review', 'keep_takes_correction'),
        (READ, RUN, 'youtube:campaign.draft'), 'instruction_test', mode='fixed_instruction_components'),
    Capability('save_placement_draft', 'Save a placement draft',
        'Save permitted, unambiguous classified placements as an unapproved revision.',
        ('draft_write',), ('classified_catalog', 'current_revision'),
        (READ, RUN, 'youtube:campaign.draft'), 'placements', mode='simulated_specialist'),
    Capability('ask_clarification', 'Ask a necessary question',
        'Return a supported clarification question without changing campaign content.', ('none',)),
    Capability('respond', 'Explain current campaign facts',
        'Select a supported topic; the application renders factual wording.', ('none',)),
    Capability('review_google_ads_delivery', 'Review saved campaign delivery',
        'Capture a delivery report through the configured reporting path or labelled offline rehearsal.',
        ('read', 'derived_record_write'), ('verified_setup', 'current_destinations'),
        (READ, RUN, 'youtube:review.write'), kind='application_request', mode='delivery'),
    Capability('recommend_delivery_next_test', 'Recommend a delivery test',
        'Save a next-test recommendation from the latest eligible delivery report.',
        ('read', 'derived_record_write'), ('eligible_saved_delivery_report', 'current_correction'),
        (READ, RUN, 'youtube:review.write'), kind='application_request'),
    Capability('apply_instruction_finding', 'Apply a supported finding',
        'Prepare an unapproved wording draft through the workspace action, not a model tool.',
        ('draft_write',), ('eligible_current_finding', 'compatible_brief', 'current_correction'),
        (READ, 'youtube:campaign.draft'), 'instruction_test', kind='workspace_action'),
    Capability('generate_contextual_voiceover', 'Generate a contextual voiceover',
        'Planned creative production; no generation tool is implemented in this catalogue.',
        ('external',), ('reviewed_creative_brief', 'generation_budget', 'permitted_assets'),
        (READ,), kind='planned', mode='unimplemented'),
)


def _mode(definition, runtime):
    if definition.mode == 'delivery':
        if runtime.delivery.reporting is not None:
            return ['configured_reporting', 'local_viewer_activity'], False
        if runtime.delivery.demo_scenario:
            return ['authored_delivery', 'local_viewer_activity'], True
        return ['offline_rehearsal', 'local_viewer_activity'], True
    if definition.mode == 'sample_performance':
        return ['sample_delivery', 'local_viewer_activity'], True
    if definition.mode == 'unimplemented':
        return [], False
    return [definition.mode], definition.mode in {'simulated_specialist', 'simulated_setup'}


def catalogue(runtime):
    """Project current scope/grants once per capability, never business readiness or effects."""
    runtime.require(READ)
    with closing(sqlite3.connect(runtime.path)) as db:
        verify(db, runtime.drafts.context, runtime.drafts.campaign_id)
    allowed = {READ: True}
    for permission in dict.fromkeys(permission for item in CAPABILITIES
                                    for permission in item.required_capabilities):
        if permission in allowed:
            continue
        try:
            runtime.require(permission)
        except PermissionError:
            allowed[permission] = False
        else:
            allowed[permission] = True
    result = []
    for item in CAPABILITIES:
        modes, offline = _mode(item, runtime)
        reasons = []
        if item.kind == 'planned':
            state, reasons = 'planned', ['not_implemented']
        else:
            if any(not allowed[permission] for permission in item.required_capabilities):
                reasons.append('permission_denied')
            if item.required_draft_permission is not None:
                reasons.append('request_draft_permission_required')
            state = 'blocked' if reasons else 'offline_only' if offline else 'available'
            if offline:
                reasons.append('offline_implementation')
            if item.mode == 'delivery' and runtime.delivery.reporting is None and not runtime.delivery.demo_scenario:
                reasons.append('delivery_metrics_unavailable')
        result.append({
            'id': item.id, 'title': item.title, 'description': item.description, 'kind': item.kind,
            'tool_names': [item.id] if item.kind == 'model_tool' else [],
            'effects': [*item.effects, *(['external_read'] if item.mode == 'delivery'
                        and runtime.delivery.reporting is not None else [])],
            'required_capabilities': list(item.required_capabilities),
            'required_draft_permission': item.required_draft_permission,
            'prerequisites': list(item.prerequisites), 'execution_modes': modes,
            'state': state, 'reason_codes': reasons,
        })
    return {'schema_version': 1, 'availability_scope': 'current_access_and_configuration',
            'prerequisites_checked_at': 'dispatch', 'capabilities': result}
