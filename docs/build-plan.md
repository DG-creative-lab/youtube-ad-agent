# Campaign agent build plan

## Current product priority · 24 November 2026

The owner paused #124's separate learning exploration and agreed a product-first
sidebar, usable Knowledge base and real Learning review/intervention view. The
[workspace UX contract](workspace-ux-design.md) captures the user actions, scope,
source/authority boundaries, acceptance journeys and sequence under #48/#125.
The paused feature branch is not part of accepted main and must not be merged
incidentally with this design capture.

The first build should deliver scoped knowledge plus visible agent context as a
bounded #56 slice, with its functional navigation. Accept the current-workspace
storage/access/version contract first; do not bypass #55/#56 project release
dependencies. Campaign-level learning review follows using existing commands.
Project-wide promotion remains #58 after #55/#56; #57 retains its own gates. #123
continues to verify behavior and deployed revisions without introducing fixtures
as production results. Earlier chronological demo plans below are historical
where they prescribe #124 as the next customer-facing feature.

Track presentation in #133, the first Knowledge/context-used build in #134 and
campaign Learning review in #135. Keep their scope distinct from #58 promotion.

A common workspace with Direct Acquisition/iwoca is a future discovery item,
tracked in #136, not an implementation dependency or repository/runtime merger
authorization.

## Current demo slice · #123 measurement context, 20 November 2026

Campaign advice needs the application's measurement contract to distinguish
existing viewer outcomes from proposed tracking integrations. The current slice
supplies versioned measurement definitions in the first live planner context and
both retained and typed `read_campaign` results. It describes comparison completion,
the arrival denominator, content/cohort attribution and unsupported viewer analytics
without querying visits or claiming observed results. Prompt v9 guides use of
those facts; existing commands still own report reads and authority. Tests bind
the definitions to real event/count behavior and check that grading criteria never
enter provider requests. The frozen capability corpus/rubric stay unchanged;
future rubric calibration and another authorized live sample remain separate work.

Resumption keeps the run's saved planner version. Historical v7/v8 prompts,
schemas and context projections remain available; only v9 receives measurement
facts in the initial context or campaign-read result. Unsupported versions stop
before reservation/dispatch. A paid v8 ledger receipt interrupted before the
planner receipt write recovers through the normal hash checks without a key,
metadata request or another completion call. Authored historical wire fixtures
and the HTTP recovery regression protect this upgrade boundary.

Non-foreground OpenRouter planner admission also accepts supported v7/v8 pins
under the current model, limit, credential and browser checks. The availability
comparison does not rewrite saved settings; rendered requests and receipts retain
the old pin. The native planner regression pauses a v8 run after its first tool,
reopens it with the v9 adapter default and verifies the next inference completes.

