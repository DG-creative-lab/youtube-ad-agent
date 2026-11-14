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
