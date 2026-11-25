# Agent capability catalogue API · version 1

14 November 2026 · [Architecture](architecture-plan.md) · [Source map](source-map.md)

`GET /api/agent/capabilities` returns an advisory catalogue for the server-selected
campaign and current operator. The local planner requires its operator credential;
the hosted staff API requires the existing staff session and current access.
The public viewer does not serve this endpoint. No query fields or selectors are
accepted, including model, campaign, run, catalog or draft-permission fields.

This is the API slice for #52. The capability UI and factual capability-reply
integration belong to #53. This catalogue is not an OpenRouter model catalogue
and introduces no runtime skills, provider connection or new executable tools.

## Meaning of availability

The command checks current campaign-read access and native campaign ownership
before projection. It checks each distinct additional grant once per request;
decisions are not cached between requests. An authority outage fails the read
rather than being converted into a denied or available entry.

Availability covers registration, current grants and implementation mode. It
does **not** prove that a particular package, catalog, report or instruction
experiment is ready. `prerequisites` declares those checks; existing commands
still resolve their exact inputs and recheck authority, revisions, evidence,
media and approvals at dispatch/commit. Listing capabilities performs none of
those operations and creates no campaign, run, review, report or approval.

The catalogue is outside any run. A role cannot supply a per-request draft
permission, so all draft operations are blocked with
`request_draft_permission_required` even when campaign-draft access is allowed.
Changing catalogue JSON or selecting an entry cannot authorize a write.

## Response schema

All fields below are required. Objects contain only the declared fields. Array
order is deterministic but consumers should use stable capability IDs, not
positions. `schema_version` changes for incompatible response-contract changes.

| Top-level field | Type / exact value |
| --- | --- |
| `schema_version` | Integer `1` |
| `availability_scope` | String `current_access_and_configuration` |
| `prerequisites_checked_at` | String `dispatch` |
| `capabilities` | Array of capability objects |

| Capability field | Type / semantics |
| --- | --- |
| `id` | Stable operation/capability string from the registry |
| `title` | Static user-facing title |
| `description` | Static description, never imported/private prose |
| `kind` | `model_tool`, `application_request`, `workspace_action`, or `planned` |
| `tool_names` | String array: the matching name for a model tool; empty for other kinds |
| `effects` | Array containing `read`, `compute`, `derived_record_write`, `draft_write`, `external_read`, `external`, or `none` |
| `required_capabilities` | Array of existing product access-capability strings |
| `required_draft_permission` | `null`, `placements`, or `instruction_test` |
| `prerequisites` | Array of stable prerequisite codes, checked by execution commands |
| `execution_modes` | Array of implementation-mode codes; empty for planned capabilities |
| `state` | `available`, `blocked`, `offline_only`, or `planned` |
| `reason_codes` | Array of stable explanatory codes |

Effects describe business operations. All executed agent turns also have their
existing run journal; `none` means no campaign business change, not an absence
of run auditing. `external_read` describes a possible configured reporting call;
it is not permission for provider changes or spend. The catalogue GET never
makes that call. `external` on the planned voiceover describes its proposed
future effect, not an implemented provider capability.

| State | Meaning |
| --- | --- |
| `available` | Registered and permitted for this access/configuration projection; request prerequisites still apply. |
| `blocked` | A current required grant or per-request draft grant is absent. |
| `offline_only` | Permitted projection with a simulated/sample/rehearsal implementation. |
| `planned` | Explicitly unimplemented; never available as a tool. |

Reasons are ordered: permission, draft permission, offline implementation and
delivery coverage. A blocked entry can also carry an offline explanation.

| Reason code | Meaning |
| --- | --- |
| `permission_denied` | At least one required current product grant is denied. |
| `request_draft_permission_required` | The write requires a separately bound per-request draft permission. |
| `offline_implementation` | The operation uses a simulated/sample/rehearsal implementation. |
| `delivery_metrics_unavailable` | The rehearsal has no paid-delivery metrics; local viewer activity remains separate. |
| `not_implemented` | Planned metadata only; there is no executable operation. |

Execution modes are `application`, `simulated_specialist`, `simulated_setup`,
`sample_delivery`, `local_viewer_activity`, `fixed_instruction_components`,
`configured_reporting`, `authored_delivery`, and `offline_rehearsal`.
Configuring an OpenRouter main model does not make the placement specialist or
paused setup live. Performance review retains sample delivery/local activity.
Delivery capture uses configured reporting when present, an explicit authored
demo scenario otherwise, or an offline rehearsal without delivery metrics.
Recommending a test is application work from an eligible saved report; it does
not require a currently connected reporting adapter or perform a new report call.

## Current operations and prerequisites

