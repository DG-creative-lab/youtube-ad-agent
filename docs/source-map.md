# Source-code map

The [demo eval gate](demo-release-evals.md) is owned by
`scripts/evaluate_demo_release.py`, with the frozen companion manifest in
`examples/demo-release-evals.v1.json` and gate regression tests in
`tests/test_demo_release_evals.py`. It reuses `scripts/evaluate_agent_behavior.py`
and `scripts/compare_instruction_policies.py`; application runtime ownership is
unchanged.

The staged map includes #87 foundation contracts/offline injection before #86;
#86 owns every pilot native participant and its minimal factory, with #87 final
external adoption and #88 consolidation afterward.

Use the accepted [boundary ADR](hexagonal-architecture.md) for semantic rules
and historical [module map](hexagonal-module-map.json) for the #83 source/target
snapshot (60Python/17web plus retained legacy client). Proposed targets remain
plans until implemented. PR #90 accepted #83 at
`7c139e19bfbf0d829b31f8d09320e912e5561f6b`.

Initial #84 was human-merged in [PR #91](https://github.com/DG-creative-lab/youtube-ad-agent/pull/91)
at `9fabf358b30cbc794455c1da78440043593d1497`. The first #85 domain-foundation
slice adds five Python modules (including the inert package marker), for 66 exact
roles after that slice; the decision policy added a 67th role; the campaign application module and marker bring the [live policy](architecture-policy.json) to 69; the delivery policy adds two roles for 71. The
[baseline](architecture-baseline.json) shrinks from 88 to 86 module edges. Pure
scope values, shared errors and video-ID syntax now have domain owners; old paths
reexport the same objects and runtime consumers use the new owners directly.
Relocated classes, including CampaignDrafts, have new `__module__` metadata.
Patching globals on the old script wrapper does not patch its moved methods;
application JSON/error/hash compatibility is preserved. CampaignDrafts now resides in the application module. PR #97 closed the revised #85 scope; deeper inversion remains in the later issues. Web inventory remains in the historical map.

This map translates the [application architecture](architecture-plan.md) into code ownership and proposes where capabilities should grow.

## Provider composition · #87

The recorded agent command, local planner launchers and hosted runtime use the
native composition in `bootstrap/runtime.py`. It supplies the OpenRouter models,
simulated setup, authored reporting and the request-local runtime configuration.
The runtime starts with foreground compatibility disabled. The composition only
qualifies adapters it builds itself. Explicitly supplied models retain the existing
offline-only path.

`application/catalogue_policy.py` owns advisory normalization and route selection
with an explicit clock. `adapters/catalogue_cache.py` owns the bounded process cache.
Each provider-session service gets one cache, and sessions prove scope and key
binding before using it. The hosted fixture still resolves current staff authority
before runtime construction. Local and Gateplane access adapters use the shared
permit check against typed ownership and revision records. Foreground writes
borrow the reader on their existing SQLite transaction.

Python callers that previously constructed a runtime with the implicit defaults
now use `bootstrap.runtime.create_runtime`. The internal catalogue
`normalize` helper takes an explicit `now`; the provider-session service supplies
its configured clock. The CLI invocations and HTTP routes are the same.

## OpenRouter request policy · #87

`agent/planning_models.py` owns the planner's prompt, tool declarations and context
projection. `agent/run.py` passes that request builder to the OpenRouter adapter,
which encodes the final request, fits the byte limit and parses response receipts.
`domain/instruction_requests.py` owns the evidence projection, prompts and assessment
schema for structured instruction requests. Existing commands still decide whether
to admit inference and accept its results. The composition root supplies the native providers to application commands.

## Campaign setup and reporting contracts · #87

`ports/campaign_effects.py` owns the setup provider, delivery binding and reporting
contracts, and the setup error shared by their callers. The Google Ads adapters
use those contracts and pure domain helpers for fingerprints and video IDs.
Existing setup and delivery imports remain available. Setup approval, creation
reservation and read-back still use the recorded plan, while delivery matches the
verified setup before saving a report. Filesystem and runtime composition changes
remain separate migration work.

## Structured model services · #87

