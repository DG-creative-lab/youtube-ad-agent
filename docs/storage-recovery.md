# Hosted persistence and private assets · first #37 slice

13 November 2026 · [Issue #37](https://github.com/DG-creative-lab/youtube-ad-agent/issues/37) · [Staff boundary](hosted-access-boundary.md)

## Supported topology

A2a adds schema version 3 for foreground provider connection/verifier,
reconnect-operation and immutable selection metadata. Raw keys are absent from
SQLite and backups. Backup copies and restored stores revoke all connection
authority, including local operator connections without a staff-session table;
selections/domain history remain intact. No inference ledger or provider vault is
added by this migration. [Foreground contract](openrouter-session-contract.md)

This slice targets one application instance/worker with SQLite and a private
filesystem on the same durable local volume. SQLite serializes competing writers;
commands retain expected-revision conflicts and existing bounded lock waits.
The portable demo retains its SQLite/Path composition. No hosting, managed
database, customer migration or provider connection is activated.

Multiple replicas, network-mounted SQLite, object storage/CDN, large-file
streaming and production workload/SLO sizing remain outside this verified
topology. #37 stays open for the chosen hosted composition and its acceptance.

15 November: [hosted topology decision v1](hosted-topology-decision.md) was
accepted in merged PR #73, closing #59 as a design decision. It selects Frankfurt
Vercel Python ASGI + Neon Postgres + private Vercel Blob; no hosted composition
is activated. #37 remains open.

The E37a.1 native SQLite seam adds `CampaignDrafts.write_unit()`, owning a new
connection, `BEGIN IMMEDIATE`, commit/rollback and close. Standalone `save()` and
`PlacementAgent._commit_turn()` use it. `save(connection=db)` borrows the caller's
transaction without committing, rolling back or closing it. The planner retains
its tool savepoint and commits draft, step, terminal status/outcome and assistant
reply together. Reservation, inference, received receipts, classification,
report capture and foreground authority refresh retain their separate phases;
failed final writes recover from the original received receipt on explicit resume.
Historical JSON, approvals, fingerprints and receipts are not rewritten.

PR #74 merged this first write-unit seam. PR #75 merged E37a.2, the concrete
`campaign_agent/adapters/sqlite_drafts.py` store on the caller's native SQLite
connection. `CampaignDrafts` uses it for seed existence, latest/exact raw snapshot
reads, seed/placement/fresh-brief/instruction revision appends and the two fixed
client/brand/campaign/reference-scoped catalog fact lookups. Snapshot JSON
serialization, ownership/access checks, approvals, catalog registration/backfill
and DDL stay in their existing application owners; the store never opens,
commits, rolls back or closes a connection and preserves raw snapshot text.

E37a.3 ([#76](https://github.com/DG-creative-lab/youtube-ad-agent/issues/76))
adds `SQLiteConversationStore`, borrowed by `CampaignConversations` for raw session
rows, joined message histories, message appends, job context, latest message/count,
session creation/settings and fully client/brand/actor/campaign-scoped list rows.
Full tuples retain missing versus present malformed/NULL values; IDs, timestamps,
raw settings/content/outcomes and native conflict behavior are preserved.
Application code retains JSON, current access and private ownership checks, model
and stale-follow-up policy, bounded context, verified replies and title filtering.
Its constructor DDL/legacy backfill and `begin()` running-run selection/status/
outcome supersession writes stay in place, on the same caller-owned transaction.

These seams are SQLite-only. Eager initializers, planner/default/job/turn records,
remaining conversation legacy/supersession SQL, access/permit reads and media retain
their current SQL and filesystem owners; this is not the complete same-store graph.
PostgreSQL repositories, transactions and conformance require a separately
accepted slice; there is no
backend selector or `DATABASE_URL` interpretation. Foreground provider sessions,
quota ledger, semantic receipts and permit reads must move as one graph before
Postgres inference. Private Blob integrity-before-bytes, coherent DB/blob
recovery, all-campaign restore admission and hosted activation remain gated.

## Migration boundary

`product_schema_migrations` records ordered names and checksums. Ownership schema
adoption is migration 1; immutable private asset metadata is migration 2.
`BEGIN IMMEDIATE` protects DDL and journal entries together. Failed upgrades
roll back; concurrent migrators serialize; unknown/changed/noncontiguous history
is rejected. Known unversioned ownership is admitted without rebuilding campaign
JSON or inferring customer ownership. Unknown ownership shapes/unbound brands
need explicit reconciliation.

Admission checks ownership column types, primary keys, required nullability and
full case-sensitive uniqueness, including the workspace ID. Partial, expression
or wider composite indexes cannot replace the required key. Same-column tables
with weaker constraints are refused without schema/data changes. These checks
also apply to already-journaled stores, status and recovery validation, so an
earlier weak admission cannot bypass them. The original nullable SQLite TEXT
primary-key declaration for campaign IDs remains compatible; existing null
identities are rejected and native provisioning requires a nonempty string ID.

This journal covers ownership and assets. Existing domain-specific legacy
migrations remain with their owning commands. Tests migrate authored learning
history and compare all original table rows through restore.

Use the release matching the store/bundle schema. Before first adoption, retain
a prior-release SQLite backup or stopped-service volume snapshot. Later upgrades
take a verified backup with the currently compatible release. SQL downgrade is
unsupported; rollback restores a separate copy with the matching release.

## Private media

`AssetStore.import_catalog` is trusted provisioning requiring current workspace
configuration access and native campaign ownership. There is no new upload,
tenant assertion, catalog selection or filesystem browsing endpoint. The fixture
imports authored media and pins its catalogs in its own bootstrap table; restart
reads private blobs rather than the source folder.

Each catalog freezes example metadata and named asset digests/sizes. Database
triggers prohibit changing/deleting catalogs and blob versions or inserting an
unprovisioned owner. New media produces a distinct catalog. Original catalogs
remain readable under their original IDs; approvals and fingerprints are never
rewritten. Server composition explicitly pins the catalog it uses. Automatic
promotion and customer onboarding remain future work.

Blob paths use a client/brand owner hash plus content digest; different owners
have separate directories even for identical bytes. Reads reject traversal,
symlinks and nonregular files and verify byte count/hash. Flushed temporary files
are published atomically without overwriting existing blobs. An aborted import
can leave unused private bytes, but no accepted partial catalog. Garbage
collection is deferred to preserve historical references and in-progress backups.
Individual blobs are bounded to 64 MiB in this adapter.

Staff downloads retain current campaign access and exact hash checks; public
bytes require the existing publication grant. The media-read port preserves
logical filenames/content hashes. Captions derive from frozen catalog metadata.
Neither API returns filesystem paths or usable blob URLs.

## Operator backup and restore

These are privileged whole-store tools, not tenant APIs. Bundles contain private
histories for all clients. Keep them outside Git and web-served directories.
Local permissions restrict access; encryption, offsite replication, retention,
scheduling and accepted recovery targets remain operations work.

```sh
.venv/bin/python scripts/product_storage.py status --db .local/hosted-access-fixture.sqlite3
.venv/bin/python scripts/product_storage.py migrate --db .local/hosted-access-fixture.sqlite3
.venv/bin/python scripts/product_storage.py backup --db .local/hosted-access-fixture.sqlite3 --assets .local/hosted-access-fixture.assets --out .local/backups/checkpoint-01
.venv/bin/python scripts/product_storage.py verify --backup .local/backups/checkpoint-01
.venv/bin/python scripts/product_storage.py restore --backup .local/backups/checkpoint-01 --out .local/restored/checkpoint-01
```

Use the Python environment containing `requirements-test.txt`; this checkout's
verification also uses `.local/hosted-venv`. SQLite's online backup API obtains
one committed snapshot; its referenced immutable blobs are then copied. The
manifest records the database hash and exact scoped inventory and is written
last. Both commands reject existing destinations. Corrupt/missing bytes,
references, hashes, versions or integrity checks block restore. Hashes establish
consistency, not authenticity against replacement of an entire bundle.

Restore writes new `state.sqlite3` and `blobs/` paths. It preserves revisions,
approval actors/timestamps/snapshots, experiments, evidence, findings, catalog
identities, setup plans and receipts. Staff sessions are cleared and copied
public grants are revoked, preventing rollback from reviving old access. Source
state is untouched. Fresh sign-in is required; verified setups retain their
historical destinations. Publication renewal remains deferred, so revoked links
use the existing new-revision/export conflict.

```sh
.venv/bin/python scripts/hosted_access_fixture.py --db .local/restored/checkpoint-01/state.sqlite3 --assets .local/restored/checkpoint-01/blobs
```

Before real activation, reconcile provider operations that may have occurred
after backup. Restoring local receipts cannot roll back an external provider.

The current recovery command does not implement the future project store
incarnation/reconciliation overlay. [PR #69/#72 product and integration rules](project-access-integration.md#restore-admission-quarantine-and-run-fences)
require a fresh incarnation and positive independent reconciliation for every
restored private campaign **before** choosing standalone/project policy, even
when the restored backup has no link/project rows or predates project schema.
Fresh staff membership/source permission and absent links cannot reopen access.
#37 must implement that admission fence before project runtime or the proposed
hosted import/cutover; old pending work and uncertain receipts remain historical,
never reactivation authority. The [future checkpoint/cutover/rollback contract](hosted-topology-decision.md#db-plus-blob-checkpoint-cutover-and-rollback)
also binds one database snapshot to its exact immutable object inventory and
requires compatible releases, quarantine and measured recovery drills.

## Offline evidence

`tests/test_product_storage.py` exercises exact learning/approval/fingerprint
preservation, migration rollback/idempotency/unknown history/concurrency,
immutable media versions, cross-client/brand catalogs and HTTP media isolation,
corrupt/symlink/nonregular blobs, competing native revision writes, two-client
restore with fresh authority, tampered bundles/occupied destinations, and an
online backup while a second connection holds an uncommitted write. All data
is authored; no identity, cloud storage, customer or provider service is called.

Verification on this slice: all **206 offline tests** passed, including 12 storage
cases. The in-app browser played both private-store editing takes and saved a
completion. CLI backup/restore recovered 15 scoped blobs into a separate store.
Old staff/public authority was rejected; fresh sign-in showed client A’s approved
revision 2 and client B’s independent revision 1. Native revision, approval, media
and viewer event rows matched the source byte for byte.

14 November review verification rejects 17 incompatible same-column ownership
schemas, including already-journaled weak stores, without modifying data/schema.
Supported constrained legacy tables still migrate; a second client cannot bind
the same workspace. Existing learning/approval/fingerprint recovery checks pass.

14 November reconciliation after PR #45: the storage branch now includes main
`3fe9c1c`, with its uncommitted work preserved. All 206 offline tests passed with
ResourceWarning reporting enabled and none emitted; the planner build passed.
A fresh two-client CLI status/migrate/backup/verify/restore drill recovered 15
scoped blobs, unchanged domain rows/approvals/fingerprints, fresh authority and
private media access. Client B retained revision 1 and no client A conversation.
The source store was unchanged. All effects were local simulations.

### Foreground inference accounting

Migration 4 appends `inference_ledger` without rewriting previous domain, approval
or semantic-receipt histories. It retains the original scoped selection and exact
request/settings hashes, committed reservation/dispatch state and sanitized cost
receipt. Actual nanodollars use decimal text so an anomalous provider value is
retained without SQLite integer overflow; application calculations use integers.
Run/day budget aggregates and unresolved concurrency include retained old rows.

Whole-store backup and restore copy this ledger unchanged. Authority invalidation
still revokes staff sessions and provider connections; it must not erase, release
or rebind uncertain spend. A pre-ledger requested operation is never inferred to
be unsent. A restored or reconnected session cannot reset aggregate accounting.
Received semantic receipts can recover through the original application checks;
possibly dispatched completions are not retried to recover missing content.
