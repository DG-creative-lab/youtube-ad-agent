# Source-code map

This map translates the [application architecture](architecture-plan.md) into code ownership and proposes where capabilities should grow.

## Current checkout

| Path | What it owns today |
| --- | --- |
| [placement-review/index.html](../placement-review/index.html) | Placement search and review UI, unsaved selections, draft conflict reconciliation and per-context export. |
| [scripts/placement_review.py](../scripts/placement_review.py) | The local server and developer CLI. It also contains YouTube search, sample search, catalog classification and the optional Jev call. |
| [scripts/campaign_drafts.py](../scripts/campaign_drafts.py) | Seed brief and rules, catalog registration, draft validation, revision checks, approval snapshots and immutable instruction versions. |
| [campaign_agent/agent/planner.py](../campaign_agent/agent/planner.py) and [planning_models.py](../campaign_agent/agent/planning_models.py) | Main-model port, tool schemas, simulated profiles, OpenRouter tool calling, pinned conversations, request receipts and the bounded placement loop. |
| [campaign_agent/agent/conversations.py](../campaign_agent/agent/conversations.py) | Campaign-scoped persisted messages, transcript migration, history reads, follow-up ordering and supersession of unfinished conversation requests. |
| [campaign_agent/agent/replies.py](../campaign_agent/agent/replies.py) | Application-owned reply topics, clarification wording and safe projection of legacy unverified replies. |
| [campaign_agent/agent/review_tools.py](../campaign_agent/agent/review_tools.py) | Chat review/draft tools, application-resolved evidence references, readiness and freshness checks, grounded outcomes and instruction-component saves through existing commands. |
| [campaign_agent/placement_discovery.py](../campaign_agent/placement_discovery.py) | Immutable scoped catalogs, automatic classifier port, simulated specialist receipts and evidence-bound placement saves. |
| [campaign_agent/agent/run.py](../campaign_agent/agent/run.py) | Recorded model inference, scoped preparation runs, tool dispatch and atomic step results. Prepares placement drafts and instruction tests. |
| [campaign_agent/adapters/openrouter_reviews.py](../campaign_agent/adapters/openrouter_reviews.py) and [openrouter_instructions.py](../campaign_agent/adapters/openrouter_instructions.py) | Shared bounded OpenRouter transport, structured assessment and instruction-drafting prompts, response parsing and sanitized errors. |
| [campaign_agent/performance.py](../campaign_agent/performance.py) | Sample reporting, saved reviews, buyer corrections and validation of the evidence supporting an instruction test. |
| [campaign_agent/creatives.py](../campaign_agent/creatives.py) | Published examples and the approved neutral instruction components used to validate and assemble provider proposals. |
| [campaign_agent/instruction_tests.py](../campaign_agent/instruction_tests.py) | Approved test pairs, stable viewer assignments, experiment-specific evidence and saved agent assessments. |
| [campaign_agent/handoff.py](../campaign_agent/handoff.py) | Package content fingerprints, media references and the manual setup export. |
| [campaign_agent/campaign_setup.py](../campaign_agent/campaign_setup.py) | Setup validation, exact-plan approval, one creation attempt and provider read-back. The simulated adapter stores its campaign separately from the approved plan. |
| [campaign_agent/measurement.py](../campaign_agent/measurement.py) | Scoped viewer activity and completion attributed to exact comparison content. |
| [web/planner/src/](../web/planner/src/) and [web/viewer/](../web/viewer/) | React campaign workspace and the public comparison experience. |
| [tests/](../tests/) and [examples/](../examples/) | Offline behavior tests, authored catalogs and synthetic evidence. Private state and credentials live under the ignored `.local/` directory. |

The browser calls the loopback API, which delegates to the owning application commands. Agent tools use those same commands. SQLite retains campaign revisions, approvals, reviews, corrections, viewer activity and agent progress. Live YouTube search results stay in the browser session.

