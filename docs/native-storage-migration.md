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

## Campaign draft and package storage · #37

Campaign draft reads and writes, brief changes, live catalogue registration,
package review, approval, historical snapshots, export and comparison instruction
versions use scoped records and transactions defined in `ports/drafts.py`.
`adapters/sqlite_drafts.py` owns the native queries and standalone units. Reads
are read-only, writes require explicit commit, and records expire with the unit.
Legacy setup, reporting, learning, publishing and agent paths borrow the draft
repository on their existing transaction so related records still commit together.

## Campaign setup and delivery storage · #37

Setup validation, paused creation, receipt reconciliation and delivery review use
the setup and delivery unit in `ports/setup_delivery.py`. Its SQLite adapter reads
approvals, public destinations, setup journals, tagged viewer counts and current
corrections in the same transaction as the affected records. Provider dispatch,
read-back and report capture retain their separate phases. Existing agent turns
borrow the same repository on their own transaction for sibling writes.

## Viewer and publication storage · #37

Viewer visits, playback events, completions, attribution summaries and hosted
publication grants use scoped records and explicit commits from
`ports/viewer_storage.py`. The SQLite adapter supplies one unit for a verified
setup link and its arrival, or an active publication and its viewer write.
Public playback and media recheck the exact grant after resolving the comparison.
Instruction-test assignments and review evidence still borrow the viewer
repository on their original transaction.

## Performance and experiment evidence storage · #37

Performance reviews and corrections, experiment starts and assignments,
assessments, and cumulative evidence snapshots use scoped records from
`ports/evidence.py`. The same SQLite unit reads approved drafts, correction
history and viewer evidence. Assignment and arrival commit together. Existing
agent runs borrow these records in their original transaction.

Saving, matching, applying and retiring reusable findings uses the same evidence
unit. The unit checks the source experiment, current correction and eligible
brief before writing. Applying a finding commits its tested wording and lineage
in one draft revision.

## Staff session storage · #37

Staff sign-in, local session lookup, campaign selection and sign-out use
[typed session records](../campaign_agent/ports/staff_sessions.py). The
[SQLite adapter](../campaign_agent/adapters/sqlite_staff_sessions.py) owns each
session change. Application policy still checks expiry and the current upstream
identity. The hosted entrypoint authorizes campaign selection before saving it.
Startup and recovery still use the existing staff session table.

## Residual native graph

Every row below stays on the original store until its own adoption. #37 owns the
remaining native graph and its SQLite/alternate-adapter conformance; #87 owns
external contracts/effect integration; #88 owns consolidation of startup and
entrypoints. These owners do not authorize provider activation or a backend switch.

| Current code family | Remaining work and owner | Required preservation |
| --- | --- | --- |
| `application/campaigns.py`, legacy paths in `agent/run.py`, `agent/planner.py`, `agent/review_tools.py` | #37: nonpilot recorded preparation, review/structured/experiment/delivery command reads and writes. Remaining callers still own the native transactions that combine draft writes with their records. Pilot draft/provenance and run lifecycle are not deferred here. | Raw JSON, native IDs, approval snapshots/fingerprints, savepoint atomicity, original received evidence and terminal reply/replay behavior. |
| `agent/conversations.py` and borrowed native store APIs in `adapters/sqlite_{drafts,planner,runs,conversations}.py` | #37: remaining nonpilot consumers of caller-owned native connections. #88: converge composition without deleting the supported compatibility path prematurely. Pilot follow-up selection, supersession, messages and transcript adoption already belong to the selected unit. | Session/operator/campaign/settings scope, stale message checks, exact ordering and malformed-history behavior. |
| `access.py`, `workspaces.py`, `staff.py`, `agent/capabilities.py`, `adapters/local_access.py` | #37: remaining provisioning, advisory catalogue and nonpilot permit/native readers. Staff session commands use the typed store. #87: external authority/client adoption. #88: entrypoint resolution/wiring. Selected placement access uses the original permit and same-unit preimage; legacy `CommandAccess` is not asserted migrated. | Current grants, full owner/workspace/installation, expiry/revocation, original command identity, fail-closed disclosure and permit fences. |
| `measurement.py`, `performance.py`, `instruction_tests.py`, `learning.py` | Viewer, review, experiment and finding commands use scoped units. Retained agent workflows borrow evidence records on their native transaction. Their named pilot context reads and required startup/adoption are in #86, not postponed. | Attribution and denominators, exact comparison/takes identities, current corrections, source versions, scoped evidence and reviewed reuse. |
| `campaign_setup.py`, `delivery.py`, `adapters/simulated_setup.py` | #37: setup, delivery and recommendation units are adopted. The simulated provider's resource store is a separate provider effect boundary. | Exact approved package/account/action, zero dispatch on denial, received versus unknown outcomes, no repeated uncertain effects, report grain/tagged attribution. |
| `assets.py`, `publications.py`, `recovery.py`, legacy media helpers in `handoff.py` | #37: native private catalog/blob records, asset integrity and whole-store recovery. Publication grant and viewer writes use scoped units. #87/#88: external asset boundary and remaining media wiring. Selected logical media facts do not establish object-storage readiness. | Immutable scope/digest/filename, current publication access, historical approval evidence and restore invalidation. |
| `migrations.py`, `workspaces.py`, `adapters/sqlite_schema.py`, `sqlite_workspace_admission.py`, `sqlite_planner_startup.py` | Shared adapter startup owns the former constructor schema and adoption. #37 owns the remaining native storage graph, including the provisioning/recovery migration bindings and future schema allocation. | Identical migration names/checksums, key/uniqueness/nullability refusal, local-only adoption, viewer ambiguity/quarantine, provenance recovery and no history rewrite. |
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