PR #131 delivered the isolated live capability runner and human grading workflow.
The preceding harness slice exposes
scoped current campaign context IDs, makes classification errors actionable, and
guides advice to answer the request without unnecessary classification or another
permission question. Planner prompt v8 retains the application authority checks.
The [prepared Mini/Terra comparison](live-capability-benchmark.md#prepared-mini--terra-comparison--20-november-2026)
uses the same frozen tasks/rubric and corrected source for both models. Offline
regressions and bounded route qualification precede separately authorized live
sampling; neither a public model listing nor a claimed credit allowance proves
live compatibility, quality or paid-account entitlement.

PR #130 delivered the deterministic gate and CI evidence. The next slice is the
[live capability benchmark](live-capability-benchmark.md): 20 frozen campaign tasks,
repeatable isolated foreground trials, explicit whole-batch authorization and
separate automated outcome checks and human quality grades. CI validates the
contract without live calls; real samples and rubric calibration retain their
credential, budget and review requirements.

PR #129 delivered live OpenRouter configuration, route qualification and safe
execution diagnostics. The [deterministic demo eval gate](demo-release-evals.md)
retains the 11 frozen behavior cases, reports the 312 paired policy simulations
with the keep/no-change baseline, checks learning-reuse safety, and publishes
sanitized revision-bound evidence in CI. Hosted smoke and live model quality stay
separate gates. This does not close the wider eval or functional MVP roadmap.

After the functional MVP, implement the [owner's next UI direction](design-direction.md#next-ui-build--owner-direction-19-november-2026):
softer controls, dark mode, collapsible navigation, artefact-only auxiliary panels
and inline expandable activity for the single campaign agent. Keep this redesign
separate from the eval runner and existing runtime/authority contracts.

The staged map includes #87 foundation contracts/offline injection before #86;
#86 owns every pilot native participant and its minimal factory, with #87 final
external adoption and #88 consolidation afterward.

## Current architecture milestone · #88 startup and entrypoints

Local demo, hosted staff/public and authored fixtures explicitly prepare the
native SQLite store before serving commands. The local HTTP and placement CLI
launchers use the same placement composition. Hosted requests bind the current
staff principal and campaign without rerunning schema initialization. The
standalone sandbox command retains its opt-in configuration and delegates to its
own composition root.

The runtime still qualifies only the native foreground adapters selected by its
bootstrap. Storage connection and repository ownership for retained commands
continues under [#37](native-storage-migration.md).

### Delivered #86 local placement pilot

The next build targets the whole accepted local authored simulated-placement pilot,
not another single participant. `bootstrap/planner.py:create_local_planner` performs
explicit native startup/admission and constructs the existing runtime without
constructor DDL. Its router selects typed placement start/follow-up, read,
classification/reservation, commit and receipt recovery through the actual local UI
and shared dispatcher. The context participant reads real approvals, saved reviews,
corrections and started tests; logical media facts and original command permits
retain their full scope and preimage checks. Other tools and foreground workflows
remain supported on the original native store through their retained paths.

#86 was accepted by human merge of [PR #104](https://github.com/DG-creative-lab/youtube-ad-agent/pull/104).
The [residual native graph](native-storage-migration.md) assigns the remaining
families to #37/#87/#88 and records the compatibility schema copies. No backend
switch, PostgreSQL acceptance, provider activation or hosted release follows.

### Delivered planner storage lifecycle

Catalogue read/save now require typed repositories throughout; the application
module has no remaining SQL or native connection path. All planner catalogue
reads borrow their existing transaction, including start/classification/tool reads.
Planner options/run-existence reads use the snapshot reader. Run/planner schema
initialization and local legacy backfill are explicit native adapter operations.
Each model/classifier receive/fail write uses a core-owned receipt port and its own
adapter transaction, preserving separately durable receipts before tool commit.

The receipt port changes storage ownership, not inference retry or failure policy.
Schemas, raw serialized data and local-only legacy identities are preserved. The
reservation/start/preflight/access graph, remaining tool commits and composition
still retain legacy boundaries; this does not complete #86 or select another backend.

### Delivered placement commit

The non-foreground placement save now uses a typed write unit. Scoped run/session
and revision checks, catalogue/provenance reads, draft append, step, run outcome
and assistant reply share one transaction. The adapter owns BEGIN, savepoint,
commit, rollback and close. Model receipts remain separately durable before tool
commit, so interrupted saves recover without repeating inference/classification.
One application placement-save policy serves both the adopted and legacy paths.

Foreground-origin commits (including detached receipt recovery), other tools,
startup/reservation phases and existing access/permit coupling retain their legacy
outer boundaries. Native failure mappings are preserved. This is the complete local
placement *commit*, not acceptance of the whole #86 pilot or a backend switch.

### Delivered planner read snapshot

The planner run projection now uses a typed scoped reader and an adapter-owned
snapshot. Run status, saved outcome, turns and joined tool history observe the same
committed view even if another worker finishes a turn during the read. Both current
access checks and all four ownership dimensions are retained before detail reads.
History rendering in write paths borrows the existing transaction's repository.

The shared planner/draft/access write unit and native error mapping remain legacy
boundaries for the complete #86 pilot. No alternate runtime backend is selected.

### Delivered conversation participant

Following PR #99's catalogue foundation, conversation commands now consume typed
repositories. Planner begin/session/finish borrow that repository from the exact
existing planner transaction, including running-run reads and superseded
status/outcome/reply writes. Conversation schema initialization and transcript
adoption remain atomic in the SQLite adapter; application code retains dialogue,
access and reply policy. Standalone transcript reads use adapter-owned snapshots.

This adopts one participant, not the full placement UOW. The planner/draft/access
transaction owners and native error mapping remain legacy boundaries until the
whole unit is adopted. No alternate runtime backend is selected. #86 stays open.

### Delivered catalogue foundation

#85 closed under its revised scope after PR #97. PR #98 supplied the first #87
planning/classifier contracts and supplied-model seam; broader provider inversion
and composition remain open.

The first #86 adoption is catalogue registration/listing through typed core-owned
records and read/write units. The SQLite adapter owns these connections, snapshot
reads, commit/rollback and catalogue initialization. Registration commits the
catalogue and its provenance entries together, with an explicit application commit.
Native catalogue IDs, raw snapshots and duplicate-registration behavior remain.

This is a preparatory adoption, not completion of the placement pilot. Planner
catalogue read/save still borrow the existing native transaction; campaign,
conversation, review/access and run/step participants must join the later complete
UOW. Runtime composition keeps catalogue operations on that same SQLite path;
alternate storage is exercised only against isolated registration/listing commands.
One unused SQLite import exception retires; raw-handle/SQL use still needs review
and migration even when an import disappears. #86 remains open.

### Delivered #85 foundations

Initial #84 was human-merged in [PR #91](https://github.com/DG-creative-lab/youtube-ad-agent/pull/91)
at `9fabf358b30cbc794455c1da78440043593d1497`. The small static Python import
checker is the accepted guard; deeper effect/authority properties remain test and
review responsibilities. #84 stays open through its later strict-zero milestone.

The first bounded #85 slice gives shared scope values, campaign/inference errors
and video-ID syntax pure domain owners. Runtime consumers import those owners;
legacy paths reexport the same objects for compatibility. The baseline shrinks
from 88 to 86 module edges, with no new exceptions. No SQL, transaction, provider,
identity-default or wire behavior moves in this slice. Relocated classes acquire
new Python module metadata; application JSON/error/fingerprint semantics remain.

The subsequent #85 policy slice moves the unchanged instruction-test decision calculations into the domain package. The old module remains a compatibility reexport; monkeypatches of globals on that wrapper do not change the implementation globals.

CampaignDrafts now has an application owner; the script remains an inward compatibility
wrapper. Its native storage, defaults and authority checks remain for later inversion.
#85's broader module-map sweep was deferred by the agreed scope reduction;
remaining baseline entries are visible, not declared completed. #87
foundation contracts/offline injection precede #86 whole pilot-native UOW; #87
external and #88 composition follow. #37's residual named native graph, #84 import
strict zero and #89 broader conformance retain their gates. PostgreSQL/cloud and
provider/identity activation remain separate. Each PR requires independent review,
verification, current CI and human merge.

Updated 15 November 2026 · [Product brief](product-brief.md) · [Architecture](architecture-plan.md) · [Design direction](design-direction.md) · [Engineering workflow](engineering-workflow.md)

## Current factory decision checkpoint · 15 November 2026

#52 capability catalogue/API and #53 capability UI are delivered; #54 foreground
BYOK implementation is delivered with real activation retained by #70. PR #69
accepted project product rules and PR #72 merged the A3a #55 artifact agreement;
#55 runtime remains blocked on producer #79 registration, #81 native client,
#83 composed service/recipient/revoke evidence and separate #36/#37 agreement.
No project migration, endpoint or new authority follows from artifact acceptance.

#59 now supplies the [proposed hosted topology and bounded migration contract](hosted-topology-decision.md):
two Frankfurt Vercel Python ASGI origins, Neon Postgres and private Vercel Blob.
Human acceptance selects this reference; it deploys nothing. Preserve local
SQLite/private files and the zero-cost demo. #37's first native placement unit of
work, complete reader/writer port, all-campaign restore fence and DB/blob drills
precede composition. #40/#41/#42 own privacy, eligible plan/budget, ingress and
measured deployed acceptance; #38 unattended execution remains deferred. The
historical checkpoints below retain their original dates and evidence.

## Application deliverable

Build one local workflow for the ElevenLabs Text to Speech brief. A buyer gives the agent a goal and gets a saved campaign package for video editing and audiobook production tutorials. Each group has proposed placements, a playable cut and a link to its comparison demo. The agent chooses the steps and prepares the package. The buyer reviews the package once for manual handoff. After trying the viewer experience, the buyer sees a review based on recorded local activity and labelled sample delivery. The agent proposes a follow-up test from that evidence and uses any relevant buyer corrections already on file.

Target a complete walkthrough by **Friday 13 November**. Reserve **Monday 16 November** for a clean setup check and application packaging before the recorded **18:30 GMT** deadline. These are planning targets. Keep the build at zero cost across media, models, hosting and advertising.

## Release checkpoint · 11 November 2026

The local POC can turn a brief into two contextual placement groups and a versioned package, then take the buyer through approval, setup and review. The Google Ads test account verified paused creation and setup read-back. Real delivery, inventory coverage and lift still require an authorized pilot. The workspace and chat can recommend waiting, checking coverage or running a comparison from saved delivery and the buyer's correction. The existing instruction experiment can compare approved versions and prepare an eligible follow-up within the campaign. [Delivery review PR](https://github.com/DG-creative-lab/youtube-ad-agent/pull/22) · [Source map](source-map.md#instruction-test-workflow)

**Portable demo is the release slice.** The checkout includes playable media and authored wait and propose scenarios. In a clean local checkout with a fresh database and no provider credentials, both tagged viewer paths recorded one completion under the correct group. The planner reproduced the wait and propose recommendations while showing authored counts separately from local visits. Keep the walkthrough freeze and packaging ahead of new functionality. [Portable walkthrough](../README.md#portable-demo-walkthrough)

**The four Bayesian self-learning slices are merged.** Eligible cumulative snapshots feed the versioned policy. The buyer can save a supported finding and retrieve its wording, source counts and uncertainty in a compatible fresh brief after restart. The draft command rechecks evidence, scope, current rules, correction and permission before creating a revision for approval. The comparison records 69 Bayesian wins, 55 fixed-lift wins and 188 ties across 312 paired simulations. Both average utility scores are below the zero payoff for always keeping under this coverage mix. [GitHub epic #23](https://github.com/DG-creative-lab/youtube-ad-agent/issues/23) · [Comparison report](instruction-policy-comparison.md)

The release pass uses merged commit `7374914ca30e1c6dd0e68d74924e16f3f103b946` in an independent local Git clone. That clone began with no `.local/`, installed dependencies or planner build. Verification commands and the server ran with `env -i PATH="$PATH"`. Python 3.14.3, Node 25.8.2 and pnpm 10.33.0 were available on the verification machine. The offline dependency install reused 21 locked packages from the existing pnpm cache with zero downloads. An uncached installation needs access to the public package registry.

| Release check | Evidence |
| --- | --- |
| Offline application checks | All 156 tests passed in the fresh clone. |
| Planner dependencies and build | Frozen-lockfile offline installation and TypeScript/Vite build passed. |
| Policy comparison | The regenerated report matched the committed report byte for byte. Its application walkthrough reopened SQLite and prepared an unapproved wording draft. |
| Browser package flow | Chromium prepared and approved the two-context package, exported its handoff, and verified the paused simulated setup. |
| Playable comparisons | Real media playback completed both editing and audiobook takes. Each tagged group saved one arrival and one completion. Reload preserved the selected take. Both viewer layouts were inspected at 420 px width. |
| Delivery and restart | Restarting the same database retained the two 1/1 link counts. The authored wait state became the authored 4/1 editing proposal. Chat displayed the demo label and zero model turns. |
| Correction and experiment | Three eligible uncompleted editing visits triggered the sample review. A saved keep-takes correction led to an approved instruction test. Participant and rehearsal links saved separate unresolved cohorts, and the policy waited at the initial review point. |
| Finding reuse and authority | The separate authored 2/20 versus 18/20 example survived a server restart. A browser apply request without draft permission returned 403 and preserved the revision. The authorized action saved the exact tested wording in a new unapproved draft. |

Chromium also displayed the finding's counts, uncertainty and policy source together, with the final approval control visible. The learning example is prepared synthetic evidence, as labelled in the walkthrough. The 156-test suite supplies the stale, mismatched, superseded, retired and changed-correction rejection checks.

**The next slice is walkthrough freeze and packaging.** Use the [demo walkthrough](demo-walkthrough.md) for the recording and its source labels. The local demo uses a seeded operator. A hosted pilot needs staff identity, scoped client and brand access, and a hosted viewer. Live viewer lift and live model quality remain pilot questions. [Tenancy plan](tenancy.md)

## Enterprise preparation · 13 November 2026

The product tenant/workspace boundary is merged in [PR #43](https://github.com/DG-creative-lab/youtube-ad-agent/pull/43), main `95e5c49`, and #35 is closed. The offline staff/public access slice is merged in [PR #44](https://github.com/DG-creative-lab/youtube-ad-agent/pull/44), main `44ff3df`. #36 retains its real Gateplane/issuer gates. The active branch is `feature/hosted-persistence-assets` for the first [#37](https://github.com/DG-creative-lab/youtube-ad-agent/issues/37) slice.

**Offline #36 checkpoint:** all 194 tests pass; the planner build passed for the unchanged UI. Seventeen HTTP/contract cases cover scoped staff sessions, client/brand/campaign selection, buyer versus reviewer/admin permissions, draft mandates, request/response binding, expiry, delayed decisions, revocation/outage, logout, fixture bootstrap/restart and public link isolation. Expired/revoked publications now make export and setup validation return actionable conflicts; failed exports cannot save partial publication links. Setup reuse and creation also recheck the exact saved destinations, including after reservation immediately before dispatch; an unavailable destination releases the known-unsent reservation with zero provider calls. Validation cannot save a setup whose links expired during its provider check, and already dispatched operations retain receipt reconciliation. Renewal remains deferred. The in-app browser prepared client A's draft, denied buyer approval, accepted a separate reviewer’s approval/export and simulated paused setup, played a published comparison to completion and showed 1/1 correlated activity. Client B retained revision 1 with no client A conversation. No live identity, Gateplane or provider calls were used. [Walkthrough, source profile and activation gates](hosted-access-boundary.md)

**First #37 slice:** versioned ownership/asset migrations, immutable brand-scoped private media and whole-store backup/restore target one application worker with SQLite and private files on durable local storage. All 206 offline tests passed, including 12 storage cases for migration/history preservation, scoped HTTP bytes, concurrent revisions and committed-snapshot recovery. In the in-app browser the private store played both takes and saved one completion; a live SQLite backup plus 15 scoped blobs restored into a new directory, rejected the old session/public link, retained client A’s approved revision 2 after fresh sign-in and kept client B at revision 1. Original revision, approval, media and event records matched the restored rows byte for byte. The 14 November review fix verifies ownership primary keys, full uniqueness and required nullability before adopting same-column legacy tables or accepting a prior journal; incompatible stores remain unchanged for explicit reconciliation. Domain-specific legacy migrations remain with their owners; PostgreSQL/object storage, replicated hosting and operational release evidence are not activated. [Storage boundary and recovery commands](storage-recovery.md)

**Post-PR #45 verification · 14 November:** local `main` and `feature/hosted-persistence-assets` are reconciled to merged UI fix `3fe9c1c`. All 19 uncommitted files were preserved byte for byte during the fast-forward, before updating these verification notes. On the combined checkout all 206 offline tests passed with ResourceWarning reporting enabled and none emitted; the planner TypeScript/Vite build passed. A fresh authored two-client fixture exercised CLI status/migrate/backup/verify/restore, recovered 15 scoped blobs and identical domain/approval/fingerprint records, left its source unchanged, rejected old staff/public authority, served restored private media and retained client B at revision 1. No provider network calls were made. #37 remains open for the remaining hosted readiness work.

#36 remains open for the real private client, maintained OIDC callback/credential adapter and composed issuer/service evidence under Gateplane #81/#77/#78/#83. Real hosted identity/service selection, production storage deployment, unattended delegation and provider connections remain unactivated; the private asset adapter is exercised with authored fixtures only. The original portable demo remains available.

**Earlier #35 verification:**  all 177 offline tests and the planner build passed. The shared-store cases keep two clients and their brands separate across runs, conversations, catalogs, approvals, reports, visits and learning reuse after restart. A credential-free temporary server completed preparation, exact approval, simulated setup read-back and the authored wait recommendation in the in-app browser. After review, visits and activity freshness are also campaign-bound within a brand. Unbound customer history is excluded, and a known-unsent setup access failure releases the reservation for an explicit retry. Finding lookup and retirement also verify the source test’s campaign, so newer sibling findings cannot shadow or retire the current campaign’s result. The restarted browser path saved one campaign-specific comparison arrival and read it back in the performance review. The 312-run policy comparison retains its scores and decisions; only the instruction-test source fingerprint changed. No Gateplane or provider network calls were made.

The [enterprise epic #34](https://github.com/DG-creative-lab/youtube-ad-agent/issues/34) contains eight linked sub-issues, [#35–#42](tenancy.md#remaining-enterprise-work). After this product boundary, compose the accepted Gateplane access contract and hosted staff entrypoints in #36. Persistence/private media, durable jobs, provider authority, privacy/audit and operational release checks follow as explicit slices. Gateplane owns identity, membership and current access; this application retains ownership, evidence, exact approvals and provider effects. [Implemented model and remaining limits](tenancy.md)

## Milestones

| Target | Build | Acceptance check |
| --- | --- | --- |
| **1. Save a campaign · 6–9 Nov** | Start from the existing Python server and placement workspace. Add SQLite with a versioned seed brief, brand rules, campaign runs and immutable package revisions. Save placement selections against their context and source. Keep the existing search, catalog assignment and export paths working. Inventory the original scripts, footage and audio in parallel with this work. | Reopen the app after a restart. The brief revision, two context groups and selections are still there. Save an edit and confirm the previous revision still resolves. Existing placement export returns the same canonical video URLs. |
| **2. Make both viewer paths playable · 9–10 Nov** | Produce two short captioned cuts with owned or otherwise permitted assets. Build one comparison page with editing and audiobook content. Bind each CTA to a creative version and its matching example. Record arrival, playback start, playback finish and choice. | Follow both CTAs in a browser. Each opens the promised example. Finishing both takes and choosing one records one completion for that visit and example. Test refresh, a duplicate event, and a missing sample with a usable recovery path. |
| **3. Give the agent the workflow · 10–11 Nov** | Add a small in-process Python loop behind `AgentRuntime` and one Python tool dispatcher. Load approved context, gather permitted candidates, assemble a draft from available creative assets, validate it and request one package review. Use recorded model responses behind `ModelInference` for the offline run. Add OpenRouter behind that same port when permitted access is available. Add a handoff with objective, format, budget, dates, per-group placements, cut and CTA, plus a place to record actual settings and ad IDs. | Start with one buyer request. The run reaches a reviewable package without the buyer operating each tool. Approve and export it. Change a cut, destination or placement and verify that the new revision needs its own review. Interrupt a preparation job and reopen it at the last saved step. |
| **4. Review and propose a next test · 12 Nov** | Save delivery and viewer activity as observations. Compute completion per tagged arrival for each eligible creative version. Apply the saved buyer correction and tie the recommendation to the report that informed it. | Zero delivery leads to a wait, partial coverage to a check, and sufficient eligible activity can lead to a controlled demo test. Show the source of the recommendation and the active buyer correction. |
| **5. Verify and package · 13 and 16 Nov** | Freeze the working path on Friday. Run the walkthrough on a fresh local database, then use Monday for fixes, the recording and setup notes. Show where product approval ends and manual Google Ads setup begins. Include the actual results of any optional runtime or sandbox checks. | A reviewer can follow the documented setup, play both viewer paths and reproduce the two runs without credentials. Every part of the walkthrough identifies its evidence source and shows which capability was exercised. |
| **6. Reuse experiment evidence · after the portable demo** | Close the loop across campaigns with one Bayesian belief and a decision about one more batch of evidence. | A fresh, comparable brief shows why the agent proposes reusing the revised wording, collecting another batch or keeping the current version. Reproduce the decision and its source after a restart and compare it against the current rule offline. [Slice plan](#bayesian-self-learning)

## Bayesian self-learning

Start with the existing randomized viewer instruction test for the editing demo. Keep the two recordings, choice controls and other comparison content fixed. Use one outcome per eligible assigned visit. A completed comparison means the viewer finishes both takes and chooses one within the declared observation window. Client knowledge supplies constraints and hypotheses. Execution records establish which versions ran and whether a result applies. Delivery reports can motivate a test. Only eligible assigned outcomes from the instruction experiment update its belief.

1. **Admit evidence.** `InstructionTests` owns the pinned versions, assignments and counts. Before testing, pin the comparison, assignment unit, outcome, follow-up window and optional second batch size. Before saving learning, verify source, scope and maturity. Separate rehearsals and authored fixtures from observed participants. At each declared review point use the latest eligible cumulative snapshot for the experiment. Recompute from its original prior so retries, overlapping counts and late outcomes cannot add the same visit twice. Preserve earlier snapshots and record which one superseded them.
2. **Estimate the effect and choose a next step.** Use a versioned Beta–Bernoulli model with a weak prior per arm. Record counts, estimated lift and the posterior probability of exceeding a predeclared worthwhile effect. Give reuse and keep explicit payoffs for a worthwhile effect and for a smaller or harmful effect. For the one allowed extra batch, average the value of the best subsequent decision over predicted batch outcomes. Collect only if the gain over deciding now exceeds the batch cost and the batch fits the approved test limits. Otherwise choose the better of proposing reuse for review and keeping the current version. Declare the effect threshold, payoffs, collection cost and sample cap in advance.
3. **Carry the decision into a fresh brief.** `learning.py` and SQLite retain a versioned finding with source test, snapshot, model and decision references. Resolve client and brand from the current run, then match the viewing context, metric and applicable comparison versions. Show the buyer the counts, uncertainty, source and reason for the recommendation. A mismatched, superseded or retired finding is ineligible for reuse. Recheck the finding, current brand rules, applicable buyer correction and draft permission through the existing command path before saving an unapproved draft. The buyer retains approval authority.

### Offline comparison

The reproducible harness and fresh-brief check are available through `scripts/compare_instruction_policies.py`. The [saved report](instruction-policy-comparison.md) records 312 paired simulations, native assessment actions, ties and baseline wins under the frozen [specification](../examples/instruction-policy-comparison.json).

Give each policy the same authored outcome streams, evidence cutoffs and sample budget. Compare with the existing instruction-test assessment and report its native decisions. Also use a fixed sample and observed-lift rule as a baseline with the same reuse, collect and keep choices. Freeze the rules and costs before evaluating held-out scenarios with sparse, mature, delayed, absent and conflicting evidence. Report wrong reuse decisions against the known fixture effect, extra visits, decisions to wait or keep, and net decision value under the declared costs. Record ties and cases where the baseline wins. Fixture results measure behavior under the simulation assumptions. A separate pilot would measure viewer outcomes.

Use independently calculated posterior examples to check the math. With a uniform prior per arm, 6/20 versus 10/20 and 30/100 versus 50/100 have the same observed lift. The respective probabilities of exceeding a five-percentage-point improvement are about 82% and 98%. Test that more evidence can change the action, and that an expensive or exhausted extra batch can lead to keeping the current version. Use the real commands with temporary SQLite to verify replay and restart, refreshed and immature evidence, mismatched context, wrong brand and retired findings. Exercise one fresh-brief walkthrough to verify the evidence and recommendation are visible together. All checks run with fixtures and zero provider calls.

### GitHub epic

The four work items in the [Bayesian self-learning epic](https://github.com/DG-creative-lab/youtube-ad-agent/issues/23) are implemented through PRs #29–#32. The release pass checks the fresh-brief walkthrough and offline comparison together against merged main.

1. **Prepare eligible experiment evidence.** Expose versioned, mature counts and verify scope, provenance and replay through the experiment command. [Issue #24](https://github.com/DG-creative-lab/youtube-ad-agent/issues/24)
2. **Implement the belief update and next decision.** Calculate lift uncertainty and compare reuse, one extra batch and keeping the current wording under a declared budget. [Issue #25](https://github.com/DG-creative-lab/youtube-ad-agent/issues/25)
3. **Reuse a finding in a fresh brief.** Retrieve compatible findings, show their evidence in the planner and use existing draft and approval commands. [Issue #26](https://github.com/DG-creative-lab/youtube-ad-agent/issues/26)
4. **Compare policies offline.** Define the fixtures, baselines and scoring alongside the policy work. Save the results and exercise the end-to-end walkthrough. [Issue #27](https://github.com/DG-creative-lab/youtube-ad-agent/issues/27)

## Follow-up slices through the checkpoint

**Recommend a next test from saved delivery.** Align tagged visits and completions to the last seven completed Google Ads account dates. Exclude marked rehearsals and untimestamped visits from the decision. Use the current buyer correction and save the recommendation against the exact report. Verify wait, coverage check and one controlled comparison test with offline fixtures.

**Attribute viewer activity to the approved ad.** Bind each tagged link to a setup, creative and comparison before validation. Open the link only after destination read-back verifies the setup. Rehearse both comparisons with the simulator and show tagged arrivals and completions beside Google Ads delivery when available. Keep sample reviews and untagged visits separate.

**Review Google Ads delivery.** Bind a read-only report to the verified setup for the current approved package. Save ad-group metrics and video placement coverage, and expose the same review action in the workspace and chat. Keep configured targets, missing rows and observed zero totals distinct. Exercise complete, partial and empty reports with fixtures before querying the paused test campaign.

**Verify paused setup in Google Ads.** Use the sandbox CLI with a private creative binding for each approved group. Validate the full Demand Gen request and save it with its Google request ID. Present the saved setup ID for approval before creation. Read back both ad groups, their ads, video assets, destinations and positive video targets. After an uncertain create response, query the original campaign name. The workspace continues to use the simulator by default.

**Prepare and verify campaign setup.** Build a paused plan from the current approved package. Validate it in chat or the workspace and show the simulated account, budget and per-group targeting for explicit approval. Reserve one creation attempt for the exact validated plan. Read back the simulated campaign and its ad groups and ads, and keep the observation with the receipt. Exercise stale approval, duplicate submission, lost receipt and mismatched targeting. Use a separate test-account validation-only probe to check positive YouTube video and channel criteria.

**Review instruction experiments through chat.** Bind the running experiment to the current approved package when the request starts. Let the agent load assigned results, choose a bounded assessment reason and save the verified assessment. Show both versions, assigned counts and the current buyer correction in the transcript. When the assessment supports a follow-up and the request permits an instruction draft, use the shared experiment command to save an unapproved revision from the approved revised baseline. Wait with the existing versions when the assessment calls for more evidence. Check stale evidence, correction changes and replay through the dispatcher. Offline stays the default.

**Review and prepare through chat.** The main model can choose `review_performance` and `prepare_next_test` alongside placement tools. Resolve the current package, reporting scenario and review identity in application code. Require the exact approved package, capture labelled fictional delivery and recorded viewer activity, and commit the review with its tool step. Reuse the latest scenario saved for that package, otherwise the balanced authored sample; the model cannot choose a more favourable report. For an eligible comparison review with an active saved keep-takes correction, the model selects approved neutral instruction components and the existing command saves an unapproved draft with the reply and provenance in one transaction. Read-only review requests do not ask the simulated model to draft. Missing approval or a correction needs input; insufficient evidence or a delivery gap waits without a draft. Changed activity or correction requires refresh. A running instruction experiment requires an assessment of its assigned versions before another draft.

Acceptance: one chat request reaches a saved review and eligible instruction draft, or a clear blocked/waiting outcome. The buyer selects the allowed draft kind under **Changes**; default to Review only for each message and pin this choice with the run. Enforce it at both instruction and placement write boundaries, including fake-provider calls and received receipts from older runs with no grant. A retry cannot change the saved authority. Show the permission in Agent activity, review evidence in the transcript and the new unapproved revision alongside it. Retain recordings, placements, old approvals and captured evidence. Test replay, rollback, late media/correction/activity changes, forged references and supersession through the real dispatcher. Keep offline as default and use simulated OpenRouter responses before live verification. No nested harness, SSE or background worker is needed.

**Persisted campaign conversation.** Save buyer messages and terminal agent replies against their campaign, conversation, run, catalog and draft revision. Reopen saved conversations, answer clarifications and send follow-ups using the latest campaign state plus the last 20 saved messages. Keep the full transcript available for review. A reply can explain the campaign without changing it. Message/run identities make retries idempotent; a last-message check rejects stale tabs. A deliberate follow-up supersedes unfinished work in that conversation, and late results cannot commit. Keep offline simulation as the default. Existing HTTP requests advance one step at a time; SSE, token streaming and browser-independent background execution remain deferred.

Acceptance: clarify the context, answer in the same conversation, add only the requested placements from another catalog and ask for a read-only summary. Reload and reopen the conversation with the transcript intact. Retry a lost response without duplicating messages or draft changes. Reject cross-actor/campaign reads and stale-tab sends, and verify that a superseded run cannot save late. Use fake OpenRouter responses for dialogue context and receipt recovery; no live calls are needed.

Review safeguards: constrain replies and questions to application-rendered topics/reasons so model text cannot claim unperformed actions. Retain old unverified text as audit data while showing a verification notice. Bound the prior dialogue by both 20 messages and 8 KB of nested serialized JSON, then preflight the full provider request against 32 KB before reservation. Mark any dialogue or tool-history omission and retain the full transcript and application evidence.

**Conversation model and agent-led placements.** Add a request composer with a conversation-level model picker, persisted session configuration and a Python model/tool loop. Use two clearly labelled simulated model profiles and fake OpenRouter tool-call responses before live calls. The model may inspect the campaign or catalog, request classification, save a classified placement draft, or ask a necessary question. Route classification to the configured specialist automatically; keep exact operations in code. Pin catalog provenance, actor, revision, settings and aggregate limits. Recover from stored receipts and commit tool results with draft changes. Keep the existing walkthrough and experiment commands working, inheriting the main-model choice in the planner.

Acceptance: two catalog inputs produce different proposals; alternate simulated responses choose different legal tool orders; ambiguous rows remain unresolved; invented IDs and unauthorized tools cannot save; an edit or revoked grant blocks dispatch; duplicate starts and interrupted inference/tool commits create one result; exhaustion and unknown outcomes stop visibly. Verify the full composer-to-package path in the browser. Live Jev, paid models and paid activation remain separate work.

**Prepare next test** drafts revised instructions from a corrected review. After approval, **Run instruction test** pins the exact original and revised content and creates one viewer link. Persist each browser's random assignment with its visit so refreshes and restarts preserve its version and progress. Count only assigned visits in the experiment's results. **Review instruction test** runs the Python agent with authored offline responses to assess both versions and the current buyer correction, retaining the evidence used. Mark saved assessments when new activity or a correction warrants another review. The first rules use an illustrative minimum of 20 assigned visits per version before proposing another instruction change.

Instruction-test assessments support explicit OpenRouter mode, with offline as the default. A server allowlist permits selected `:free` models under a zero-price route filter, a one-request allowance and a 512-token output limit. Pin model settings and evidence on each run, reserve the allowance before dispatch, call outside SQLite write transactions and persist the provider receipt before accepting the agent step. Retain model, prompt, evidence and usage provenance with the assessment.

**Prepare next test** now offers separately enabled OpenRouter drafting under the same limits. Supply the saved review, current comparison and active keep-takes correction. The model selects approved playback, focus and neutral-choice component IDs; application code assembles and verifies the viewer wording, preserving both-take completion and excluding biased choices or new claims. Preserve the recordings and placements, and save an unapproved revision with inference provenance. Recheck package and correction before dispatch, response acceptance and save. Retry an interrupted start with its original operation ID and resume from the stored receipt. Rejected starts clear their placeholders; missing saved runs cannot become a demo preparation. Verify recovery, conflicts and rejected output with simulated responses before separately authorized live verification.

**Plan next step** connects the experiment assessment to another preparation run. Require the latest, verified assessment, unchanged captured activity and correction, and the exact current approved package. An insufficient-evidence or keep-collecting assessment records a terminal waiting outcome, with no draft and no drafting inference. An eligible assessment prepares another instruction-only revision using the current approved revised comparison as baseline, retaining its source experiment and assessment IDs. The new package requires approval and starts a distinct experiment; earlier evidence and assignments stay intact. Offline remains the default. Check retries, rollback, stale and superseded assessments, late viewer activity and provider-receipt recovery with authored fixtures.

## First implementation slice

Build this slice in Python and SQLite with the existing browser screen. React and TypeScript are for the fuller planner. Use the same backend API for both. The viewer comparison uses plain HTML, CSS and JavaScript.

1. Keep `scripts/placement_review.py serve` and `assign` as developer entry points. Extract the discovery, catalog classification and export behavior into callable functions only where the web or agent workflow needs them. Keep public YouTube search in its native review flow. Use independently supplied or fictional catalog material for model assignment.
2. Add the SQLite store and load one versioned brief with two contexts, approved claims and asset references. Store app state under `.local/`. The first browser change is **Save to campaign** in placement review. Persist the campaign and context, video IDs and provenance. Reload the saved selection in the planner.
3. Store each package revision as the exact brief and policy references, placement groups, creative versions, destinations and proposed launch settings. An approval points to that revision. Export the current approved package for handoff. A material edit requires a new approval, with the earlier package retained in history. Record actual provider bindings separately if a buyer supplies them.

Start the viewer path as soon as the creative and destination IDs exist. Use original recordings if suitable ElevenLabs output is unavailable within the zero-cost and rights constraints. Label the source of the audio shown in the application.

Before recording viewer events, bind the comparison example to the seeded client and brand on the backend. Use an opaque local visit ID and a stable event ID. Count one completion per visit and example version after two distinct takes finish and the viewer chooses one. Attribute activity to the example actually played and retain the original CTA version separately if the viewer switches contexts. [POC access checks](tenancy.md#compatibility-and-verification)

## First tool contracts

The agent and the web app enter through application commands. Resolve authority from the saved run. Bind reads and draft changes to its workspace, allowed sources and mandate. Use structured inputs and results throughout.

| Tool | Input and result | First adapter |
| --- | --- | --- |
| `load_campaign_context` | Run reference → approved knowledge versions, permitted assets and relevant memory references | SQLite |
| `propose_placements` | Context and allowed catalog reference → proposed IDs, source references and ambiguous items for review | Existing rules and fictional catalog. Jev stays opt-in subject to cost and permission. |
| `save_draft_package` | Run and expected draft revision plus the proposed package → a new revision or validation issues | SQLite and local asset checks |
| `get_campaign_delivery` | Bound campaign and date window → snapshot with source, reporting level, dates, coverage and status | Sample adapter first. Verified Google Ads test reads support a later read-only adapter. |
| `save_review_proposal` | Scoped observations and proposed hypothesis → a review record with evidence references | SQLite |

The buyer approves a package through the UI. The first runtime can read and prepare drafts. Let the agent choose tools from the allowed set and handle ordinary tool failures within its budget. Ask the buyer when a missing fact or choice materially affects the result, or when the next action requires approval. Save the job and its planned step before running tools. Commit each accepted draft change and its step outcome together, so a restart can reuse the result. A later activation command will check the saved grant and current policy before dispatch. Attach tool call status and evidence IDs to the run activity log.

## Release checks

- **Authority and recovery.** Exercise the actual dispatcher with fake adapters. A wrong workspace, stale revision, cancelled run or injected instruction cannot cause a write. A repeated accepted command returns its recorded result or resumes the same work. Tool responses and activity logs contain no credentials.
- **Placement evidence.** Preserve provenance and the distinction between candidate, selected and reported. Measure acceptance, reassignment and abstention on a permitted, human-labelled sample before claiming classification quality. Record whether a result came from local rules or a model.
- **Measurement.** Keep replayed model decisions, sample delivery and real local viewer events visibly labelled. Preserve report coverage and native grain. Show the numerator and denominator for viewer completion. An incomplete report can support a request for more evidence.
- **Product value.** The complete seed brief should reach package review from one buyer request without intermediate questions. Add a second scenario with a material gap that warrants one focused question. Show that the agent can use a tool result to change its next action. After the portable demo, verify that a fresh brief reuses scoped experiment evidence through the Bayesian slice. Label recorded model responses in the offline walkthrough. Real model behavior, adoption and lift each need separate evidence.

## Optional runtime and later integration gates

- **Runtime growth.** The POC uses the Python loop. Revisit a Python-native library if a shipped workflow exposes a measurable gap, such as expensive provider-specific maintenance or recovery across long waits. Compare it against the existing campaign commands and tests, including scoped access and cancellation or restart without a duplicate draft.
- **Live reporting and activation.** Add the Google Ads read adapter independently of writes. Validate the exact campaign type, targeting and report grain first. Keep manual handoff if a writable configuration cannot preserve the contextual placements. With separate authorization, verify a validation-only request and then a paused test-account write with read-back. Test stale grants, unknown write outcomes, reconciliation and duplicate dispatch with a fake provider first. A paid pilot is a separate milestone for delivery, inventory and outcome claims.
- **Product expansion.** Schedule report-triggered reviews once repeatable reads exist. Add provider subscriptions, external MCP, user-authored recipes or another ad platform when there is a real workflow for each. Use the same typed product commands and capability checks.
