# Source-code map

This map translates the [application architecture](architecture-plan.md) into code ownership and proposes where capabilities should grow.

## Current checkout

| Path | What it owns today |
| --- | --- |
| [placement-review/index.html](../placement-review/index.html) | Placement search and review UI, unsaved selections, draft conflict reconciliation and per-context export. |
| [scripts/placement_review.py](../scripts/placement_review.py) | The local server and developer CLI. It also contains YouTube search, sample search, catalog classification and the optional Jev call. |
| [scripts/campaign_drafts.py](../scripts/campaign_drafts.py) | Seed brief and rules, catalog registration, draft validation, revision checks, approval snapshots and immutable instruction versions. |
| [campaign_agent/agent/run.py](../campaign_agent/agent/run.py) | Recorded model inference, scoped preparation runs, tool dispatch and atomic step results. Prepares placement drafts and instruction tests. |
| [campaign_agent/performance.py](../campaign_agent/performance.py) | Sample reporting, saved reviews, buyer corrections and validation of the evidence supporting an instruction test. |
| [campaign_agent/instruction_tests.py](../campaign_agent/instruction_tests.py) | Approved test pairs, stable viewer assignments, experiment-specific evidence and saved agent assessments. |
| [campaign_agent/handoff.py](../campaign_agent/handoff.py) | Package content fingerprints, media references and the manual setup export. |
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
2. The runtime stores the source reference in `agent_test_sources`, loads validated review evidence through `CampaignPerformance` and supplies it to `ModelInference`. The authored offline response proposes revised instructions.
3. At save, performance code rechecks the current package and correction. `CampaignDrafts` writes the new revision and instruction versions in the transaction that records the completed agent step.
4. Package construction reads the revision's instructions. The viewer verifies its content fingerprint against current media and persisted wording, and measurement keeps activity for that content separate from the original.
5. Starting an experiment freezes both approved contents in `instruction_tests`. `instruction_test_assignments` binds a browser reference to an arm and visit in the transaction that records its first arrival.
6. The agent captures experiment evidence, assesses both versions and saves a review with its completed step. Later events retain their own records. The planner compares current evidence and correction against the saved assessment to indicate when to review again.

Move existing files in small changes when a feature needs their boundary. Preserve the documented CLI, browser API and existing SQLite drafts during extraction. Start with import and ownership checks during review. Introduce an automated architecture check when a concrete dependency rule needs enforcement.