| ID | Kind | Declared prerequisites |
| --- | --- | --- |
| `read_campaign` | Model tool | None beyond current access |
| `inspect_catalog` | Model tool | `bound_catalog` |
| `classify_catalog` | Model tool | `bound_catalog` |
| `validate_campaign_setup` | Model tool | `approved_package`, `valid_destinations` |
| `review_performance` | Model tool | `approved_package`, `current_activity` |
| `load_experiment_evidence` | Model tool | `approved_package`, `bound_instruction_experiment` |
| `assess_instruction_experiment` | Model tool | `loaded_assigned_evidence`, `current_correction` |
| `prepare_next_test` | Model tool | `approved_package`, `eligible_current_review`, `keep_takes_correction` |
| `save_placement_draft` | Model tool | `classified_catalog`, `current_revision` |
| `ask_clarification` | Model tool | Supported question reasons only |
| `respond` | Model tool | Supported reply topics only |
| `review_google_ads_delivery` | Application request | `verified_setup`, `current_destinations` |
| `recommend_delivery_next_test` | Application request | `eligible_saved_delivery_report`, `current_correction` |
| `apply_instruction_finding` | Workspace action | `eligible_current_finding`, `compatible_brief`, `current_correction` |
| `generate_contextual_voiceover` | Planned | `reviewed_creative_brief`, `generation_budget`, `permitted_assets` |

`current_correction` means the current correction state, including absence where
the native command permits it. The catalogue does not assert that a correction
exists. Supported question/topic constraints remain in the unchanged tool schema.

All model and application-request entries need campaign-read and agent-run
access. Saving reviews/reports/recommendations additionally needs review-write;
setup validation needs setup-manage; drafts need campaign-draft access. Finding
application is a workspace draft action, not a main-model tool, and does not
acquire a learning-manage requirement merely because it consumes a finding.

## Example response entry

This excerpt is one complete entry in the response's `capabilities` array.
It contains no campaign, actor, workspace, catalog, run, evidence, account or
credential references.

```json
{
  "id": "save_placement_draft",
  "title": "Save a placement draft",
  "description": "Save permitted, unambiguous classified placements as an unapproved revision.",
  "kind": "model_tool",
  "tool_names": ["save_placement_draft"],
  "effects": ["draft_write"],
  "required_capabilities": [
    "youtube:campaign.read", "youtube:agent.run", "youtube:campaign.draft"
  ],
  "required_draft_permission": "placements",
  "prerequisites": ["classified_catalog", "current_revision"],
  "execution_modes": ["simulated_specialist"],
  "state": "blocked",
  "reason_codes": ["request_draft_permission_required", "offline_implementation"]
}
```

## Failure and verification boundary

Unknown/query fields return 400. Missing hosted sign-in returns 401; missing local
operator or denied current access returns 403. Current-authority/storage outages
return 503. The viewer and a local mode without an agent return 404. Existing
host/origin/session protections still apply. Select a campaign through the
existing staff context command, never by adding a selector to this endpoint.

Focused tests verify exact model-tool coverage, immutable metadata projection,
fresh scoped access and outage behavior, native ownership, local/hosted/public
routes, no domain writes or provider/readiness calls, component modes, and actual
denied/replayed/unknown dispatch. The catalogue never supplies execution authority
and does not change provider tool schemas, prompts, reply wording or dispatch.

## Workspace discovery and chat answers

The **Capabilities** control beside the composer fetches the current scoped
catalogue through the existing authenticated API client. It shares the composer's
single options panel: Escape returns focus to its trigger. Each expandable row
shows the outcome, availability, execution mode and requirements, with model tools,
application requests, workspace actions and planned features labelled separately.

**Use example** fills the message and focuses the textarea. It does not send,
change **Changes**, grant access, approve a package or call a provider. Examples
are presentation wording, not another tool registry. Planned features have no
example action. Draft outcomes explain the explicit per-request Changes setting;
the supported-finding action remains in its workspace rather than becoming a
model tool. Actual commands still recheck permissions, revisions and prerequisites.

The catalogue stays in component memory, never browser storage. Opening the panel,
using **Refresh capabilities**, or reloading refetches current access. A scope key
includes actor, client, brand, workspace and campaign; changing it clears the
rendered result and ignores obsolete responses. A failed refresh hides the previous
catalogue and shows a retry message. The existing application resolves workspace
scope at bootstrap; this slice does not add a workspace-switching interface.

For the supported `capabilities` response topic, the real tool dispatcher loads
`AgentRuntime.capabilities()` and application code groups its titles by current
availability. It explains offline simulation, blocked access/draft requirements,
workspace-only actions and planned features, rather than accepting model-authored
claims. Access outages propagate without saving an optimistic answer. The answer
retains the existing no-change/approval/export/launch notice and verified reply
format. Saved conversations keep the factual answer from their original turn;
ask again or refresh discovery for current access.
