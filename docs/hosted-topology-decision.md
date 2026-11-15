# Hosted topology and first migration contract · proposed v1

15 November 2026 · E41a / [#59](https://github.com/DG-creative-lab/youtube-ad-agent/issues/59) · owner: #41 operations, with #37 storage and #36 access.

This is a concrete design proposal for human acceptance. It provisions nothing,
authorizes no spending and establishes no deployed, customer, performance or
recovery conformance. The supported application remains the zero-cost local POC:
one worker, SQLite, immutable private files and offline inference. Historical
research on #59 was not accepted implementation. Acceptance of this document
selects a reference design; a separate task contract must authorize each build.

## Selected reference and eligibility

Choose **two Vercel Python ASGI projects in Frankfurt (`fra1`), Neon Postgres in
`aws-eu-central-1`, and a private Vercel Blob store in `fra1`**. Both projects use
the same versioned application command implementation and database. The staff
project serves the planner and staff API on one origin; the viewer project exposes
only publication-scoped comparison/media/events. Static bundles contain authored
public UI assets, never imported private media. Retain request-driven foreground
advances; no scheduler, queue, durable worker or provider key vault is selected.

| Mode | Eligibility and activation policy |
| --- | --- |
| Current application/demo | Local only; no hosting account or payment required. Keep SQLite/Path composition and existing offline behavior. |
| Future hosted authored POC | Hobby plus Neon Free may be evaluated only for permitted personal/non-commercial use, bounded fixtures and verified quotas. This document does not establish this employment-application demo's eligibility. |
| Future customer pilot | Reference plan is separately authorized paid Vercel Pro with Neon capacity/backup plan chosen against the acceptance targets below. No customer pilot on Hobby by project policy. Obtain current terms/use, account availability, privacy, residency, retention, budget and operator acceptance first. If no eligible approved budget exists, remain local; no trial, upgrade or purchase is implied. |

Current [Vercel terms §4](https://vercel.com/legal/terms) limit Hobby to personal
or non-commercial use. The freshly retrieved Hobby/fair-use pages (updated
12 November) omit the older commercial-use paragraph still present in search
excerpts; use the current terms, not cached excerpts, for this decision. They do
not prove this particular use eligible. Terms §3 also describe model-training
defaults for Hobby/trial content and an opt-out; #40/#41 must accept actual
terms/settings before customer material. Plan selection is not legal clearance.

Frankfurt is the selected colocation default, not a UK-only or EU-only processing
guarantee. [Vercel regions](https://vercel.com/docs/regions) maps `fra1` to
Frankfurt; [Neon regions](https://neon.com/docs/introduction/regions) offers
Frankfurt Postgres and Object Storage, whereas London currently has Postgres
without Object Storage. Both storage products fix region at creation. CDN caches,
identity/authority services, logs, backups and model providers need their own
approved location/data-flow inventory. A residency requirement incompatible with
this design blocks activation and requires a new decision.

## Official evidence checked 15 November 2026

These are public documentation facts, not observations of an account. Recheck
them before provisioning; free quotas are shared/limited, not an availability SLA.

| Surface | Current primary evidence and consequence |
| --- | --- |
| Vercel compute | [Python runtime](https://vercel.com/docs/functions/runtimes/python) supports ASGI/WSGI and Python response streaming. [Function limits](https://vercel.com/docs/functions/limitations) gives Fluid Hobby 300 s; Pro default 300 s, GA maximum 800 s (1800 s is beta). Duration includes streaming. Request and buffered-response cap is 4.5 MB; streamed responses are explicitly exempt from the response cap. No exception to the request cap is inferred. |
| Files and cold starts | [Runtimes](https://vercel.com/docs/functions/runtimes) specifies a read-only filesystem and up to 500 MB writable `/tmp`; archived functions add cold-start delay. Scratch is never the database, permanent asset store or backup. Neither compute nor Neon wake-up latency has been measured here. |
| Hobby capacity | [Hobby](https://vercel.com/docs/plans/hobby) lists 4 CPU-hours, 360 GB-hours memory, 1M invocations, 100 GB fast transfer and 10 GB origin transfer. Limit exhaustion can pause service. These allowances do not establish customer-pilot entitlement. |
| Neon Free Postgres | [Plans](https://neon.com/docs/introduction/plans): 100 projects, 10 branches/project, 100 CU-hours/project/month, 1 GB Postgres/project (20 GB overall), 5 GB public transfer/project/month; scale-to-zero after 5 minutes cannot be disabled. Free restore history is at most 6 hours/1 GB changes, with one manual snapshot; scheduled backups require a paid plan. Exceeding compute/transfer suspends compute; storage growth fails at the cap. |
| Postgres pooling | [Connection pooling](https://neon.com/docs/connect/connection-pooling) uses PgBouncer transaction mode, accepting up to 10,000 clients, not 10,000 simultaneous database transactions. Avoid session `SET`, session advisory locks and SQL `PREPARE`; use explicit transactions and schema names. Migrations and `pg_dump`/`pg_restore` use direct connections. |
| Selected private media | [Blob](https://vercel.com/docs/vercel-blob) supports private authenticated reads, distinct pathnames and a chosen fixed store region. [Python SDK](https://vercel.com/docs/vercel-blob/python-sdk-reference) provides `stream_blob`, async context cleanup and chunks up to 64 KiB. Framework examples are not application authorization. |
| Blob capacity/cost | [Pricing](https://vercel.com/docs/vercel-blob/usage-and-pricing): Hobby includes 1 GB-month, 10K simple/2K advanced operations and 10 GB Blob transfer; excess blocks access rather than purchasing overage. Hobby rates are 20 simple/15 advanced operations per second. Service permits objects up to 5 TB, but this design retains 64 MiB. Private proxy delivery consumes both store-fetch and function-delivery resources; regional Pro usage is chargeable. |
| Alternative now available | [Neon Object Storage](https://neon.com/docs/storage/overview) includes 5 GB/project Free, 5 GiB single-request/10 GiB multipart maximum. [Private buckets](https://neon.com/docs/storage/buckets) require credentials; [S3 compatibility](https://neon.com/docs/storage/s3-compatibility) includes Range. It is a real contender, not an unavailable feature. |
| Deployment environments | [Environment variables](https://vercel.com/docs/environment-variables) allows broad Preview scopes, branch overrides and integration-injected credentials; custom environments can inherit defaults. A preview label alone does not isolate credentials or customer data. |

Choose Vercel Blob for its documented Python private-read/cleanup path and
same-platform media proxy; retain separate DB/blob checkpointing rather than
depend on storage-branch semantics. Neon Object Storage is rejected for this first
port because inherited branch objects require additional disclosure/restore
analysis and its S3 subset adds a second adapter surface. It may replace Blob
only through a later decision, not a runtime fallback. A public Blob store or
direct signed URL would bypass per-request native revocation checks. Local SQLite
on function scratch loses durability and cross-instance serialization. A permanent
VM with durable SQLite remains a different operational design; it is not this
selected managed-Postgres path. No claim is made that these alternatives are
technically impossible or that Blob is universally cheaper.

## Staff, public and credential boundary

Use exactly two configured HTTPS origins, illustrated by
`https://staff.campaign.example` and `https://viewer.campaign.example` (reserved
example names, not provisioned domains). No wildcard deployment-host admission.
Each entrypoint pins its own canonical host and scheme; direct/preview aliases
must fail or redirect keyless navigation before private handling. The Vercel
ingress adapter must establish trusted external host/scheme from authenticated
platform context, reject conflicting/duplicate host/forwarding fields and ignore
client-supplied forwarding assertions. Do not enable blanket proxy trust. #41/#42
must demonstrate this on the actual ingress; today's loopback Uvicorn fixture
disables forwarding trust and cannot be exposed as the hosted server.

Preserve `HostedApplication`'s exact Origin/Fetch Metadata checks, JSON field and
800,000-byte request bound, CSRF proof and no-store/security headers. Staff uses
the host-only `__Host-gp_session` Secure/HttpOnly/SameSite=Strict cookie with path
`/` and no Domain. The separately reviewed OIDC callback must handle its own
state/nonce and cookie transition; this proposal does not invent a callback API
or relax command CSRF. The viewer has no staff routes, even with a copied cookie;
do not enable credentialed cross-origin CORS between these origins.

Gateplane owns identity/current membership/current decisions through #36 and the
real maintained issuer/client/service composition. Product tables own immutable
workspace/campaign relationships and disclosure intent, never a competing
membership or login directory. Join each original decision deadline, verified
session, native owner/revision and current relationship immediately before a
private response or commit. Keep the accepted maximum five-second decision-use
window; no distributed atomic-revocation claim. #55 also needs producer #79
registration, #81 native client and #83 composed service/recipient/revoke
acceptance, plus #36/#37 agreements. The merged PR #72 artifacts do not supply
those runtime capabilities. Follow [integration v1](project-access-integration.md)
and [product rules](project-sharing-contract.md); never substitute campaign
targets for workspace/project/resource actions or invent recipient lookup APIs.

Retain browser active-tab BYOK and the existing explicit same-origin POST allowlist,
fresh keyless bootstrap/CSRF binding, immutable server selection and receipt-first
recovery. Ingress, errors, APM, traces, logs and replay tools must suppress credential
headers and request bodies before capture; no key in URLs, responses, prompts,
SQLite/Postgres, backups or frontend build variables. Platform DB/Blob credentials
are infrastructure secrets, not model keys. The real OpenRouter path stays unwired
until [#70's foreground qualification](openrouter-session-contract.md) passes.
Request cancellation or timeout never proves a dispatched completion unsent.

Use separate production/preview database roles and stores, migration/backup roles
outside request handlers, and no browser database credentials. The public role
may only execute the narrowly scoped publication/media/event queries needed by
the viewer; deny staff sessions/provider selections/ledger/private history and
arbitrary table access. The staff role has the command-required grants and no DDL.
DB roles reduce exposure but do not replace native owner predicates and authority
joins. Prefer project-bound rotating OIDC for Blob as documented in its
[security guide](https://vercel.com/docs/vercel-blob/security); this is infrastructure
access, not tenant authorization, and grants no assumed per-viewer credential
scope. #40/#41 must prove effective privileges and credential lifecycle. Before enabling
previews, inspect effective environment/Marketplace connections and deny production
credentials at startup; use a separately seeded synthetic project/store, not a
branch copied from customer production. Untrusted PR builds get no production or
provider credentials. Preview cookies, issuers, origins and store incarnation are
separate; UI deployment protection does not authorize application commands.

## First bounded Postgres port (#37)

Today's constructors call `sqlite3.connect`, SQLite DDL and path migrations across
modules. Setting `DATABASE_URL` cannot port them. `HostedApplication._app` already
runs synchronous commands via `run_in_threadpool`; retain that boundary. Choose
[Psycopg 3](https://neon.com/docs/guides/python) synchronous PostgreSQL transactions
in the command worker thread, with one short-lived pooled-endpoint connection per
unit of work, automatic prepared statements initially disabled and guaranteed
close/rollback. Do not introduce JavaScript database
drivers, blocking SQL in the ASGI event loop, ORM identity rewrites or global
unbounded connection pools. Exact package/version and deployed ABI checks belong
to the implementation contract; no dependency is added here.

The first concrete caller is **`PlacementAgent.resume` → placement tool →
`CampaignDrafts.save(connection=...)`**, reached by the existing staff foreground
advance command. #37 owns a command unit-of-work/read-store seam shared by these
owners, a default SQLite adapter and an explicit PostgreSQL adapter. Its first
vertical slice supports an authored offline placement run from start/read/resume
through draft, step, conversation reply and replay, including all reads and catalog,
ownership/access context it uses in the same selected store. Unsupported PostgreSQL
commands fail explicitly. Do not dual-write, route related reads to SQLite or
advertise the partial graph as a deployable application. All remaining command
families must be ported/accepted before hosted composition can select Postgres.

The required transaction contract is:

1. Start/retry reserves original run/message/operation identities under scoped
   uniqueness; same input recovers its original result, changed input conflicts.
   Remote authority/report/provider calls remain outside write transactions.
2. A final transaction locks native campaign and run rows in deterministic order,
   reloads the owner, expected revision, original actor/session/mandate, supersession
   and current permit facts, then preserves the planner tool savepoint. Domain
   draft changes, `agent_steps`, terminal run/job state and conversation reply
   commit together; tool failure rolls back its partial changes before the saved
   error result. Concurrent same-revision saves yield one accepted revision and
   one native conflict, never two revisions from one expectation.
3. PostgreSQL replaces `BEGIN IMMEDIATE` with explicit row/guard locks and CAS,
   not a naive textual SQL substitution. Port `?` bindings, pragmas, rowid/DDL,
   affinity, upserts, partial indexes, constraints and immutable-owner triggers
   deliberately. Preserve native case-sensitive IDs/full-owner joins, integer
   bounds and null rejection. A migration lock and ordered checksummed journal
   serialize schema owners; existing four SQLite migration checksums stay intact.
4. Before enabling foreground inference on Postgres, port `InferenceLedger` and
   receipt writers as one graph. A transaction-scoped installation guard row
   serializes admission/settlement aggregates across actor/client/run quotas;
   lock it before campaign/run rows. Unique `(run_id,position)` alone cannot
   prevent write-skew overspend. Keep original settings/request hashes, selections,
   dispatch marker, semantic receipt and uncertain reservations. Reservation and
   dispatch marker are durable before I/O; received cost evidence can survive a
   late authority denial without authorizing a draft. No automatic replay after
   unknown commit/dispatch: reload original operation first, reconcile if needed.
5. Retry serialization/deadlock failures only for known-uncommitted local units,
   with a bound and refreshed current authorization. Never retry external I/O in
   a transaction retry. Proposed local lock timeout is 1 s, statement timeout
   5 s and at most two transaction attempts within the caller deadline; validate
   these values against recovery/latency evidence before activation. Use `SET LOCAL`
   and explicit schemas, no session-level state on transaction-pooled connections.

Import historical JSON/snapshot/receipt text as exact UTF-8 text and SQL blobs as
bytes; keep an exact export digest inventory. JSONB may index a separate derived
projection, never replace raw snapshots. Preserve actors, IDs, timestamps, request
hashes and the bare native package fingerprint (its ASCII-escaped canonicalizer
differs from project-profile hashing). Keep `actual_nanos` as lossless decimal
text and application integer arithmetic; no float/SQL integer narrowing. Existing
approval and publication authority must not be recalculated from imported text.

## Private immutable media contract (#37/#40/#41)

Keep `AssetStore`/`CatalogMedia` logical names and frozen catalog identities.
Trusted provisioning writes an owner-scoped immutable object key derived from
the existing owner hash and content digest under an environment/store namespace.
Postgres records full native owner/catalog/version, logical name, SHA-256, exact
byte size, MIME and opaque internal store/key reference. No cross-owner dedup or
browser-selected storage path. Stage bytes, verify full hash/size, publish without
overwrite, then atomically register the entire catalog in the database. A crash
may leave unreferenced private bytes, never accepted partial metadata. Keep old
catalogs/keys while history or any backup references them; GC is separately gated.
Immutability is our conditional-create/no-overwrite policy plus hash verification,
not a provider WORM guarantee; Blob supports explicit overwrite operations.

Staff media requires current campaign/source authority and, once implemented,
the exact #55 incarnation/project/link/disclosure/resource joins. Public media
requires the active unexpired publication and its exact frozen content/media;
project revocation does not silently unpublish a separate publication. Neither
route exposes Blob URLs, credentials or arbitrary media selection.

**Verify before releasing any bytes.** Use Python `stream_blob(access="private")`
to spool at most 64 MiB plus one overflow sentinel into a private, exclusive
request tempfile in `/tmp`, hash/count it fully, then close the upstream stream.
After verification, reacquire fresh current authority outside writer locks and
recheck native/publication/project facts at the last response boundary. Only then
stream the verified file through ASGI in bounded chunks. This preserves today's
`read_blob` full-check-before-return invariant; hashing bytes already sent would
weaken it. Use isolated request-owned directories and the same verified file
handle. Cancellation/error/finally closes/unlinks its own scratch; a cleanup owner
may reclaim a crashed request's reservation only after proving it orphaned, never
by sweeping shared `/tmp` or another process's live files. Count orphan reservations
against capacity until safe cleanup; otherwise refuse admission. No scratch reuse
across requests or retained authority.

Proposed limits: four concurrent media spools per instance (256 MiB plus bounded
overhead), 70 MiB scratch reservation per request, 30 s fetch/verification deadline,
60 s total media invocation deadline, and admission refusal when capacity is
unavailable. The 500 MB scratch cap includes all temporary users; #41 must measure
headroom and prove admission across the actual process model, or reduce the cap.
Functions may multiply under scaling, so #41 also requires global request/rate/
transfer controls and an accepted usage ceiling. No new upload endpoint: trusted
operator import bypasses the function request body and is separately authorized.

After the same full verification and authorization, support one valid byte range
with correct 206/Content-Range/length; reject invalid/unsatisfiable/multipart ranges
with 416, and authorize HEAD identically. Avoid repeated full-download amplification
with bounded per-session/publication rates. Never return unverified upstream
partial bytes. Private and publication responses use `Cache-Control: private,
no-store`, CDN no-store, nosniff and no-referrer; no cache hit or 304 bypasses
authorization. Blob's internal immutable-byte cache can remain, but cannot cache
an application allow. **No presigned download URLs are issued**: residual signed-link
validity is zero by design. Already delivered bytes/in-flight responses cannot be
recalled, and external authority still has the bounded decision-use window.
Test a streamed response above 4.5 MB on the actual Python ASGI ingress before
activation; SDK/platform support alone is not evidence that this composition works.

## DB plus blob checkpoint, cutover and rollback

#37 owns the importer/recovery format; #41 owns protected backup copies, keys,
monitoring and a named recovery operator. Proposed checkpoint format binds source
release/schema/migration digests, database dump digest, exact raw-row inventory,
store/catalog/object inventory and hashes, checkpoint ID and completion marker.
Encrypt and authenticate offsite backups with separately controlled recovery keys;
hash consistency alone does not authenticate a replaced bundle. Agree retention,
deletion/export and backup-key access with #40 before real data.

1. Rehearse on authored two-client histories. Verify the existing whole-store
   SQLite bundle, import its snapshot into an empty quarantined PostgreSQL schema,
   copy/verify every referenced immutable object into a new private namespace and
   compare every historical snapshot/approval/fingerprint/receipt/ledger identity.
   Mark complete only after DB constraints, reference closure and bytes all pass.
2. For hosted backup, take a consistent database snapshot/dump over a direct
   connection; enumerate that snapshot's immutable object references and copy them
   before the authenticated manifest completion marker. Freeze GC; newer objects
   are irrelevant. Neon PITR alone does not establish a matching Blob checkpoint.
3. For cutover, stop admission, drain known requests and reconcile possibly
   dispatched provider effects without replay. Record the final checkpoint and
   last operation IDs, import/verify, apply restore invalidation and reconciliation,
   then switch **both** origins/store configuration to one release/database/blob
   checkpoint. Keep the old source stopped/read-only. No simultaneous writers.
4. Every controlled restore/import creates a fresh store incarnation and clears
   sessions/revokes provider connections and public grants before exposure.
   Quarantine copied audience/disclosure/link state. Require positive independent
   current-incarnation reconciliation for **every campaign before choosing
   standalone/project policy**, including absent links, empty project tables and
   pre-project-schema backups. Fresh membership/source permission is insufficient.
   Old permits/cursors/pending runs/operation success cannot reactivate access;
   selected new recovery requests require #36's independent recovery/recipient
   decisions. Preserve old manifests and uncertain ledger receipts unchanged.
5. Reject unknown schema/format/checksum or incomplete objects. Restore into a
   fresh private target, never over the running store. A release declares its
   readable/writable schema range and refuses unsupported combinations. Use expand
   then migrate then contract; no destructive downgrade or automatic SQLite export
   fallback. Before first new write, rollback may reopen the verified prior source
   only through the same fresh-incarnation/reconciliation process. After new writes,
   rollback requires a new complete checkpoint and compatible release/forward fix;
   replaying an old database discards history and may repeat external effects.

Today's [local recovery](storage-recovery.md) verifies SQLite/files and invalidates
staff/provider/public authority; it does **not** implement project incarnation or
all-campaign reconciliation. PR #69/#72 require that fence before project runtime
or hosted migration activation. Do not label the present recovery command safe
for post-project rollback without the #37 extension.

## Implementation gates and proposed acceptance

All numbers below are proposed release targets, not measurements or provider SLAs.
Use authored fixtures for initial acceptance; separately authorize account, traffic,
scope and cost for deployed checks. A human accepts the design only at this stage.

| Owner | Required evidence before that capability is enabled |
| --- | --- |
| #37 storage | First native placement UOW on SQLite and Postgres: start/read/save/replay/reopen; competing same-revision commits; late revoke/supersession; failure between draft/step/reply commits; exact raw historical inventory and fingerprints; no split reads/writes. Then port remaining writer/read graphs, atomic ledger admission/receipt races and private media corruption/range checks. One owner allocates future schema slots after rebase. |
| #36 + #55 | Real issuer/client/service, producer #79/#81/#83 agreements, exact original-deadline/recipient/revoke joins and bounded request counts; deny cross-client/brand/project/source substitutions through every direct and tool/media entrypoint. Runtime remains blocked despite merged A3a artifacts. |
| #38 execution | Foreground restart/timeout/unknown-receipt recovery with original actor/cost identity and zero redispatch; no browser-independent execution. Unattended mandates, queues and durable workers need a separate design/acceptance task. |
| #40 privacy | Approved media rights, customer retention/export/deletion and backup policy, sanitized telemetry/key-capture audit, actual terms/training settings and region/data-flow decision; no raw credentials in stores/logs/errors/backups. |
| #41 operations | Effective production/preview credential and DB-role isolation, canonical ingress/scheme/cookie/CSRF checks, migration lock/pool exhaustion and cold-start drill. Proposed warm non-provider command p95 ≤1 s, cold p95 ≤5 s at 10 concurrent staff requests over 100 authored samples each; report wake-up/provider latency separately. Prove four-spool headroom, 64 MiB integrity before bytes and ≤60 s bounded delivery on the agreed network; quota/admission denial must remain usable. |
| #41 recovery | Proposed checkpoint RPO ≤24 h and restore RTO ≤60 min for ≤1 GB DB + ≤1 GB referenced assets. Restore twice into fresh targets; verify reference/hash closure, old-authority denial, missing-link and pre-project backups, partial reconciliation, legitimate new recovery and unchanged uncertain costs. Record actual elapsed times and compatible releases; Free PITR is not this backup plan. |
| #42 pilot release | End-to-end two-client staff draft/approval/export → separate viewer playback/events → report/restart; stolen cookie/origin/forwarded-host/preview denial, >4.5 MB streamed media, cancellation and current revocation before bytes. All-campaign restore fence and fresh authorized recovery succeed. Accept eligible plan, budget, capacity and named operator before any customer traffic. |
| #70 provider activation | Current foreground metadata/charge/route/DNS/slow-stream bounds, request-local key redaction and uncertain receipt reconciliation under the separately authorized provider scope/cost. No provider calls are authorized by #59. |

Source inspection for this proposal covered `hosted.py`, `staff.py`, `assets.py`,
`recovery.py`, `migrations.py`, `agent/planner.py`, `agent/run.py`,
`scripts/campaign_drafts.py`, `inference_ledger.py` and the access/project/foreground
agreements. Document link/scope/whitespace checks establish document integrity
only. No database migration, service, media performance, browser, provider or
deployed check ran for this decision. Independent review/verification and current
unchanged Python/planner CI must name the final head/tree in factory evidence.
