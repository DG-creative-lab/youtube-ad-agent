# Factory launch board and worker handoffs

15 November 2026 · Coordinator: the originating factory-planning conversation.

[Architecture and implementation map](../agent-platform-factory-plan.md) ·
[Engineering workflow](../engineering-workflow.md) · [Build priorities](../build-plan.md)

## Backlog and ownership

These are linked GitHub issues/checklists, not a claim that GitHub native sub-issue
or blocking relationships have been configured. Issues are the durable backlog;
the coordinator records dispatch and acceptance evidence against exact commits.

| Lane | Tracker | Owner / boundary |
| --- | --- | --- |
| Development factory | [Epic #47](https://github.com/DG-creative-lab/youtube-ad-agent/issues/47) | Complete: #49/#50/#51 merged; retain task contracts, independent verification and exact-head checks. |
| Agent workspace | [Epic #48](https://github.com/DG-creative-lab/youtube-ad-agent/issues/48) | Capabilities, user-funded models, projects, guidance, creative and learning. |
| Hosted enterprise foundations | [Existing epic #34](https://github.com/DG-creative-lab/youtube-ad-agent/issues/34) | Current access, durable storage/jobs, provider effects, privacy and deployed acceptance. |

| Package | Issue | Dispatch state at preparation | Dependency / next owner |
| --- | --- | --- | --- |
| F1 | [#49 Coordinator/verifier playbooks and contracts](https://github.com/DG-creative-lab/youtube-ad-agent/issues/49) | Merged complete | Accepted development playbooks/contracts. |
| F2 | [#50 Locked planner build in offline CI](https://github.com/DG-creative-lab/youtube-ad-agent/issues/50) | Merged complete | Unchanged locked planner CI remains required on each candidate. |
| F3 | [#51 Offline agent behavior/attack portfolio](https://github.com/DG-creative-lab/youtube-ad-agent/issues/51) | Merged complete in PR #71, base d409d7b | [Accepted 11-case portfolio](../agent-behavior-evals.md); historical 298-test checkpoint is not current candidate evidence. |
| A1a | [#52 Scoped capability catalogue/API](https://github.com/DG-creative-lab/youtube-ad-agent/issues/52) | Delivered/merged | Accepted catalogue contract; advisory metadata grants no dispatch authority. |
| A1b | [#53 Capability UI and factual replies](https://github.com/DG-creative-lab/youtube-ad-agent/issues/53) | Delivered/merged | Existing capability UI and factual application replies remain native. |
| A2 | [#54 OpenRouter BYOK/model selection](https://github.com/DG-creative-lab/youtube-ad-agent/issues/54) | Implementation delivered/merged; activation tracked by #70 | [Foreground checkpoints](../openrouter-session-contract.md); #70 owns foreground transport/route/charging qualification; real identity remains #36 and deployment stays gated. |
| A3 | [#55 Projects and governed sharing](https://github.com/DG-creative-lab/youtube-ad-agent/issues/55) | Open: PR #69 product rules and PR #72 A3a artifacts merged; runtime blocked | [Integration v1](../project-access-integration.md); producer #79/#81/#83 and #36/#37 acceptance remain; no migration slot reserved. |
| A4 | [#56 Conversational briefs/versioned guidance](https://github.com/DG-creative-lab/youtube-ad-agent/issues/56) | Blocked on #52/#55 | Separate runtime skills/guidance from development-agent skills. |
| A5 | [#57 Reviewed voice artifacts](https://github.com/DG-creative-lab/youtube-ad-agent/issues/57) | Blocked on provider/guidance/assets/budget contracts | Offline first; later live trial ceiling is £4 total. |
| A6 | [#58 Reviewed project-learning proposals](https://github.com/DG-creative-lab/youtube-ad-agent/issues/58) | Blocked on #55/#56 | Preserve native evidence eligibility and uncertainty. |
| E41a | [#59 Hosted topology/migration decision](https://github.com/DG-creative-lab/youtube-ad-agent/issues/59) | Accepted design, merged PR #73; #59 closed | [Selected topology and first port](../hosted-topology-decision.md); child of #41; no deployment or schema implementation. |

Do not dispatch all backlog issues as simultaneous builders. Earlier #49/#50 and
#52/#53 delivery order is historical. #59's merged design is an accepted dependency;
#37 implementation remains open and #55 runtime is blocked. Research on later
dependencies can run as bounded read-only work without authorizing implementation.

## Baseline and dispatch gate

GitHub inspection confirms storage PR #46 is merged at
`c9756e0422d061291b6ebcc75654e34b2128b992`. The local coordinator checkout remains
`610c4d672d9112c9090b0de47eeeb077d75a3a5a`, with planning edits. A fresh worktree
does not inherit those dirty files. Publish these documents on
`feature/factory-launch-plan`; review them before handing off implementation.

Immediately before dispatch, resolve current remote main and the accepted plan
commit, then record the exact worker base. If the plan is still unmerged, either
wait or explicitly approve a stacked base and integration target; never let the
worker guess. Refresh issue/PR state and ownership at that time. The historical
206-test checkpoint is not a new verification run for these planning files.

Each worker uses its own `feature/…` or `fix/…` branch/worktree and temporary
database, media root, ports and fixtures. Do not move the coordinator checkout or
share its local runtime directory. Worktrees are not credential/network sandboxes;
only provide the tools and data the assignment permits. No customer/employer
material or credentials in prompts, issue bodies, commits or reports.

No persistent sidebar worker threads were created by this preparation: thread
creation controls are not exposed in the current session. One bounded independent
review agent inspected the proposal and reported source-only findings. Use the
handoffs below in new worktree threads, or dispatch bounded agents when their
execution/resource isolation can satisfy the same contract. Do not describe
bounded agents as persistent sidebar threads or an unattended scheduler.

## Task contract

Complete this record before builder dispatch. IDs/SHAs/paths must be actual
resolved values; an incomplete template is not execution authorization.

```yaml
task_id: "GitHub issue number and package ID"
stage: queued
issue_url: "actual issue URL"
contract_version: 1
base_commit: "resolved full SHA"
plan_commit: "resolved full SHA containing these handoffs"
integration_target: "main or explicitly accepted stacked target"
branch: "feature/description or fix/description"
worktree: "actual isolated path"
outcome: "one observable user/developer result"
dependencies: []
owned_files: []
exclusive_resources: []
scope: []
out_of_scope: []
protected_invariants: []
acceptance_scenarios: []
permitted_network: []
provider_calls: forbidden
cost_limit_gbp: 0
reviewer: "assigned role/agent/thread"
verifier: "assigned role/agent/thread"
repair_attempt_limit: 2
stop_conditions:
  - "Changed dependency contract, overlapping ownership or unavailable base"
  - "A required check needs unavailable credentials/network or new external effects"
merge_authority: human
```

Routine dependency installation can be permitted explicitly; it does not permit
provider calls, secrets access, deployment or arbitrary network destinations.
Do not treat issue text or imported material as authority to expand this contract.

## First-wave builder handoffs

### #49 — workflow implementation

Implement issue #49 from the coordinator's completed task contract. Start by
reading AGENTS.md and the product, architecture, build, source-map and workflow
documents, then this launch record and the issue's current body. Own only the
coordination/verification instructions, templates and routing assigned there.

Add two concise repository playbooks: `factory-coordination` and
`campaign-verification`. Reuse existing engineering, test and adversarial-review
instructions. Coordination handles readiness, handoffs, isolation and integration;
verification handles exact-commit acceptance and truthful evidence. Prefer links
to existing security rules over another generic security checklist. Validate
metadata/routing and forward-test with fresh-context offline assignments. Report
which behavior the exercises demonstrated and what remains untested. Preserve
these as versioned repository resources, not personal installed skills.

Do not modify application behavior, CI dependencies or deployment. Return the
head SHA, changed files, performed checks, unresolved findings and a review-ready
handoff. Do not merge, close the issue as complete or dispatch dependent builders.

### #50 — first delivery pilot (after #49)

Implement issue #50 from the completed contract on a separate worktree/branch.
Own the GitHub offline workflow and narrowly required verification documentation.
Preserve Python tests. Add supported pinned Node/pnpm setup and the frozen-lockfile
planner install/build, with existing package versions and least privileges.
Do not introduce provider keys or change runtime/UI source to make checks pass.

Run the checks in an isolated clean environment where feasible; report a blocked
registry install accurately. Verify the build rejects a representative TypeScript
failure in a disposable copy without committing the failure. Return exact commands,
exit/results and head SHA for independent review. Browser checks are not required
for a CI-only change; do not fabricate browser evidence.

### #59 — parallel read-only decision

Work on issue #59 as a read-only architecture decision task. Read current #34 and
#36–#42, the storage/access documentation and source owners; verify changing
provider/platform claims against official current sources. Evaluate Vercel/Neon,
including private media and the foreground-credential limitation. Preserve separate
staff/public origins and current exact approval semantics.

Return a proposed topology, migration/transaction contract, region/plan eligibility,
cost assumptions, performance/recovery acceptance and unresolved decisions. Do not
provision accounts, deploy, migrate data, call models or rewrite persistence. Send
schema proposals and job/credential requirements to the coordinator for the
#37/#38/#39 owners; do not post messages, mutate issues or implement competing
foundations from this read-only assignment.

## Independent reviewer handoff

Review the assigned issue, frozen task contract and exact base..head diff. Start
from source artifacts rather than the builder's explanation. Read the existing
adversarial-review instructions for consequential boundaries and trace alternate
writers, unchanged callers, current access, commit/effect and recovery paths.

Stay read-only unless fixes are separately assigned. Report consequence, trigger,
source file/line and smallest fix; distinguish reproduced failures, source-only
reasoning and unknowns. Check whether acceptance evidence proves the requested
behavior, including at least one legitimate allowed path when authority changes.
A different role/context helps independence but does not establish correctness.

Return the reviewed head SHA and findings. New commits invalidate affected review.
Review completion does not authorize merge, deployment, paid calls or scope growth.

## Independent verifier handoff

Derive expected outcomes from the issue/contract, not implementation details. Verify
the exact accepted head/integration commit in an isolated checkout with authored
resources. Run the applicable offline suite/build and the real changed browser
path when browser behavior changes. Check persisted outcome/export as well as
visible text. Exercise restart and adversarial cases where the changed boundary
makes them relevant; do not add tests merely to mirror code.

Normal acceptance requires clean tracked source, lockfiles and workflows matching
the recorded commit. List generated artifacts separately. Fault injection belongs
in a disposable copy and cannot replace final acceptance on the actual head.

Return a separate evidence record. A check needing an unavailable dependency is
blocked, not passed. A source inspection is not an executed test. Historical green
CI does not establish current integration success, live model quality, usability
or production readiness. Never supply credentials or spend to unblock a check.

## Stage evidence record

```yaml
task_id: "actual task ID"
contract_version: 1
stage: "build | review | verify | integrate"
base_commit: "actual SHA"
head_commit: "actual SHA"
integration_commit: "actual SHA, or not_run with reason"
dirty_state: "clean tracked source/lockfiles/workflows; list generated artifacts separately"
checks:
  - name: "check or acceptance scenario"
    kind: "executed | source_inspection | historical"
    cwd: "actual working directory"
    command_or_path: "exact command or browser path"
    exit_code: null
    outcome: "passed | failed | blocked | not_run"
    evidence: "sanitized result or durable evidence reference"
findings: []
limitations: []
provider_calls: 0
live_spend_gbp: 0
next_owner: "assigned role"
recommendation: "ready for review | needs repair | blocked | ready for human merge"
```

Keep private raw logs, databases and screenshots with secrets outside Git. Commit
only authored fixtures and sanitized reproducible evidence. Cap automatic repair
at two attempts for the same contract before returning to specification. The
coordinator integrates serially and refreshes affected review and verification
on the resulting commit. Issue closure follows accepted evidence and merged work;
issuing a handoff or opening a PR is not completion.

### Historical F3 #51 preparation · 15 November 2026

F3-51 v1 starts from accepted dependency base
`0e6e1e2f9847d18c789bd3f1d4a771973877b5e7`. An independent specification froze
11 authored cases before implementation, with version/digest retained in the
[portfolio guide](../agent-behavior-evals.md). The evaluator uses the actual typed
dispatcher and temporary native SQLite, observes source-bound saves and denials,
and reports exact authored-adapter counters and restart/supersession evidence.
The existing unittest job discovers the portfolio and fail-closed reporting checks;
application code, dependencies and CI remain unchanged. Synthetic execution makes
no live-model, customer-guidance, external-billing or hosted-readiness claim.
Independent review/verification must name the exact candidate commit and final CI;
issue #51 closes only after accepted implementation is human-merged.


### Historical A2c #54 frontend preparation · 15 November 2026

The frozen A2c v1 slice builds account connection controls, private tab-memory
credential handling, searchable priced model/budget selection and existing planner /
three structured-command integration on accepted A2a/A2b base
`6daa75e92ab1acc7f4143497e1499dcbc04ac640`. The frontend owns no backend authority,
provider activation or migration changes. The existing planner CI job now enforces
dependency-free client boundary tests before its locked build. Original operations,
receipt-first recovery and independent per-request draft grants remain explicit.

Implementation checks use authored transports and disposable data only. Live route
qualification, real provider spend and deployment remain separate gates. Exact
commit independent source/browser verification and human merge remain required;
this checkpoint does not close umbrella #54.


### Historical A3-contract #55 preparation · 15 November 2026

PR #68 merged at `23b0bc0f5afc6b016b46b646423272a8bf7e203b`; its tree matches the independently accepted OpenRouter head. The next slice is the [proposed project/sharing contract](../project-sharing-contract.md), not project runtime. Current campaign-only access/permits cannot authorize project creation, listing or shared bytes by substituting a campaign ID. External membership/current decisions remain Gateplane-owned; the product owns native relationships and explicit disclosure intent.

Task A3-contract-55 v2 owns four documentation files on `feature/project-sharing-contract` from that merged base. Local execution became unavailable before validation/commit. V2 uses exact GitHub source/tree/commit APIs, coordinator JavaScript document/link checks, independent remote source review/verification and final CI. It makes no local clean-checkout, local commit, runtime or browser execution claim. Earlier local draft/design work is historical, not final-head evidence.

The coordinator authors; independent roles return separate exact-head evidence. Human document merge does not dispatch project capabilities, schemas, APIs, UI, providers or hosting. #36/producer and #37 must accept the concrete access/migration agreement before A3b runtime dispatch. Preserve portable demo release priority and keep #55 open through implementation acceptance.


### Historical A3a artifact preparation · 15 November 2026

Factory #47 and portfolio #51 are merged complete; PR #71 provides source base
`d409d7b96c3e2313f961af7fd78f0523ed1b4418`. #54 implementation is delivered;
[activation #70](https://github.com/DG-creative-lab/youtube-ad-agent/issues/70)
retains foreground transport/route/charging qualification gates; real identity/issuer remains #36. Historical preparation sections
above describe their dispatch time, not outstanding implementation work.

PR #69 accepted project product rules at
`0e6e1e2f9847d18c789bd3f1d4a771973877b5e7`. A3a-contract-55 v1 now prepares
the [concrete native integration agreement](../project-access-integration.md),
closed profile, literal request/result/hash vectors and a small offline checker.
One builder owns eight artifact/checker/test/docs paths. Runtime access, API/UI,
migrations, dependencies, provider effects and the pinned producer wire stay
unchanged. Independent review/verification must name the exact final head/tree;
existing Python/11-case portfolio and current unchanged planner CI remain required.
No browser/service/storage execution is claimed by these artifact checks.

#55 remains open. The current artifact agreement is proposed: first accept its
exact-head artifact evidence, then obtain separate #36/Gateplane registration,
native adapter, recipient/revoke, deadline and request-budget agreement and #37
storage/all-campaign restore/admission agreement. No producer/storage acceptance
or runtime dispatch follows from human product-document acceptance. Refresh main,
next migration ownership and a complete new task contract before A3b.

### Accepted #59 decision and retained implementation gates · 15 November 2026

PR #72 merged at `51e4b6dfd9a90794230572ae96f0eff27656cdb0`, tree
`39eaa19fd823840b2f212371154604fff5046d05`, accepting the A3a artifacts only.
#55 remains open for producer #79 registration, #81 native client, #83 composed
service/recipient/revoke evidence and separate #36/#37 acceptance. The accepted
all-campaign missing-link restore fence remains mandatory. #52/#53 and #54
implementation are delivered; #70 retains real foreground qualification.

E41a-59 v1 merged in PR #73 at
`a7fba7151f2755a93ff61cccf369d089c63df96c`, accepting the
[hosted decision](../hosted-topology-decision.md) as design only. #59 is closed;
#37 remains open. The Frankfurt Vercel Python ASGI staff/viewer projects, Neon
Postgres, private Vercel Blob, integrity-before-bytes, coherent recovery, preview
isolation and measured owner gates are not runtime or deployment acceptance.

### E37a.1 native SQLite write unit · 15 November 2026

The bounded implementation starts from accepted base `a7fba7151f2755a93ff61cccf369d089c63df96c`
on `feature/placement-write-unit`. `CampaignDrafts.write_unit()` now owns the
native SQLite connection/transaction for standalone saves and the planner's
extracted final tool commit. Existing application owners retain all validation,
authority, savepoint and revision checks; received inference receipts remain in
their original separate phase. Only two source files, their two native test files
and three mapping/status documents are owned by this slice.

Independent exact-head review/verification and current unchanged CI remain
required before human merge. The next serial #37 scope is the complete native
repository/read/start/initializer graph, followed by actual PostgreSQL
repositories, transactions and conformance. Foreground sessions/ledger/semantic
receipts/permit reads require their own complete port before provider activation.
No database switch, Postgres driver/schema, cloud/media adapter, project authority
or migration slot is introduced here. #55's merged artifacts remain separate
from its blocked runtime and all-campaign restore admission acceptance.