`ports/planning.py` owns `InstructionReviewer` and `InstructionDrafter` with typed
logical receipts/usage; no provider request, credential or HTTP object crosses
these contracts. `agent/run.py` accepts either dependency explicitly and uses the
same assessment/drafting commands, source checks and receipt lifecycle as before.
`bootstrap/planner.py:create_local_planner` forwards those constructor options.
Default OpenRouter classes and their imports remain compatible.

`agent/run.py` owns the offline-only fence for supplied structured dependencies;
`foreground_inference.py` rejects their attachment before credentials/policy or
provider configuration. A received receipt skips fresh-effect checks and inference.
These are consumer seams, not completion of #87's provider/request-policy cleanup
or #88's legacy-constructor consolidation. See `test_structured_model_services.py`
for actual substituted workflows, faults, freshness, replay and denial checks.

## Selected #86 placement composition

The #86 pilot accepted in PR #104 is `bootstrap/planner.py:create_local_planner`,
which initializes native adapters before `AgentRuntime(initialize=False)` and
selects the typed local simulated-placement application. It is integrated with the
local planner UI and the shared dispatcher; retained review/delivery/experiment and
foreground commands keep their supported original-store paths. Earlier role counts
and checkpoint narratives above are historical; #85 closed under its revised scope.
See the [residual native graph](native-storage-migration.md) for the complete #37
migration inventory and #87/#88 boundaries. #86 is closed; its broader residual graph remains open under those owners.

| Current selected owner | Responsibility |
| --- | --- |
| [bootstrap/runtime.py](../campaign_agent/bootstrap/runtime.py), [bootstrap/hosted.py](../campaign_agent/bootstrap/hosted.py) | Prepare native storage and assemble the runtime graph. Hosted requests resolve current staff authority and can seed an authorized provisioned campaign without rerunning schema startup. |
| [bootstrap/local.py](../campaign_agent/bootstrap/local.py), [planner.py](../campaign_agent/bootstrap/planner.py), [placement_router.py](../campaign_agent/bootstrap/placement_router.py) | Explicit local startup and supported command/UI selection; existing nonpilot workflows retain their original dispatcher after the selected unit exits. |
| [application/planner_runtime.py](../campaign_agent/application/planner_runtime.py), [ports/placement_commit.py](../campaign_agent/ports/placement_commit.py) | Scoped placement start/follow-up, reservation, tool validation, terminal commit and recovery over typed same-store units. |
| [application/access.py](../campaign_agent/application/access.py), [adapters/local_placement_authority.py](../campaign_agent/adapters/local_placement_authority.py) | Original command permits acquired outside locks, same-unit owner/preimage/deadline validation and explicit authorized draft postimage. |
| [application/planner_context.py](../campaign_agent/application/planner_context.py), [ports/planner_context.py](../campaign_agent/ports/planner_context.py), [adapters/sqlite_planner_context.py](../campaign_agent/adapters/sqlite_planner_context.py) | Package identity and actual scoped approval/review/correction/started-test context, including nonempty evidence. |
| [adapters/local_media.py](../campaign_agent/adapters/local_media.py), [ports/storage_errors.py](../campaign_agent/ports/storage_errors.py) | Real logical media capture/currentness and safe adopted storage failures; no native handles or driver objects in application contracts. |
| [adapters/sqlite_schema.py](../campaign_agent/adapters/sqlite_schema.py), [sqlite_workspace_admission.py](../campaign_agent/adapters/sqlite_workspace_admission.py), [sqlite_planner_startup.py](../campaign_agent/adapters/sqlite_planner_startup.py) | Native schema, owner/demo admission, seed, viewer legacy quarantine, correction/provenance and transcript adoption; journal/history semantics preserved. |

## Current checkout

