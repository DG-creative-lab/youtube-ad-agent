# Native storage migration after the #86 pilot

17 November 2026 · Candidate completion scope; merge, independent review and final
verification determine #86 acceptance. This is a migration ownership map, not a
claim of whole-application inversion or hosted readiness. The accepted
[ADR](hexagonal-architecture.md#migration-and-enforceable-acceptance) remains the
scope authority; the [import baseline](architecture-baseline.json) records retained
module couplings and is not an inventory of every SQL or runtime effect.

## Adopted composition

`bootstrap/planner.py:create_local_planner` explicitly initializes the native
schema, workspace/demo admission, original legacy histories and transcript
adoption before constructing `AgentRuntime(initialize=False)`. Its selected
application is `application/planner_runtime.py`, with typed records and units,
`application/planner_context.py` and `application/access.py`. It uses the existing
single SQLite store and real logical media facts; there is no alternate backend.

The supported selection is the original local demo identity and campaigns, authored
`simulated`/`simulated-inspect` placement requests, catalogue registration/list/read,
start and follow-up, scoped read, classification/reservation, draft save, terminal
reply, interruption and receipt replay. `bootstrap/placement_router.py` integrates
that selection with the actual local planner UI and shared agent dispatch. Delivery,
review/experiment tools, configured/foreground inference and their historical
receipts remain on the supported legacy commands in the same store. A retained
workflow exits the adopted unit before legacy dispatch; a database handle is not
passed through a core callback. Existing history-dependent `check_progress`
freshness behavior remains with those retained workflows.

A selected unit reads real owner, revision, catalogue/provenance, approval,
instruction-version, saved review, correction, started-experiment, session/message,
job/turn and run/step facts even when the corresponding tables are empty. Context
assembly preserves package fingerprints and viewer paths. Media capture precedes
the unit and its current facts are checked before commit. Authority acquisition is
outside the write unit; original command/session/scope/owner/preimage and expiry
checks use its typed records. An accepted draft transition binds its postimage
without granting a new permit. Model/classifier dispatch remains outside the write
unit, with separately durable requested/received/failure phases. Draft, step, status,
outcome and reply commit or roll back together. Native failures are mapped to core
storage errors at the adopted boundary; unknown outcomes are not blind retries.

## Residual native graph

Every row below stays on the original store until its own adoption. #37 owns the
remaining native graph and its SQLite/alternate-adapter conformance; #87 owns
external contracts/effect integration; #88 owns consolidation of startup and
entrypoints. These owners do not authorize provider activation or a backend switch.

| Current code family | Remaining work and owner | Required preservation |
| --- | --- | --- |
| `application/campaigns.py`, legacy paths in `agent/run.py`, `agent/planner.py`, `agent/review_tools.py` | #37: nonpilot recorded preparation, review/structured/experiment/delivery command reads and writes; package approvals/export and instruction saves. #88: retire compatibility construction only after callers migrate. Pilot draft/provenance and run lifecycle are not deferred here. | Raw JSON, native IDs, approval snapshots/fingerprints, savepoint atomicity, original received evidence and terminal reply/replay behavior. |
| `agent/conversations.py` and borrowed native store APIs in `adapters/sqlite_{drafts,planner,runs,conversations}.py` | #37: remaining nonpilot consumers of caller-owned native connections. #88: converge composition without deleting the supported compatibility path prematurely. Pilot follow-up selection, supersession, messages and transcript adoption already belong to the selected unit. | Session/operator/campaign/settings scope, stale message checks, exact ordering and malformed-history behavior. |
| `access.py`, `workspaces.py`, `staff.py`, `agent/capabilities.py`, `adapters/local_access.py` | #37: remaining provisioning, staff session records, advisory catalogue and nonpilot permit/native readers. #87: external authority/client adoption. #88: entrypoint resolution/wiring. Selected placement access uses the original permit and same-unit preimage; legacy `CommandAccess` is not asserted migrated. | Current grants, full owner/workspace/installation, expiry/revocation, original command identity, fail-closed disclosure and permit fences. |
| `measurement.py`, `performance.py`, `instruction_tests.py`, `learning.py` | #37: event/visit/completion/assignment aggregation, review and correction writes/freshness, experiments, assessments, snapshots, finding lineage and reuse. Their named pilot context reads and required startup/adoption are in #86, not postponed. | Attribution and denominators, exact comparison/takes identities, current corrections, source versions, scoped evidence and reviewed reuse. |
| `campaign_setup.py`, `delivery.py`, `adapters/simulated_setup.py` | #37: setup/report/recommendation records, approval/reservation/readback and reconciliation. #87: provider effects/reporting contracts. #88: remaining setup/reporting assembly. | Exact approved package/account/action, zero dispatch on denial, received versus unknown outcomes, no repeated uncertain effects, report grain/tagged attribution. |
| `assets.py`, `publications.py`, `recovery.py`, legacy media helpers in `handoff.py` | #37: native private catalog/blob records, publication/link/event atomicity, integrity and whole-store recovery. #87/#88: external asset boundary and remaining media wiring. Selected logical media facts do not establish object-storage readiness. | Immutable scope/digest/filename, current publication access, historical approval evidence and restore invalidation. |
| `migrations.py`, `workspaces.py`, legacy constructor initializers, and their selected copies in `adapters/sqlite_schema.py`, `sqlite_workspace_admission.py`, `sqlite_planner_startup.py` | #37 owns the ordered migration chain and future allocations. #88 consolidates compatibility startup. Until deduplicated, a schema/admission change must keep both supported entrypoints aligned; selected copies are not a second migration journal. | Identical migration names/checksums, key/uniqueness/nullability refusal, local-only adoption, viewer ambiguity/quarantine, provenance recovery and no history rewrite. |
| `provider_sessions.py`, `model_catalogue.py`, `inference_ledger.py`, `foreground_inference.py` | #37: remaining native verifier/operation/selection/cache/quota/receipt/settlement graph. #87: qualified provider contracts/transport. #88: foreground assembly; #70 retains real route/cost/privacy qualification. | Request-local credentials, actor/account/selection identity, admission/deadline/budget, reserved/received/unknown phases and receipt-before-domain effects. |
| `hosted.py`, `scripts/placement_review.py`, `scripts/product_storage.py`, agent CLI/tools and hosted fixtures | #88: remaining parser/session/origin/CSRF/credential and factory consolidation; #37: residual native reader/writer consumers. Existing local placement UI routing is adopted; hosted/provider flows are retained. | Same application commands, existing URLs/JSON/errors, staff/public isolation and no alternative writer. |

No family may switch to PostgreSQL or another selected backend while a mandatory
same-command participant still opens the old store. #37's complete native-graph
milestone precedes that switch; PostgreSQL/cloud acceptance, real identity and
hosted/private-media recovery remain their separate issues. #84 strict zero and
#89 whole-application substitution/conformance follow the remaining graph work.

## Completion evidence

#86 may close only after the final candidate passes the complete authored pilot,
nonempty review/correction/experiment context, current/denied/stale/expired scope,
follow-up supersession, savepoint/commit faults, requested/received interruption,
reopen/replay, schema/legacy adoption and error conformance. Run the full offline
suite, canonical portfolio, affected local HTTP/UI journey and trusted/candidate
architecture checks, with independent source review and verification on the final
commit. Results belong in the stage evidence and PR; this document records no
unexecuted pass or live-service guarantee.
