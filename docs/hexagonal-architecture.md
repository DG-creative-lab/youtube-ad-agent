# ADR: core boundaries and staged inversion

16 November 2026 · H83-boundary-v2 · [#83](https://github.com/DG-creative-lab/youtube-ad-agent/issues/83), first child of [#82](https://github.com/DG-creative-lab/youtube-ad-agent/issues/82).

Status: H83-boundary-v2 accepted by human merge of PR #90 at
`7c139e19bfbf0d829b31f8d09320e912e5561f6b`, tree
`c8daca04e0dbbda84c8905ca4dd3940ae031974a`. The rejected v1 candidate remains
historical working material, not architecture authority. Initial #84 now supplies
an offline checker/live policy/finite shrinking baseline; it changes no runtime
behavior or composition. Independent final-head source/seed/CLI/native/full-suite
and current CI acceptance plus human merge apply. #84 remains open for strict
zero debt after the named native graph; #82/#85–#89/#37 runtime milestones remain
pending. Next after initial #84 human merge is #85 relocation.

## Observed base and inventory

The source baseline is human-merged PR #81 / #80 at
`b885b732fda9cce6894e8b48fb4c8b7e86be9aab`, tree
`b47e5c91ee4bd7a9dcdacc3fc4e1acbb2a836d84`. Its historical 339 tests,
11-case portfolio and CI are evidence of that slice only.

The authoritative [module map](hexagonal-module-map.json) enumerates all **60**
tracked Python files under `campaign_agent/` and `scripts/`, and all **17**
tracked `.ts`, `.tsx`, `.mjs`, `.html`, `.css` files under `web/`, including the
Node test driver. `placement-review/index.html` is a separately classified retained
legacy browser client, outside those 17. Package markers, developer/evaluation
scripts and client styles are classified rather than silently discarded.
`excluded_tracked_paths` enumerates every other base path by support category;
these include tests, docs/instructions, dependency/configuration/workflow files,
authored examples/media, the SVG and contract JSON. The pinned producer wire and
product profile remain data owned by #36/#55, with provenance in
[contracts/README](../campaign_agent/contracts/README.md); they are not new authority.

For each source, the map records current responsibility/definitions, observed
imports, concrete target components with named responsibilities/roles, owner issue
and migration milestone, compatibility/removal and acceptance rules. A target
marked `proposed` does not exist at base; these path strings are plans, not links
to implemented code. Shared `rules` are referenced per module. Python imports are
rows using `import_columns`: kind, source module, relative level, imported name /
alias pairs, line, resolved dependencies, nested flag, TYPE_CHECKING flag, migration
owner and final removal milestone, followed by dependency class, retirement targets
and retirement rule. A null removal milestone is valid only for retained pure,
core-contract, technology-adapter or explicit support uses; their role and actual
operations still require checking. It is not a module exemption. Both literal
`__import__('json')` in local access
and `__import__('math')` in OpenRouter metadata are included. Web imports are
source-observed specifiers/resources; API literals are observations, not a complete
JavaScript execution graph. No runtime checker is provided by this table. A mixed import retires only when
its last actual symbol obligation is complete: use the latest whole-row milestone
and the union of real callee/port/adapter/factory destinations. Earlier pure
members can move at #85, and mandatory pilot members at #86, without retiring
later file/default/cache/native obligations. Imported classes and namespace
members must be traced through construction and calls; renaming a caller does
not discharge those obligations.

Current concrete seams are useful but incomplete. `SQLiteDraftStore`,
`SQLiteConversationStore`, `SQLitePlannerStore` and `SQLiteRunStore` borrow native
connections; callers still import them, issue SQL, initialize schema and decide
lifecycle. `CampaignDrafts` remains reusable application code in `scripts/`.
`AgentRuntime` constructs concrete collaborators. `planning_models.py` mixes a
Protocol/tool definitions, simulation and OpenRouter. `hosted.py` and
`scripts/placement_review.py` mix inbound transport with composition and native
reads; the latter also owns YouTube/Jev/search/report glue. Existing behavior
checks do not establish dependency inversion.

## Scope values and their use obligations

The finite `scope_use_contract` in the [module map](hexagonal-module-map.json)
separates immutable value **definitions** from what a caller does with them.
It covers every import/use of `LOCAL_BRAND`, `LOCAL_OPERATOR` and `LOCAL_CONTEXT`
across all 60 Python sources: nine import rows, eleven bindings, 25 Name loads
and three definition stores. Its 24 grouped records retain every occurrence's
column and multiplicity, including two member loads on the same source line.
Each record links the actual import/definition and source line to its behavior,
kind, targets, owner, milestone and disposition. The five native `test_id`
callers are recorded separately as use evidence. No runtime checker is shipped.

| Actual use | Disposition and obligation |
| --- | --- |
| `access.py` definitions at24/25/41 | Immutable authored values/type composition can relocate to `domain/scope.py` at85. A seeded operator value is not authenticated hosted identity or evidence of a current external grant. Its definition does not retire defaults or native adoption elsewhere. |
| `adapters/local_access.py`14/24 | Exact scope/actor comparisons remain in the explicit local-only adapter. Importing the relocated immutable value is an inward85 dependency, not an implicit identity choice in application construction. Keep this existing adapter role and first86 actor/native/permit fences; its separately planned87 path relocation supplies no hosted fallback or excuse to delay those checks. |
| `agent/run.py`66/69 and98 | Omitted operator/context selects local identity at66/69: bootstrap `local_defaults`/`services` owns final88 retirement. The guarded legacy `agent_runs` campaign backfill at98 is a real native write owned by first86 `sqlite_planner_startup`/workspace admission. The entire import row therefore ends at88, with definition85 and mandatory startup86 recorded separately. The first86 factory passes explicit operator/context now; it does not wait for88. |
| `scripts/campaign_drafts.py`84/89/90/98/101/112 | Catalogue backfill84 and guarded native admission112 stay86. Constructor operator/context defaults89/90, implicit local campaign guard98 and authored-example fallback101 belong to explicit bootstrap88. Preserve that existing split and the complete-row88 deadline. |
| `measurement.py`56/59 | `LOCAL_BRAND` binds the sibling-owner ambiguity SELECT and conditional legacy visit UPDATE in constructor schema adoption. Both are mandatory first86 viewer startup participants, not pure constant imports. Preserve the exact local owner filter, ambiguity guard and quarantine of other unbound visits. Ordinary event/completion/aggregation records remain separate37 work; later record adoption cannot defer this initializer. |
| `instruction_tests.py`82 | The compatibility default belongs to deterministic scope-inclusive ID hashing, not identity admission, access or a core constructor default. Retain exact hash/default compatibility as a pure85 calculation. All current native callers at88/116/240/462 and `learning.py`73 explicitly pass `self.drafts.scope`; their native checks resolve owner/current authority separately. A computed ID grants no read/write/permission. Migration tests and review must reject new native callers relying on omitted scope, while retaining exact historical IDs and standalone calculation compatibility. The simplified import checker does not analyze those calls. |
| `creatives.py`47/55 | Static authored Example tags are deterministic data using the declared brand value. The scope/type reference can move85; separate EXAMPLES fixture/default composition stays88. This does not select a caller's identity, grant access or replace the server's brand/catalog checks. |
| `workspaces.py`20/54 | Explicit reserved-demo native binding20 stays86 admission. Comparing an explicitly supplied context against reserved demo IDs54 is deterministic validation, not choosing a default or granting membership. The shared import also has `require_access`'s existing87 contract obligation; its complete-row deadline remains88 without deferring native admission86. |
| `scripts/evaluate_agent_behavior.py`254 | The foreign-authored actor/brand fixture remains support-only, checked at89. It confers no production identity/default; core cannot import the evaluator. |

For migration review, definition/import spelling and use-obligation identities are distinct; the simplified #84 guard tracks module edges only.
Moving a value to a pure package, changing its import alias, or splitting a file
cannot discharge its original constructor-default, admission or backfill debt.
Preserve the register's obligation identity and actual semantic role when a
migration moves source witnesses. Re-enumerate the entire finite closure,
including stores, defaults and same-line member occurrences; new/aliased/member
uses require explicit review, not an automatic pure-symbol exemption. Complete
row retirement is the maximum of recorded use and existing non-scope obligations.
No original86 pilot participant may be postponed merely because that row also
contains a later88 default. Current supported runtime behavior, scope checks,
native adoption criteria, hashes and public compatibility remain unchanged by
this specification.

## Decision and directions

Adopt `campaign_agent/domain/`, `application/`, existing core-owned `ports/`,
`adapters/inbound/`, `adapters/outbound/` and `bootstrap/` using the map's feature
splits. Preserve existing campaign, agent, access, evidence, learning, media and
provider responsibilities. Create each component only when its slice moves a real
caller; no generic framework or speculative interface layer is required.

| Importing role | Permitted project dependencies and responsibilities |
| --- | --- |
| domain | Other acyclic domain values/rules/errors; no application/ports/adapters/bootstrap/scripts. Deterministic policy only. |
| ports | Domain values/errors and acyclic core contract types. A purpose-specific Protocol may live beside its application caller if it has the same inward rules; a folder alone does not make it a port. |
| application | Domain, core-owned ports and acyclic application services. Own scope/approval/revision/evidence/mandate/recovery policy; receive dependencies. |
| outbound adapter | Core contracts/values and necessary driver/SDK/network/filesystem mechanics. Adapter-to-adapter helpers are permitted only as explicit acyclic technology-local dependencies, e.g. shared OpenRouter transport. No inbound/bootstrap/scripts import. |
| inbound adapter | Application commands and typed core inputs/errors. Own HTTP/CLI/tool field parsing, authentication/context extraction and wire/error mapping; no direct repository/driver/provider construction or alternative business writer. |
| bootstrap | Explicit concrete construction plus application/port wiring; no product approval or recovery policy. Only approved roots select storage/provider/access/media implementations. |
| scripts / old module facades | Thin inward delegation to inbound/bootstrap/application as appropriate; never imported by core. Supported invocations survive extraction. |
| browser client / test driver | Clients consume supported HTTP and client modules, never confer authority. Test/evaluation drivers may construct authored dependencies in test composition and inspect native witnesses; production core cannot import them. |

Domain permits deterministic stdlib values/calculations (`dataclasses`, `enum`,
`typing`, `collections.abc`, `functools`, `math`, `decimal`, `hashlib`, `json`, `re`,
`datetime`, `unicodedata`, and deterministic `hmac.compare_digest`) when used
without I/O, clock reads or environment access. Reviewed deterministic
`urllib.parse` parsing/encoding (`urlsplit`, `quote`, `urlencode`, `parse_qs`)
may remain beside business URI validation. These text operations neither open a
URL nor require a parser port; they must not move business validation outward
solely because their package is named urllib.
Application/ports may use stdlib in the same effect-free way for their inputs and
orchestration. No third-party pure dependency exception is currently approved;
Adding one requires explicit package/module/use review; the import guard also needs a separately reviewed rule change.
`sqlite3`, SQL, driver exceptions, Starlette/http.server/Uvicorn,
`urllib.request`/`urllib.error`/requests network mechanics,
Google SDKs, provider adapters, Path/file operations, environment key lookup and
startup schema effects belong outside core. Clock/ID/media/cache dependencies are
injected purpose-specific contracts only where an existing caller needs the effect.
A bootstrap default cannot be hidden in an application constructor. The map
explicitly assigns current Path/file, os/stat, native closing/transactions,
clock/UUID/secrets and cache/lock uses to their actual adapter/composition owners.
`runtime_values` port/adapter targets support existing clock/ID callers beginning
with #86; later caller adoption remains separately owned. Mathematical memoization
in `instruction_policy` remains deterministic policy; mutable connection-scoped
catalogue/cache/locks move to `memory_catalogue` under #87. Time-zone database
lookup is an adapter effect; core window validation uses supplied zone facts.

Approved proposed construction roots are `bootstrap/services.py`, `planner.py`, `local.py`,
`hosted.py`, `authored.py`, `agent_cli.py`, `google_ads_cli.py`, `fixture_cli.py`,
`storage_cli.py`, `schema.py`, `workspace_admission.py`, `local_defaults.py`,
`demo_media.py`, `provider_profiles.py`. Roots may share assembly helpers but
never import inbound modules that import them back; a thin launcher calls the
factory then hands constructed services to the inbound adapter. No unrestricted
`bootstrap/**` exemption: #84 checks exact path roles and static import cycles;
construction and call behavior remain migration test/review obligations. Test composition is explicit and cannot become a production fallback.

Allowed calls follow imports: a client/inbound command invokes application policy;
application calls a core-owned port; a supplied adapter implements that port;
bootstrap constructs the graph. Core never receives an ASGI Request/Response,
provider HTTP envelope, SQLite connection/cursor, SQL string, driver-specific
error/SQLSTATE, arbitrary `execute`, `.connection`, callback over a native handle,
or opaque `Any`/`object` capability. A generic dictionary wrapping those objects
is equally forbidden. Boundary records use named typed immutable values and
explicit optional fields; bounded JSON payloads use a closed recursive JSON-value
type with validators, never arbitrary Python values. Preserve missing row versus
present malformed JSON/NULL/empty facts; do not coerce malformed presence to absence.

Retain and narrow existing `AccessPolicy`, `ProviderMetadata`, `SetupProvider`,
`CampaignReporting`, `PlacementClassifier`, `MainModel`, `ModelInference` and
`IdentityVerifier` contracts rather than wrapping them in unused duplicate ports.
Move `GateplaneClient`'s wire dictionaries to outbound ownership and its validated
facts to typed access values. Move `ReviewInferenceError` and product errors out
of concrete adapters/scripts; move ProviderError HTTP status/response mapping to
inbound while retaining supported public codes/messages/retryability.
Application validates business facts in provider output; adapter success cannot
approve, publish or launch.

## Transaction, authority and recovery contract

#86 defines concrete signatures in its bounded implementation; the following
semantics are binding without freezing speculative product APIs.

* One selected store/UOW factory supplies all transaction-scoped repositories
  participating in a command: owner/native facts, revisions/approval/catalogues,
  conversation/session/message, job/turn, run/step and relevant evidence/receipt
  records. Neither a repository nor nested use case opens a second connection,
  silently falls back to SQLite, independently commits or changes backend.
  Read-only units offer a consistent snapshot for decisions needing joined facts;
  no loosely timed sequence of independent reads is an equivalent substitution.
* The application decides logical acceptance and explicitly requests completion.
  The adapter owns connection acquisition, begin/isolation/locks, savepoint,
  commit/rollback and close. Exception, unaccepted result or exit without explicit
  completion rolls back. Completion is single-use; use after exit fails. A
  nested tool attempt can roll back its own changes without rolling back an
  already retained external receipt or committing its parent. Sibling attempts
  cannot observe rolled-back effects. No repository factory exposes a native handle.
* Load and check immutable full client/brand/workspace/installation/campaign
  ownership before projecting private records; runs/conversations/provider records
  also filter original actor/session as required. IDs alone are never permission.
  Repository predicates and application current-access checks both remain; adapters
  do not infer authority from a copied row or grant it by returning data.
* Preserve start/retry identities and changed-input conflicts. Final tool acceptance
  rechecks current scope, original run/request, revision, supersession, mandate,
  evidence/correction/media and permitted command facts. Commit draft revision,
  step, terminal status, job outcome and assistant reply atomically. Recoverable
  invalid tool arguments roll back the attempt before recording its safe failure
  result. Failure inserting a step or terminal status/reply rolls back the draft
  and all final effects. Explicit resume reuses its original received evidence.
* Keep main-model requested/received turns, classifier requested/received state,
  structured `agent_test_sources`/`agent_review_inference`, and foreground
  reservation/dispatch/cost evidence as distinct durable phases. Inference/report/
  authority I/O stays outside write locks. Requested/dispatching/unknown cannot be
  treated as unsent after crash or missing acknowledgement; no automatic repeat
  completion, new allowance, cost release or retargeting. Foreground cost evidence
  commits before semantic acceptance; rejected/late results may retain accounting
  while gaining no authority to save a tool result/draft. A received semantic
  receipt needs no new credential or provider request for local recovery.
* Current authority is application-owned. Gather required command permits outside
  locks, retaining each original expiry and exact session/full owner/command hash/
  campaign revision/native snapshot binding. Recheck local session/revocation and
  those bindings at admission and final acceptance. Do not replace a denied optional
  capability with an agent.run allow, renew old permits by joining a fresh one,
  or treat the written postimage as the original authorized preimage. The UOW must
  preserve/recheck the authorized preimage and permitted transition at the same
  fence/order as today's owner; after an accepted revision change obtain fresh
  outside-lock authority before the new private response. Today's `CommandAccess.decide`
  opens a separate SQLite read while `check(db)` uses the supplied connection;
  #86/#37 must replace the former with the proper same-store typed read/fence,
  not copy this coupling or naively compare the mutated postimage to an old permit.
* Preserve original decision lifetime: earliest wall expiry, credential/session
  expiry and monotonic start-before-check plus `min(valid_for_ms,5000)`. No network
  authority callback under a writer lock. This is the accepted bounded decision-use
  window, not atomic distributed revocation or recall of already emitted bytes.
  Response/media access still has a last current-authority/native fence.
* Adapters translate native unique/revision conflict, unavailable/busy, malformed
  stored fact and uncertain commit into narrow core error categories, retaining
  distinctions needed by callers. Application chooses allowed recovery; inbound
  maps to existing public exception attributes, statuses/codes/messages. No blanket
  retry on IntegrityError, SQLSTATE or network error. An ambiguous commit reloads
  the original operation before deciding; only known-uncommitted local work can
  receive a bounded retry under refreshed authority. Never repeat external I/O
  inside a transaction retry. Low-level adapter conformance may assert native
  driver behavior; driver types do not cross into application policy.

Exact raw snapshot/receipt JSON text, UTF-8/bytes, actors, IDs, timestamps,
approvals, immutable selections and request hashes survive unchanged. Native
`handoff.package_fingerprint` is the bare lowercase SHA-256 of sorted compact
ASCII-escaped JSON; project-profile hashes use their separately pinned literal
Unicode encoding. Do not normalize Unicode/recompute approvals, replace raw text
with JSONB, narrow `actual_nanos` decimal text to SQL integers/floats, or erase
unknown accounting. Derived projections cannot replace original histories.

Restore remains operator-only, whole-store and integrity-before-bytes. Existing
copied staff/provider/public authority is invalidated without deleting uncertain
receipts/ledger costs. The future all-campaign fresh-incarnation reconciliation
fence applies **before** standalone/project policy, including absent links and
pre-project backups; it is not implemented by this ADR or today's recovery tool.
Project intent/recipient lookup/revoke and native producer agreements remain
[#55's gates](project-access-integration.md). Membership, schema-valid profiles,
copied operation successes, received receipts and learned/model text confer no
new authority. Preserve publication's separate exact-content grant, full media
hash/size verification before bytes, foreground active-tab key policy, selected
budget/profile and unknown-effect rules in the [storage](storage-recovery.md),
[access](hosted-access-boundary.md), [project](project-sharing-contract.md) and
[foreground](openrouter-session-contract.md) contracts.

## Migration and enforceable acceptance

The manifest's milestone graph is authoritative and acyclic:

| Milestone | Prerequisite | Exclusive finish/next owner |
| --- | --- | --- |
| 83-contract | Accepted #80 base | ADR/map accepted after independent review/verification and human merge. |
| 84-initial | 83-contract | #84 implements tested checker and reviewed finite owner-linked baseline before migrations. Issue remains open. |
| 85-core | 84-initial | #85 relocates reusable core/errors and flips internal imports; outward debt stays explicitly owned. |
| 87-foundation | 85-core | #87 first provides MainModel/ModelInference/classifier typed contracts and real injectable offline adapters needed by the pilot; other external adoption follows later. |
| 86-first-uow | 87-foundation | #86 adopts the complete bounded local placement workflow below, including native supporting reads/startup and its minimal composition root. |
| 87-external | 86-first-uow | #87 serially inverts shared model/access/effect construction/errors and supplies the minimal services factory for real callers; #88 later consolidates the other roots. #36/#39/#70 retain activation. |
| 88-composition | 87-external | #88 makes local/hosted/CLI/tool startup explicit and transport thin; all accepted initial graphs remain supported. |
| 37-native-graph | 88-composition | #37 finishes every residual native graph listed below using accepted contracts. No PG required. |
| 84-strict | 37-native-graph | #84 import baseline empty; broader runtime conformance still requires #89. |
| 89-conformance | 84-strict | Independent whole-application native/substitution/security/performance acceptance; #82 may then close after human merge. |
| 37-pg-cloud | 37-native-graph | Separate #37 PostgreSQL/private media/DB+blob recovery acceptance; no edge from here back to #89. |

This splits #87 foundation from final adoption and chooses serial integration for overlapping files even where #86/#87 planning
can be independent. At dispatch one builder owns shared runtime constructors,
commands, adapters and migration files; schema slots remain with one serial #37
owner after refresh/rebase. No implicit allocation of slot 5 or duplicate recovery
journal. A wrapper at an old path may import inward for compatibility but core
must import its new owner directly. Remove migration exemptions by their named
milestone; retain public CLI/URLs/needed external imports as inward facades with
an explicit #89 compatibility decision, never an outward core exception.

The first #86 adoption is precisely the existing **local authored simulated
placement** journey: explicit startup/catalogue registration → start/read →
read_campaign/classify/save → received-receipt interruption → reopen/replay and
terminal conversation reply. #87-foundation supplies actual model/classifier
contracts/offline implementations first. #86 owns `bootstrap/planner.py` as minimal
composition, with all native owner/preimage/catalogue/revision/approval/instruction-
version/session/message/job/turn/run/step and classifier-phase participants,
`sqlite_schema.py`, `sqlite_workspace_admission.py`, `sqlite_planner_startup.py`,
`sqlite_conversation_lifecycle.py` and logical media reads required by that
workflow. It must move every needed
constructor/adoption effect into explicit adapter startup before instantiating
adopted core services. No dependency on a future #88 factory or #37 final native
participant is permitted. First-pilot original-permit/preimage policy in
`application/access.py` is also delivered at #86 with typed owner facts; #87
external authority adoption does not delay that local acceptance fence.

In particular, placement `start` always invokes `CampaignReviewTools.pin`, reading
`CampaignPerformance.saved_review` and `InstructionTests.started_for_package`;
`read_campaign` also reads `correction_for_comparison`. Even empty tables are real
participants: #86 extracts typed `ports/planner_context.py`,
`application/planner_context.py` and `sqlite_planner_context.py` for these reads.
It must not bypass them, hardcode missing evidence or defer them to #37.

Conversation `begin` is also mandatory on every placement `start`: it executes
its joined prior-running-run SELECT even on an empty store, then supersedes each
matching unfinished run by status, planner-job outcome and assistant reply before
creating the new turn. #86 explicitly owns all these operations in the typed
conversation/run/planner repositories and `sqlite_conversation_lifecycle.py`.
The same #86 adapter startup owns constructor DDL and legacy transcript adoption
(including original message/outcome replay). Preserve full owner/actor/session,
settings/prompt-version and stale-after-message checks. Superseded writes and the
new settings/user message/default/run/job remain in the caller's parent UOW;
a failed new message rolls them all back while preserving prior received evidence.
None of this first-pilot startup, selection, outcome, status or reply work waits
for #37, and no raw handle callback may bridge it.

Other review/setup/delivery/experiment/structured/foreground commands stay supported
on their original single native store under named shrinking-baseline debt until
their adoption. They are not claimed inverted or exposed through the adopted
pilot as native-handle callbacks. #88 later consolidates all composition while
reusing the accepted minimal root. No backend switch is allowed for partial graphs.
#37's remaining native milestone must migrate these named families:

| Current family | Residual responsibility / acceptance |
| --- | --- |
| Drafts/planner/run/conversations/review | All pilot DDL/admission/seed, draft/approval/instruction/catalogue facts, planner joined history/defaults, conversation constructor/adoption and begin supersession selection/status/job-outcome/reply belong to #86, including nonempty followups. Only genuinely nonpilot structured test-source/inference and review/experiment write/freshness participants remain #37; no conversation lifecycle prerequisite is deferred. Native rollback, followup, received-write fault and reopen/replay retain exact rows. |
| Access/workspaces/staff/capabilities | First-pilot owner/preimage/permit policy/reads and explicit local admission are #86. Remaining trusted provisioning, staff session/CSRF/expiry and advisory catalogue records are #37; #87 completes external access/identity integration and #88 other startup. Full owner/private scope checks precede projection. |
| Discovery/setup/reporting | Catalogue/provenance and selection; exact setup approval/reservation/receipt/unknown/readback; report snapshots/native grain/tagged attribution. #86 owns pilot catalogue records, #87 provider ports, #37 remaining storage. Denied/stale setup causes zero dispatch; uncertain effects never repeat. |
| Measurement/performance/instruction tests/learning | Visit/event/assignment/aggregate reads, review/correction freshness, pair/snapshot/source-test/finding lineage and fresh-brief saves. #86 owns the already named pilot saved-review/correction/started-for-package reads. #37 owns remaining writes/aggregation/assessment/evidence/finding records; #85 pure policy splits. Preserve denominators, scoped source evidence, current corrections and atomic followup. |
| Assets/publications/recovery/schema | Private catalog/blob metadata, publication/link/event atomicity, exact media integrity and filenames, operator checkpoint/restore invalidation and ordered legacy migrations. #86 owns pilot logical media and existing schema/admission/startup extraction with checksums preserved. #37 owns remaining native assets/publications/recovery and future schema allocation; #88 other startup. Actual object storage/PG recovery is later. No copied authority or absent-link bypass. |
| Provider sessions/catalogue/ledger/foreground | Verifier/operation/immutable selection records, cache/bounded metadata, quota aggregate/dispatch/cost settlement and all semantic receipt writers/permit/step reads. #87 contracts/transport, #37 one native store graph, #88 wiring. Preserve original settings/request/actor identity, unresolved reserves across reconnect/day/restore and receipt-before-domain phases. |
| HTTP/local/CLI/tools/UI | #88 extracts local/hosted parser, origin/session/CSRF/credential transport and dependency factories; every path delegates to same application commands. Scripts/evaluation drivers remain classified support consumers; client URLs/payloads/draft controls unchanged. |

On 16 November 2026 the user explicitly simplified initial #84 to a static Python
module dependency guard. This supersedes the earlier requirement that #84 infer
use-level/native/callback/effect behavior and preserve individual occurrence
identities. The accepted application boundaries, first-pilot #86 adoption,
whole-row migration owners and transaction/security requirements above remain.
Their deeper obligations are verified through migration tests and source review,
not claimed as properties established by the smaller checker.

#84 inventories Python source, checks all-depth static imports, allowed layer
directions and module cycles, and admits only a finite reviewed set of existing
module-edge exceptions. CI compares exceptions against the current accepted
integration base: new edges or altered surviving metadata fail; removed edges
must remove their exceptions. Strict mode requires zero admitted import edges.
Import aliases or repeated symbols on an admitted edge share that explicit waiver;
there is no statement identity or runtime-effect proof. Web source remains in the
historical inventory and existing Planner checks.

#89 also substitutes a contract-conforming authored adapter solely via composition
for representative real use cases without editing application source. That adapter
must preserve tested transaction/error semantics, not hardcode success; native
SQLite conformance remains required. Refresh inventory, affected CLI/in-process
HTTP/browser journeys, full offline suite/canonical portfolio, exact-head review
and unchanged Python/planner CI. No browser check is applicable to #83's data/docs.
#37 PG/cloud, #36 identity/issuer, #38 jobs, #39 effects, #40 privacy, #41 operations,
#42 pilot, #55 projects and #70 foreground qualification keep their existing gates.

## Initial #84 enforcement and limits

The user-approved H84-simple-v5 scope replaces the unpublished broad analyzer.
The [live policy](architecture-policy.json) assigns exact roles to 61 Python files;
[88 readable module-edge exceptions](architecture-baseline.json) record source,
target, rule, owner and whole-import retirement milestone. No call-level finding
catalogue or compact occurrence schema is needed. The historical module map,
including its 60 Python/17 web/legacy-client snapshot, stays byte-identical.

The stdlib tool parses source without importing or executing it. Static imports at
all depths, relative/package-child imports, local package initializers, local
stdlib-name shadows and cycles are checked. Import permissions and role directions
are defined explicitly in the checker; support/developer tools are consumers,
bootstrap permissions apply only to classified paths, and inert markers cannot
hide executable code. Existing module-edge waivers intentionally cover repeated
imports and additional symbols from the same module.

This tool does not establish SQL/native-handle safety, indirect or dynamic effects,
reflection safety, callback behavior, cache lifetime, scope/authority correctness,
web dependency correctness or complete migration adoption. Existing behavior tests,
review and later conformance checks retain those responsibilities. Passing strict
means zero import exceptions, not proof of all architectural requirements.

The first seed is bound to exact accepted #83 with protected source/modes unchanged,
clean committed files and a single candidate commit parented directly to that base.
CI may check its two-parent synthetic merge only when parents are exactly base and
that candidate and its full tree is identical to the candidate. Other initial-seed
histories are rejected. Later comparisons require an
externally selected current accepted base. A stale historical base does not prove
cumulative shrinkage. Candidate-controlled CI is subject to workflow/branch review;
it cannot guarantee its own enforcement. Detailed commands, role directions,
shrinking rules and limitations are in the [engineering workflow](engineering-workflow.md#architecture-migration-gates).
No automatic baseline updater, application change or #84 closure is introduced.
The original native comparison recipe below is unchanged.

## Authored native baseline and provisional comparison gate

Executed on the base source above: CPython **3.14.3**, SQLite **3.51.3**, Darwin
arm64. Three independent child processes per workload; all databases/media are
fresh authored scratch, no service/account/network/provider fixture. Timings are
instrumented local observations, not deployed latency, live-provider throughput,
a statistically useful p95 or a production SLA.

| Workload | Elapsed milliseconds (all three samples) | Connections / traced statements per sample | Authored adapter calls |
| --- | --- | --- | --- |
| cold | 143.843, 126.524, 128.907 | 12 / 113 | 0 |
| demo | 21.126, 21.047, 20.905 | 31 / 167 | 4 recorded decisions |
| planner_recovery | 30.794, 31.059, 31.482 | 35 / 271 | 3 simulated main-model decisions, 1 classifier |

`cold` times application import, tiny authored file setup and fresh runtime
construction inside a new interpreter; interpreter startup, stdlib/instrumentation
imports and final cleanup are excluded. The OS/file cache is not flushed.
`demo` and `planner_recovery` reset counters/timer **after** initial runtime
construction; they include commands, a second runtime construction against the
same store, assertions and replay. Counts include transaction/DDL/PRAGMA statements
and verification reads in the snippet, not just SELECTs; SQLite trace callbacks
may repeat trigger-related statements. They count connection attempts (all
succeeded here). The callback only increments, never persists SQL text/values.
Tracing adds overhead; compare with the identical instrumented recipe. No remote
adapter attempt counter is installed: only the shown authored decisions/classifier
are observed; this is not a live network/deadline benchmark.

For subsequent architecture slices, default structural tolerance is **zero extra
connections, traced statements or authored adapter attempts** for identical work;
reductions are allowed only with behavior preserved. A justified count increase
needs explicit reviewer approval with source reason and revised measured baseline,
never silent ratchet regeneration. Provisional timing gate: compare three-sample
medians on a comparable idle host; allow up to `max(25%, 25 ms)` increase over the
baseline median for each workload. If exceeded, reproduce with at least 10 samples,
report host/noise and obtain a reviewed explanation or fix before acceptance.
These are refactor comparison tolerances, not a product latency promise.

Existing local expiry/admission fences remain distinct from transport timeout
configuration: original decision use at most 5 s, foreground connection at most
1 h/session expiry, charging-profile expiry at reservation/dispatch, catalogue TTL
5 min, planner eight calls / 512 target output tokens / 32 KB full envelope,
structured one-call and current quota/cost bounds. The provider adapters pass
**nominal timeout arguments** of 5 s for metadata and 30 s for completion. These
arguments do not establish an enforced total DNS/connect/slow-stream request
deadline; hard total transport-bound qualification remains #70. Local SQLite uses
its existing connect/lock behavior; this baseline neither tunes timeouts nor
measures a real provider deadline. The [hosted decision](hosted-topology-decision.md)
proposes separate deployment targets; none is established here. Future #89 compares
resource/deadline behavior in addition to local timing.

To reproduce from the repository root, use the existing Python environment with
`requirements-test.txt` dependencies already installed. Do not install anything or
start a service for this recipe. Save the following **complete** snippet to a
scratch file, e.g. `/tmp/hex83-baseline.py`, then run
`/path/to/installed/python -B /tmp/hex83-baseline.py`. The JSON includes every
sample and environment; UUIDs/temp paths/SQL/values are not output. The base SHA is
a workload attribution constant: independently record `git rev-parse HEAD` for
comparison on another candidate. Only the baseline source SHA is claimed here.

```python
"""Authored offline workload; run from repository root with installed Python."""
import json, os, platform, statistics, subprocess, sys

WORKER = r'''
import json, sqlite3, sys, time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
stats = {'connections': 0, 'statements': 0, 'recorded_decisions': 0,
         'planner_decisions': 0, 'classifier_calls': 0}
connect = sqlite3.connect
def traced_connect(*args, **kwargs):
    stats['connections'] += 1
    db = connect(*args, **kwargs)
    def count_only(_statement):
        stats['statements'] += 1
    db.set_trace_callback(count_only)
    return db
sqlite3.connect = traced_connect
started = time.perf_counter()
from campaign_agent.agent.run import AgentRuntime, RecordedInference, DEMO_REQUEST
from campaign_agent.agent.planning_models import SimulatedPlanner
from campaign_agent.placement_discovery import SimulatedClassifier
from campaign_agent.creatives import EXAMPLES
class Recording(RecordedInference):
    def next_tool(self, *args):
        stats['recorded_decisions'] += 1
        return super().next_tool(*args)
class Planner(SimulatedPlanner):
    def next_turn(self, *args):
        stats['planner_decisions'] += 1
        return super().next_turn(*args)
class Classifier(SimulatedClassifier):
    def classify(self, *args):
        stats['classifier_calls'] += 1
        return super().classify(*args)
with TemporaryDirectory(prefix='hex83-') as temp:
    root = Path(temp); media = root / 'media'; media.mkdir()
    for example in EXAMPLES:
        for name in {example.preview, *(take[2] for take in example.takes)}:
            (media / name).write_bytes(name.encode('ascii'))
    def reopen():
        return AgentRuntime(root / 'state.sqlite3', media_dir=media,
            model=Recording(), planner_simulator=Planner(), placement_classifier=Classifier())
    runtime = reopen()
    mode = sys.argv[1]
    if mode != 'cold':
        for key in stats: stats[key] = 0
        started = time.perf_counter()
    if mode == 'demo':
        run = runtime.start(DEMO_REQUEST)
        result = runtime.resume(run)
        assert result['status'] == 'ready_for_review'
        assert runtime.drafts.read()['revision'] == 2
        runtime = reopen()
        assert runtime.resume(run)['status'] == 'ready_for_review'
        assert runtime.drafts.read()['revision'] == 2
    elif mode == 'planner_recovery':
        catalog = runtime.planner.catalogs.register('Authored catalog', [
            {'video_id':'SAMPLE00001','source':'synthetic','description':'Video editing voiceover timing tutorial.'},
            {'video_id':'SAMPLE00002','source':'synthetic','description':'Audiobook fiction narration and character voices.'},
            {'video_id':'SAMPLE00003','source':'synthetic','description':'Video editing and audiobook production together.'}])
        run = runtime.planner.start('Find placements for the saved campaign.', 'simulated',
            uuid4().hex, uuid4().hex, catalog, draft_permission='placements')
        runtime.resume(run, max_steps=2)
        with patch.object(runtime.planner, '_commit_turn', side_effect=sqlite3.OperationalError('Authored stop')):
            try: runtime.resume(run, max_steps=1)
            except sqlite3.OperationalError: pass
            else: raise AssertionError('Interruption missing')
        with closing(sqlite3.connect(root / 'state.sqlite3')) as db:
            assert db.execute('SELECT state FROM planner_turns WHERE run_id=? AND position=2',(run,)).fetchone() == ('received',)
        before = stats['planner_decisions']
        runtime = reopen()
        result = runtime.resume(run, max_steps=1)
        assert result['status'] == 'ready_for_review' and result['result']['revision'] == 2
        assert stats['planner_decisions'] == before == 3
        assert runtime.resume(run)['status'] == 'ready_for_review'
        assert stats['classifier_calls'] == 1
    else:
        assert mode == 'cold'
    elapsed = time.perf_counter() - started
    print(json.dumps({'elapsed_ms':round(elapsed*1000,3), **stats}))
'''
if __name__ == '__main__':
    result = {'base_commit':'b885b732fda9cce6894e8b48fb4c8b7e86be9aab',
        'environment':{'python':platform.python_version(),'sqlite':__import__('sqlite3').sqlite_version,
        'os':platform.system(),'machine':platform.machine()},'samples':{}}
    for mode in ('cold','demo','planner_recovery'):
        result['samples'][mode] = [json.loads(subprocess.check_output(
            [sys.executable,'-B','-c',WORKER,mode],text=True,env={**os.environ,'PYTHONHASHSEED':'0'})) for _ in range(3)]
    print(json.dumps(result,indent=2))
```

The receipt interruption is authored before `_commit_turn`, after the native
received row; reopen must finish without another model decision. This does not
replace native trigger/final-write rollback tests or full provider unknown-outcome
conformance. The fixture bytes are filenames, not playable media. Existing native
suite and browser/media acceptance remain separate. Compact measured JSON is also
retained under `baseline` in the module map; helpers outside Git are not required
to reconstruct the measurement.