| Path | What it owns today |
| --- | --- |
| [domain/delivery_next_test.py](../campaign_agent/domain/delivery_next_test.py), [domain/performance.py](../campaign_agent/domain/performance.py) | Pure delivery recommendations, evidence thresholds and buyer-correction choices; storage and authorization stay in application modules. Old imports reexport the same objects; patching globals on the old recommendation wrapper does not patch the moved functions. |
| [domain/scope.py](../campaign_agent/domain/scope.py) | BrandScope, Operator and WorkspaceContext values/validation; defaults and current-authority decisions stay in access.py. |
| [domain/errors.py](../campaign_agent/domain/errors.py), [domain/inference_errors.py](../campaign_agent/domain/inference_errors.py) | Shared campaign conflicts and sanitized inference failure, independent of script/provider modules. |
| [domain/placements.py](../campaign_agent/domain/placements.py) | Shared video-ID syntax, independent of script imports. |
| [scripts/check_architecture.py](../scripts/check_architecture.py) | Small stdlib Python import/role/cycle checker with selected-base shrink guard and strict mode; never executes scanned code. |
| [tests/test_architecture_boundaries.py](../tests/test_architecture_boundaries.py) | Authored temporary CLI/Git fixtures for import boundaries, cycle failures and baseline shrinking; developer/test support only. |
| [architecture-policy.json](architecture-policy.json), [architecture-baseline.json](architecture-baseline.json) | Schema-1 exact Python classifications and readable module-edge exceptions; detailed ownership/line diagnostics, no baseline updater. |
| [placement-review/index.html](../placement-review/index.html) | Placement search and review UI, unsaved selections, draft conflict reconciliation and per-context export. |
| [scripts/placement_review.py](../scripts/placement_review.py) | The local server and developer CLI. It also contains YouTube search, sample search, catalog classification and the optional Jev call. |
| [campaign_agent/hosted.py](../campaign_agent/hosted.py), [staff.py](../campaign_agent/staff.py) and [adapters/gateplane.py](../campaign_agent/adapters/gateplane.py) | ASGI staff/public entrypoints, server-side session binding and current request-bound wire decisions over existing commands. |
| [campaign_agent/publications.py](../campaign_agent/publications.py) | Explicit approved-comparison publication, expiring opaque links and narrow public media/events. |
| [campaign_agent/migrations.py](../campaign_agent/migrations.py), [assets.py](../campaign_agent/assets.py) and [recovery.py](../campaign_agent/recovery.py) | Versioned ownership/asset schema, immutable brand media catalogs and private blobs, and operator-only SQLite/media backup/restore. [Topology and limits](storage-recovery.md) |
| [scripts/product_storage.py](../scripts/product_storage.py) | Migration status/upgrade, verified backup and restore into a new directory. |
| [scripts/hosted_access_fixture.py](../scripts/hosted_access_fixture.py) and [adapters/fixture_access.py](../campaign_agent/adapters/fixture_access.py) | Loopback-only synthetic identity/access composition; refuses nonfixture data and cannot select a real provider. |
| [campaign_agent/access.py](../campaign_agent/access.py), [ports/access.py](../campaign_agent/ports/access.py) and [adapters/local_access.py](../campaign_agent/adapters/local_access.py) | Server-resolved workspace context, operator brand grants, current capability decisions and the exact local-only access adapter. |
| [campaign_agent/workspaces.py](../campaign_agent/workspaces.py) | Immutable brand/workspace/installation and campaign ownership, trusted provisioning and explicit legacy demo admission. |
| [application/campaigns.py](../campaign_agent/application/campaigns.py) | CampaignDrafts commands, native SQLite lifecycle and approvals. The old [script](../scripts/campaign_drafts.py) reexports the same objects for compatibility; storage inversion remains future work. |
| [campaign_agent/adapters/sqlite_drafts.py](../campaign_agent/adapters/sqlite_drafts.py) | Concrete native SQLite revision existence/latest/exact raw reads, raw appends and two fixed scoped catalog fact lookups, used by `CampaignDrafts` seed/read/placement/fresh-brief/instruction paths. Borrows the supplied connection without owning its lifecycle or authority. |
| [campaign_agent/agent/planner.py](../campaign_agent/agent/planner.py) and [planning_models.py](../campaign_agent/agent/planning_models.py) | Main-model port, tool schemas, simulated profiles, OpenRouter tool calling, pinned conversations, request receipts and the bounded placement loop. `_commit_turn()` uses the native draft write unit for draft/step/outcome/reply atomicity; inference and receipt phases remain separate. |
| [campaign_agent/adapters/sqlite_planner.py](../campaign_agent/adapters/sqlite_planner.py) | Concrete native SQLite default/job/turn records and ordered joined raw step history, used immediately by `PlacementAgent`. Borrows the supplied connection; preserves raw tuples/text/NULLs, the original three-field default scope and partial-column updates. JSON, authority, recovery decisions and lifecycle remain application-owned. |
| [campaign_agent/adapters/sqlite_runs.py](../campaign_agent/adapters/sqlite_runs.py) | Concrete native SQLite common run/step records: fully scoped raw run pairs, three distinct run insert conflict forms, status updates, ordered steps, strict append, count and existence. Runtime/planner/conversation status/foreground count use the exact borrowed connection; authorization, JSON, policy and lifecycle stay in application code. |
| [campaign_agent/agent/conversations.py](../campaign_agent/agent/conversations.py) | Application-owned private scope/model checks, JSON, verified replies and context/limit/title policy through typed repositories. The selected unit includes follow-up supersession and messages; the SQLite adapter owns transcript adoption. |
| [campaign_agent/adapters/sqlite_conversations.py](../campaign_agent/adapters/sqlite_conversations.py) | Concrete native SQLite raw session/message/job-context rows, message appends, latest ID/count, session/settings writes and four-scope lists for `CampaignConversations`. Preserves tuples/text and borrows the exact connection without lifecycle, JSON or authority. |
| [campaign_agent/agent/replies.py](../campaign_agent/agent/replies.py) | Application-owned reply topics, clarification wording and safe projection of legacy unverified replies. |
| [campaign_agent/agent/capabilities.py](../campaign_agent/agent/capabilities.py) | Immutable advisory capability metadata and current-access/configuration projection; the runtime and local/hosted staff GET route share its read command. [Version 1 API contract](agent-capabilities.md). It supplies no dispatch authority. |
| [campaign_agent/provider_sessions.py](../campaign_agent/provider_sessions.py) and [ports/inference.py](../campaign_agent/ports/inference.py) | Foreground connection, reconnect, catalogue, qualified-selection and disconnect commands. Durable records contain scoped salted verifiers and immutable selections, never raw keys. Hosted/local HTTP share these commands. |
| [campaign_agent/model_catalogue.py](../campaign_agent/model_catalogue.py) and [adapters/openrouter_models.py](../campaign_agent/adapters/openrouter_models.py) | Bounded connection-scoped metadata cache, decimal display prices, exact reviewed endpoint profiles and fixed-origin metadata probes. Production compositions start without a live metadata adapter or qualified profiles. |
| [campaign_agent/agent/review_tools.py](../campaign_agent/agent/review_tools.py) | Chat review/draft tools, application-resolved evidence references, readiness and freshness checks, grounded outcomes and instruction-component saves through existing commands. |
| [campaign_agent/placement_discovery.py](../campaign_agent/placement_discovery.py) | Immutable scoped catalogs, automatic classifier port, simulated specialist receipts and evidence-bound placement saves. |
| [campaign_agent/agent/run.py](../campaign_agent/agent/run.py) | Recorded model inference, scoped preparation runs, tool dispatch and atomic step results. Prepares placement drafts and instruction tests. |
| [campaign_agent/adapters/openrouter_reviews.py](../campaign_agent/adapters/openrouter_reviews.py) and [openrouter_instructions.py](../campaign_agent/adapters/openrouter_instructions.py) | Shared bounded OpenRouter transport, structured assessment and instruction-drafting prompts, response parsing and sanitized errors. |
| [campaign_agent/performance.py](../campaign_agent/performance.py) | Sample reporting, saved reviews, buyer corrections and validation of the evidence supporting an instruction test. |
| [campaign_agent/creatives.py](../campaign_agent/creatives.py) | Published examples and the approved neutral instruction components used to validate and assemble provider proposals. |
| [campaign_agent/instruction_tests.py](../campaign_agent/instruction_tests.py) | Approved test pairs, stable viewer assignments, saved agent assessments and cumulative learning evidence snapshots. |
| [domain/instruction_policy.py](../campaign_agent/domain/instruction_policy.py) | Offline posterior and value of one more batch; the old instruction_policy module reexports its objects for compatibility. |
| [campaign_agent/learning.py](../campaign_agent/learning.py) | Scoped instruction findings, source freshness, retirement, and reuse through the campaign draft writer. |
| [scripts/compare_instruction_policies.py](../scripts/compare_instruction_policies.py) | Frozen offline simulations, native assessment comparison, decision scoring and the persisted fresh-brief walkthrough. |
| [campaign_agent/handoff.py](../campaign_agent/handoff.py) | Package content fingerprints, media references and the manual setup export. |
| [campaign_agent/campaign_setup.py](../campaign_agent/campaign_setup.py) | Setup validation, exact-plan approval, one creation attempt and provider read-back. The simulated adapter stores its campaign separately from the approved plan. |
| [campaign_agent/adapters/google_ads_sandbox.py](../campaign_agent/adapters/google_ads_sandbox.py) | Test account verification, Demand Gen request construction, validation and read-back. [scripts/google_ads_sandbox.py](../scripts/google_ads_sandbox.py) is the opt-in entry point. |
| [campaign_agent/delivery.py](../campaign_agent/delivery.py) | Resolves the verified setup for the current approved package and saves read-only report snapshots. [Google Ads reporting](../campaign_agent/adapters/google_ads_reporting.py) queries ad-group totals and video placement details. |
| [campaign_agent/measurement.py](../campaign_agent/measurement.py) | Scoped viewer activity and completion attributed to exact comparison content. |
| [web/planner/src/openrouter-session.ts](../web/planner/src/openrouter-session.ts) | Private active-tab credential memory, strict foreground header transport, metadata-only connection persistence, current-key content checks and stale connection/catalogue/selection guards. Server-owned historical selections hydrate only in memory. |
| [web/planner/src/OpenRouterAccount.tsx](../web/planner/src/OpenRouterAccount.tsx) and [OpenRouterModels.tsx](../web/planner/src/OpenRouterModels.tsx) | Native account dialog, immediate password-field clearing, explicit reconnect/replace/disconnect, searchable priced catalogue and exact local budget choices. These controls never request a completion. |
| [web/planner/src/main.tsx](../web/planner/src/main.tsx) | Existing shared planner/structured start and resume path, receipt-first recovery, original-operation retention, profile-specific selection and independent draft-grant resets. |
| [web/planner/tests/openrouter-session.test.mjs](../web/planner/tests/openrouter-session.test.mjs) | Dependency-free Node boundary regressions using the locked TypeScript transpiler and authored request interleavings; enforced by the existing planner CI job. |
| [web/planner/src/AgentCapabilities.tsx](../web/planner/src/AgentCapabilities.tsx) | Scoped read-only capability discovery, execution/prerequisite labels and composer-only examples; consumes the catalogue API. |
| [web/planner/src/](../web/planner/src/) and [web/viewer/](../web/viewer/) | React campaign workspace and the public comparison experience. |
| [tests/](../tests/) and [examples/](../examples/) | Offline behavior tests, authored catalogs and synthetic evidence. Private state and credentials live under the ignored `.local/` directory. |