## Where the code should grow

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
5. Starting an experiment freezes both approved contents in `instruction_tests`. `instruction_test_assignments` binds a browser reference to an arm and visit in the transaction that records its first arrival.
6. The agent captures experiment evidence, assesses both versions and saves a review with its completed step. Later events retain their own records. The planner compares current evidence and correction against the saved assessment to indicate when to review again.
7. OpenRouter settings and request state for both assessment and drafting live in the existing `agent_review_inference` table. The runtime reserves one request before dispatch, calls the adapter outside the write transaction and retains the receipt for recovery. Application code checks the current package and correction before accepting draft text, and retains inference provenance with the unapproved revision. Explicit operation IDs make repeated starts reuse the same run.
8. **Plan next step** calls `AgentRuntime.start_experiment_next_test`. `InstructionTests.next_test_context` verifies the latest assessment against current activity, correction and approved baseline. The existing preparation loop either records `waiting_for_evidence` without inference or saves a new revision through `InstructionTests.save_next_test` and the same draft writer. The new instruction-test record carries its source experiment and assessment references; earlier experiments and assignments remain independent.

Move existing files in small changes when a feature needs their boundary. Preserve the documented CLI, browser API and existing SQLite drafts during extraction. Start with import and ownership checks during review. Introduce an automated architecture check when a concrete dependency rule needs enforcement.

## Main-model placement workflow

The composer calls `/api/agent/placements`. `AgentRuntime` delegates these runs to `PlacementAgent`, retaining the shared `agent_runs`, `agent_steps` and campaign command path. `planner_sessions` pins model and actor scope; `planner_jobs` pins the request, initial revision, catalog, routing policy and turn allowance. `planner_turns` reserves inference before dispatch and retains its receipt before executing the requested tool. Specialist results are reserved and cached on the job. Tool saves use a savepoint inside the transaction that records the result, preventing a recoverable tool error from committing a partial draft. The model chooses tools from observations rather than a fixed step index.

`CampaignConversations` owns `planner_messages` and the campaign binding on `planner_sessions`. User messages commit with run creation; terminal replies commit with the tool result and draft change. `/api/agent/conversations` lists the current operator's campaign conversations, and `/api/agent/conversation?id=…` returns a scoped transcript. The React `CampaignChat` displays stored text and revision references. The client sends `after_message` to reject stale views; replaying the same run ID returns the original run. Starting a new follow-up supersedes unfinished requests before taking its dialogue snapshot. The provider receives up to 20 recent messages within an 8 KB serialized budget. `OpenRouterPlanner.prepare_turn` measures the complete wire JSON through the shared transport encoder and trims oldest dialogue/tool pairs to fit 32 KB before reservation; the current request is never clipped. Omission flags and retained message IDs accompany inference provenance. Full transcripts and tool results remain persisted. `replies.py` generates all accepted conversational wording from topics/reasons and current application facts; old unconstrained messages are retained as audit data and projected as needing verification. Progress still uses one HTTP step per request.

`PlacementDiscovery` owns registered catalogs and source checks. Discovery adds new video IDs while preserving existing saved placements when catalogs overlap. `CampaignDrafts` validates every selected fact and independent `source_reference` against scoped catalog entries before saving. The reference travels with the approved snapshot and export. Older catalog entries recover it from their immutable catalog snapshot; previous draft and approval snapshots stay unchanged. Existing experiment commands remain callable, and the planner passes its inherited main-model choice to their narrower inference adapters. The current specialist is simulated; live Jev and other budgeted routes remain separate integration work.

## Chat performance workflow

`review_performance` captures evidence through `CampaignPerformance.capture_review` outside the SQLite write lock. `save_review` rechecks the exact approved package and viewer aggregation using the caller's connection, then saves `campaign_performance_reviews` with the parent `agent_steps` row. `CampaignReviewTools` binds that review to the run and supplies the active correction and approved instruction components. `draft_permissions.py` maps the explicit per-request permission in `planner_jobs.snapshot` to the two write tools; the provider schema and application dispatcher both use it. `prepare_next_test` checks instruction-draft authority, media, activity, approval and correction, then calls the existing instruction writer with the model-selected component IDs. Its draft, step, outcome and assistant message commit together. Replayed inference reuses its stored receipt and rechecks authority. `planner_messages` retains the full outcome's review reference for the transcript evidence inspector; no new job framework or review database is introduced. For a running instruction experiment, `load_experiment_evidence` reads both assigned versions from the test bound to the run. `assess_instruction_experiment` saves a verified reason through `InstructionTests.save_review` with its tool step. The same `prepare_next_test` tool uses `InstructionTests.save_next_test` after verifying the latest saved assessment and the request’s draft permission. The transcript retains the captured assessment and dialogue context carries its ID.