The browser calls the loopback API, which delegates to the owning application commands. Agent tools use those same commands. SQLite retains campaign revisions, approvals, reviews, corrections, viewer activity and agent progress. Live YouTube search results stay in the browser session.

PR #74's write unit, PR #75's draft store and PR #77's merged conversation store
(#76 closed) are bounded #37 seams. PR #79 merged the native planner record seam
and closed #78; #80 now adds the shared common run/step record seam.
Recorded preparation and structured review and drafting use typed run, source,
inference and evidence records. The retained planner and conversation paths
still borrow native transactions. Private media, recovery, and foreground
session and ledger transactions still require migration.
Actual Postgres repositories and conformance,
DB/blob recovery and all-campaign restore admission remain pending; no hosted
composition or new project authority is enabled.

## Where the code should grow

[Proposed project/sharing contract](project-sharing-contract.md) maps the next #55 ownership, access, source-resource and migration boundaries. No projects module, project capability or team-sharing API exists yet. Reuse native campaign writers and the current access/permit owner after producer/storage acceptance; the paths below remain proposed.

```text
campaign_agent/              Python application package
  bootstrap.py               Wire concrete adapters when assembly needs a home
  http.py                    Translate browser requests to application commands
  access.py                  Resolve actor and client/brand scope, enforce grants
  campaigns.py               Brief references, drafts, review and handoff
  placements.py              Search and independent catalog assignment
  creatives.py               Creative versions and comparison examples
  measurement.py             Viewer events, completion and delivery evidence
  knowledge.py               Versioned briefs, brand rules and source permissions
  learning.py                Scoped preferences, findings and experiment proposals
  agent/                     Run lifecycle, mandates and typed tool dispatch
  adapters/                  Concrete storage, provider and runtime integrations
web/
  viewer/                    Plain HTML, CSS and JavaScript comparison experience
  planner/                   React and TypeScript when the fuller planner lands
scripts/                     Developer commands and research probes
tests/                       Offline tests organized by the behavior they protect
examples/                    Shareable fixtures and permitted example assets
```

These are proposed homes. Create a file or subpackage when a slice gives it real code and a caller. Keep a capability in one module until it has a concrete reason to split. For example, extract brand knowledge when briefs and rules need their own lifecycle. Add learning when a review can produce reusable findings. Add an agent module when the workflow needs a dispatcher and durable runs. Add separate activation and reporting integrations as their callers arrive.

## Dependency and ownership rules

- **Clients call commands.** The browser calls HTTP. Agent tools and developer commands call the same application commands for shared behavior. Request handlers and tool schemas translate inputs. The owning module validates scope, provenance, revisions and permissions.
- **Access is resolved at entry.** The backend resolves the actor and requested client and brand before loading private records. Tools inherit scope from the saved run. Public viewer routes resolve only the example and event scope assigned to the link. [Tenancy and growth plan](tenancy.md)
- **The caller owns the port.** Define a narrow interface beside the capability that needs it when the first integration warrants one. Concrete adapters implement those interfaces and own SQL, API mapping, credentials and provider-specific retries. Wire them at the entry point or in `bootstrap.py` once there is shared assembly.
- **State has one writer.** Each module owns its records and the transaction that protects them. Other modules use that module's commands or read contracts. One SQLite database is enough. Campaign revisions, viewer events, platform reports and learning findings have distinct identities and provenance.
- **Orchestration stays outside product rules.** A runner can ask the application to prepare a draft or analyze a report. Its session history and tool results carry no approval authority. The application checks the current grant and approved revision before any later provider write.

## Instruction-test workflow

1. The planner starts **Prepare next test** with an approved package and saved review reference. The server resolves the local operator and delegates to `AgentRuntime.start_next_test`.
2. The runtime stores the source reference in `agent_test_sources`, loads validated review evidence through `CampaignPerformance` and supplies it to recorded offline inference or explicitly selected OpenRouter drafting. OpenRouter chooses approved instruction component IDs, and application code assembles the neutral viewer wording.
3. At save, performance code rechecks the current package and correction. `CampaignDrafts` writes the new revision and instruction versions in the transaction that records the completed agent step.
4. Package construction reads the revision's instructions. The viewer verifies its content fingerprint against current media and persisted wording, and measurement keeps activity for that content separate from the original.
5. Starting an experiment freezes both approved contents and the observation protocol in `instruction_tests`. `instruction_test_assignments` binds a browser reference to an arm, visit and source in the transaction that records its first arrival.
6. The agent captures participant evidence, assesses both versions and saves a review with its completed step. Later events retain their own records. The planner compares current participant evidence and correction against the saved assessment to indicate when to review again.
7. OpenRouter settings and request state for both assessment and drafting live in the existing `agent_review_inference` table. The runtime reserves one request before dispatch, calls the adapter outside the write transaction and retains the receipt for recovery. Application code checks the current package and correction before accepting draft text, and retains inference provenance with the unapproved revision. Explicit operation IDs make repeated starts reuse the same run.
8. **Plan next step** calls `AgentRuntime.start_experiment_next_test`. `InstructionTests.next_test_context` verifies the latest assessment against current activity, correction and approved baseline. The existing preparation loop either records `waiting_for_evidence` without inference or saves a new revision through `InstructionTests.save_next_test` and the same draft writer. The new instruction-test record carries its source experiment and assessment references; earlier experiments and assignments remain independent.
9. **Save evidence snapshot** calls `InstructionTests.save_evidence_snapshot`. It checks the approved package and saves the cutoff, per-arm cohorts and the previous snapshot reference in one SQLite transaction. An operation ID replays its original snapshot. Each new snapshot is cumulative. Learning uses mature participant counts while rehearsals, authored fixtures, unknown sources and unresolved visits stay visible separately. Public viewer requests can mark rehearsals. Fixture assignments originate in the offline application path.

Move existing files in small changes when a feature needs their boundary. Preserve the documented CLI, browser API and existing SQLite drafts during extraction. Start with import and ownership checks during review. Introduce an automated architecture check when a concrete dependency rule needs enforcement.

## Main-model placement workflow

The composer calls `/api/agent/placements`. `AgentRuntime` delegates these runs to `PlacementAgent`, retaining the shared `agent_runs`, `agent_steps` and campaign command path. `planner_sessions` pins model and actor scope; `planner_jobs` pins the request, initial revision, catalog, routing policy and turn allowance. `planner_turns` reserves inference before dispatch and retains its receipt before executing the requested tool. Specialist results are reserved and cached on the job. Tool saves use a savepoint inside the transaction that records the result, preventing a recoverable tool error from committing a partial draft. The model chooses tools from observations rather than a fixed step index.

`CampaignConversations` owns `planner_messages` and the campaign binding on `planner_sessions`. User messages commit with run creation; terminal replies commit with the tool result and draft change. `/api/agent/conversations` lists the current operator's campaign conversations, and `/api/agent/conversation?id=…` returns a scoped transcript. The React `CampaignChat` displays stored text and revision references. The client sends `after_message` to reject stale views; replaying the same run ID returns the original run. Starting a new follow-up supersedes unfinished requests before taking its dialogue snapshot. The provider receives up to 20 recent messages within an 8 KB serialized budget. `openrouter_reviews.OpenRouterPlanner.prepare_turn` measures the complete wire JSON through the shared transport encoder and trims oldest dialogue/tool pairs to fit 32 KB before reservation; the current request is never clipped. Omission flags and retained message IDs accompany inference provenance. Full transcripts and tool results remain persisted. `replies.py` generates all accepted conversational wording from topics/reasons and current application facts; old unconstrained messages are retained as audit data and projected as needing verification. Progress still uses one HTTP step per request.

`PlacementDiscovery` owns registered catalogs and source checks. Discovery adds new video IDs while preserving existing saved placements when catalogs overlap. `CampaignDrafts` validates every selected fact and independent `source_reference` against scoped catalog entries before saving. The reference travels with the approved snapshot and export. Older catalog entries recover it from their immutable catalog snapshot; previous draft and approval snapshots stay unchanged. Existing experiment commands remain callable, and the planner passes its inherited main-model choice to their narrower inference adapters. The current specialist is simulated; live Jev and other budgeted routes remain separate integration work.

## Chat performance workflow

`review_performance` captures evidence through `CampaignPerformance.capture_review` outside the SQLite write lock. `save_review` rechecks the exact approved package and viewer aggregation using the caller's connection, then saves `campaign_performance_reviews` with the parent `agent_steps` row. `CampaignReviewTools` binds that review to the run and supplies the active correction and approved instruction components. `draft_permissions.py` maps the explicit per-request permission in `planner_jobs.snapshot` to the two write tools; the provider schema and application dispatcher both use it. `prepare_next_test` checks instruction-draft authority, media, activity, approval and correction, then calls the existing instruction writer with the model-selected component IDs. Its draft, step, outcome and assistant message commit together. Replayed inference reuses its stored receipt and rechecks authority. `planner_messages` retains the full outcome's review reference for the transcript evidence inspector; no new job framework or review database is introduced. For a running instruction experiment, `load_experiment_evidence` reads both assigned versions from the test bound to the run. `assess_instruction_experiment` saves a verified reason through `InstructionTests.save_review` with its tool step. The same `prepare_next_test` tool uses `InstructionTests.save_next_test` after verifying the latest saved assessment and the request’s draft permission. The transcript retains the captured assessment and dialogue context carries its ID.

## Foreground inference admission

`foreground_inference.py` owns request-local connection/selection proof, bounded
provider preflight and the shared agent HTTP field dispatcher. `inference_ledger.py`
owns atomic cost/call/rate/concurrency records and sanitized cost receipts. The
existing planner and structured run modules still own semantic receipts and
transactional product effects; `adapters/openrouter_reviews.py` remains the sole
completion transport. `CommandAccess` in `access.py` consumes command-bound permit
sets without network I/O at nested commit checks. See the
[foreground contract and checkpoints](openrouter-session-contract.md).
