# YouTube project access integration agreement v1

15 November 2026 · A3a-contract-55 v1 · [Issue #55](https://github.com/DG-creative-lab/youtube-ad-agent/issues/55)

This is a **proposed artifact agreement** for #36/Gateplane and #37 owner acceptance.
It prepares native profiles and reproducible synthetic examples. It registers no
producer policy, adds no application permission, command, route, migration or UI,
and establishes no real service, recipient, persistence or recovery conformance.
The [human-accepted product rules](project-sharing-contract.md) remain the product
boundary, including every-campaign recovery and absent-link fail-closed behavior.
Source baseline is `d409d7b96c3e2313f961af7fd78f0523ed1b4418` (merged PR #71).

## Profile and unchanged producer boundary

The closed [profile](../campaign_agent/contracts/youtube-project-v1.json) is
product-owned data. The [wire provenance](../campaign_agent/contracts/README.md)
pins producer `d8eb4f4073753573fc809a557521e4428719ea1d`, schema Git blob
`9bfc7650019f5fe9cb852cbcba088557e01366fd`. The producer schema is unchanged.
Product-profile data is neither a wire-schema fork nor registration approval.
The existing campaign-only `AccessRequest`, `GateplaneAccess`, `CommandPermit` and
`CAPABILITIES` cannot consume these project records as runtime authority.

| Native action family | Proposed wire capability | Effect | Native target / ID |
| --- | --- | --- | --- |
| create | youtube:project.create.v1 | write | workspace / workspace_id |
| list | youtube:project.list.v1 | read | workspace / workspace_id |
| read | youtube:project.read.v1 | read | project / project_id |
| rename | youtube:project.edit.v1 | write | project / project_id |
| audience.list | youtube:project.share.v1 | read | project / project_id |
| audience.set, audience.revoke | youtube:project.share.v1 | write | project / project_id |
| campaign.link, campaign.unlink | youtube:project.link.v1 | write | project / project_id |
| relationship.link, relationship.unlink | youtube:campaign.project_link.v1 | write | campaign / campaign_id |
| archive, restore | youtube:project.archive.v1 | write | project / project_id |
| resource.read | youtube:project.resource.read.v1 | read | project_resource / resource_ref |
| resource.share, resource.unshare | youtube:project.resource.share.v1 | write | project_resource / resource_ref |
| recover-campaign | youtube:project.recover.v1 | write | workspace / workspace_id |

These are twelve action families and eleven distinct capabilities; none uses
`external`. Project owners/IDs resolve from native records. Workspace create/list
and independent recovery resolve directly from `brand_workspaces`, with no dummy
campaign, campaign revision or campaign-target substitution. `relationship.*`
is the second campaign-side decision in the same link/unlink operation, not an
independent writer or a new public endpoint. First share reserves its opaque
resource_ref before authority I/O and atomically commits it with the disclosure.

Manager intent permits management only with its current decision; it grants no
campaign edit/approval. Editor use intersects project.read, editor intent, native
source grants and the original per-request draft mandate. Reviewer use intersects
the exact shared projection and current review/approval grants and native approval
rules. Shared package/media reads require project.read, resource.read and the
source campaign.read decisions, with the exact active link/disclosure/source
checks. A source deny cannot be replaced by a project allow. This profile assumes
separate fresh decisions, not an unavailable batch API.

## Closed native encoding and hashes

All command schemas and the native-state field set are explicit and closed in the
profile. Every native field is present; inapplicable fields are JSON null. The
full immutable owner is `(client_id, brand_id, workspace_id, installation_id)`.
The state binds owner, incarnation, action and native target, workspace revision,
project revision/state/epoch, actor-intent revision/digest, campaign revision and
snapshot digest, link generation, resource identity/revision, package fingerprint,
projection/media digest, disclosure revision, recipient-proof digest, reservation
identity and recovery state. Action-bound state intentionally gives different
resource versions to different actions over otherwise identical records.

| Value | Exact encoding |
| --- | --- |
| Native IDs and session IDs | Wire ASCII grammar `[A-Za-z0-9][A-Za-z0-9._:-]*`, 1..128 characters. No coercion, truncation or hash alias for unsupported existing longer IDs. |
| Positive counters | Decimal JSON strings `1`..`9007199254740991`, no sign, padding, float or boolean. Applicable counters are non-null. |
| Names | Original Unicode, 1..120 code points and <=480 UTF-8 bytes; Unicode category Cc controls rejected. No trim, case fold or NFC normalization. |
| Canonical bytes | UTF-8 JSON, sorted keys, compact comma/colon separators, literal Unicode, finite values, no trailing newline; floats, duplicate keys, lone surrogates and out-of-range integers rejected. |
| Large sets/manifests/proofs | Canonical digest references; no JSON serialized into scalar attributes and no private context or credentials. Intent/reference arrays are sorted and unique. |
| native_state_hash | `sha256:` followed by the lowercase SHA-256 of the closed canonical native state. |
| resource_version | `yp1:` followed by that same 64-character digest (68 ASCII characters; wire bound 128). |

The fixed 24 scalar attribute names/types are derived from the native state and
listed in the profile. `youtube:profile`, brand, incarnation, workspace revision,
recovery state and native-state hash are always present; all other keys remain
present with explicit null when inapplicable. Facts use
`source=youtube-project-sqlite-v1`, `attester_id=application_id`, exact native owner
and workspace. No attribute string exceeds the wire bound of 256 characters; the
wire permits 32 attributes but this profile permits exactly its own 24.
The full state must be retained/reloaded behind the digest. A digest or copied
schema-valid fact cannot establish ownership or a current permission.

The input preimage is the closed object
`{profile:"youtube-project-input-v1",command:<exact native command>,reservation:<null or exact reservation>}`.
Its SHA-256 uses the `sha256:` prefix. The command includes action and operation_id,
and only the declared schema fields. List fixes page_size=20 and cursor_digest
(null on first page). Recovery includes explicit standalone/project classification,
expected incarnation/campaign revision and every selected project/link/resource
reference and recipient-proof digest. The native command is the shared UI/tool
application representation. Future HTTP adapters must normalize parsed transport
fields to exactly it, rejecting unknown/duplicate query/body fields; headers and
secrets are not part of its preimage. No HTTP adapter is implemented here.

The subject preimage is the closed object
`{profile:"youtube-project-subject-v1",application_id,installation_id,tenant_id,brand_id,workspace_id,actor,session_id,target,capability,effect,input_hash,resource_version,native_state_hash}`.
Actor is the exact verified human wire Actor (null grant/delegator), and session_id
is the verified staff-session ID. `idempotency_key` is the subject digest without
`sha256:`. Request/correlation IDs correlate transport; they do not replace the
native operation_id. Any owner, session, action, command, incarnation or state
change changes the binding. These hashes are not signatures.

## Current authority and recipient handoff (#36/Gateplane)

The consumer must bind originating request/result application, installation,
tenant, workspace, actor, target, request/correlation IDs, input/subject hashes,
current human membership versions and all obligations. Project actions support
only `product.verify_current_resource.v1`. Other schema-valid obligations fail
closed; source-action obligations remain with the existing owner. Every nonallow
outcome is unusable. Human decisions require non-null tenant/workspace membership
versions, no grant and no parent grants. Local logout is an additional fence.

Each required decision retains its **original** deadline: the earliest of original
wall expiry, verified credential expiry, staff-session expiry and monotonic start
before authority check plus `min(valid_for_ms,5000)`. Never renew an earlier
decision while joining fresh decisions. Revalidate all bindings immediately before
private projection/bytes and inside the product commit transaction. Expiry or any
native mismatch denies the whole effect. Remote authority/provider I/O occurs
outside SQLite writer locks. Gateplane and SQLite are not one transaction;
external revocation has the accepted bounded decision-use window, and delivered
bytes cannot be recalled.

Recipient proof must bind exact external issuer+subject and canonical human
principal_id, application/installation/tenant/workspace, active principal and
current tenant/application/workspace membership versions, checked_at and a bounded
usable original deadline. Its canonical bytes use the profile's encoding and its
`sha256:` digest is the recipient_proof_hash; native state holds only the digest; the future native proof record retains its
immutable reference/versions, not a second membership authority. The
producer-supported lookup must be narrow and authenticated to the current manager
and staff session and a nominated opaque subject reference. Email guesses,
browser role strings, directory dumps, administrative routes and caller-supplied
membership proofs are unsupported. No lookup/public API is invented here.

Set, re-share and recovery require current eligible recipient proof. **Recipient
revoke semantics remain pending #36/product-owner acceptance**: whether removing
persisted intent requires the removed member still to be active must be decided
before runtime dispatch. The recommendation is removal under current manager
authority without requiring the removed member's active membership; this document
does not amend the accepted product rules or activate that recommendation.

List scans at most 20 candidates and returns at most 20 authorized metadata rows;
it never scans until full, reveals totals, audience counts, private previews or
actor-private histories. Each returned row receives a current project.read check.
The opaque cursor binds actor/session/full owner/incarnation/query and last scanned
identity, expires within 300 seconds and restarts on logout/security changes.
Proposed single-page ceiling is one workspace-list plus at most 20 project-read
decisions (21 calls), with bounded concurrency and a whole-response deadline.
This is an owner-review ceiling, not measured latency, an accepted aggregate
budget or an instruction to implement sequential remote calls.

## Durable operation and storage handoff (#37)

No schema slot is reserved, appended or applied here. Current ordered/checksummed
slots 1..4 remain byte-identical. The serial #37 owner refreshes the actual main
head, allocates the next free slot (5 is only the baseline candidate), reconciles
concurrent migrations, records accepted profile revision/checksum and obtains
independent storage acceptance before dispatch. One worker, local SQLite and
private immutable files remain the topology.

Every record below has NOT NULL case-sensitive full owner and native identity
columns unless explicitly nullable; comparisons use BINARY. Revision/epoch values
are positive SQLite integers bounded to 2^53-1 in storage and decimal strings on the
profile boundary. This is a proposed record/constraint agreement, not executable
DDL or proof today's SQLite schema enforces it.

| Proposed record | Exact identity, relationships and constraints |
| --- | --- |
| projects | Globally unique project_id PK; immutable full owner; composite UNIQUE(full owner,project_id); name; positive metadata revision/security_epoch; active/archived. Workspace FK binds all owner parts to native brand_workspaces. |
| project_intent_current + immutable intent_history | Key (full owner,project_id,issuer,external_subject); canonical principal_id, sorted bounded intents, positive intent_revision and active/revoked state. Project composite FK; current points to immutable history. Actor eligibility is current Gateplane data, not stored membership. |
| project_link_history | Globally unique link_generation PK; full owner/project_id/campaign_id; active/ended; positive revision. Composite native project/campaign ownership joins; partial UNIQUE(campaign_id) WHERE active. Ended generations cannot be reactivated; relink allocates a new generation. |
| project_disclosures | Globally unique resource_ref PK; full owner/project/campaign/link_generation; exact campaign revision/fingerprint/projection/media digest, positive resource/disclosure revisions; active/revoked. Composite project/link/source ownership references. Re-share cannot adopt an old generation or broaden an exact version. |
| project_recipient_proofs | Immutable digest PK, full owner/project/recipient reference, issuer/subject/principal identity, source membership versions and original checked/deadline metadata. This historical proof reference never substitutes for current eligible membership. Lookup/proof and revoke semantics require #36 acceptance. |
| project_operations | UNIQUE(full owner,actor_id,operation_id); operation kind, exact command request digest, immutable store_incarnation, reservation_id, optional proposed_project_id/proposed_resource_ref, pending/committed state and immutable result reference. Globally unique reservation/prospective IDs. No private content or permission in pending reservations. |
| project_audit | Globally unique event_id; full owner/native references; sanitized actor/action/revision/epoch/outcome and timestamp; append-only, no tokens, prompts or copied private package content. |
| project_run_manifests | Original run_id PK and full immutable actor/campaign owner, incarnation/project/security_epoch/link generation and exact used resource references. Existing run identity/receipt remains authoritative; manifest never grants permission. |
| project_store_security | Singleton current incarnation and fresh/restored/quarantined admission state; normal restart preserves incarnation. Separate history retains prior incarnations. |
| project_campaign_reconciliation | PK (store_incarnation,campaign_id), exact full owner, explicit standalone/project classification, selected project/new link generation/disclosure references, active reconciliation revision/audit reference. Positive current-incarnation record required for every restored campaign. |
| workspace_project_index | PK full immutable workspace owner; positive monotonic index_revision incremented atomically for candidate/projection/security changes; list native resource state uses this, never campaign revision. |

Require composite FKs **and** insertion/update triggers for immutable owner and
critical native/project/link/disclosure relationships where existing native keys
cannot support those composite FKs. Triggers must reject null/unknown owners,
foreign owner insertion/update and adoption even on connections with
`PRAGMA foreign_keys=OFF`. No parallel membership store, copied package payload,
provider credential or replacement approval store. Preserve original campaign
snapshots, approvals, fingerprints, attribution, experiments, findings, assets,
conversations, selections, receipts and ledger rows byte-for-byte.

Create's first `BEGIN IMMEDIATE` transaction resolves the native workspace and
reserves a non-authoritative operation keyed by full owner/actor/operation_id,
binding the exact authored command digest and server-generated reservation_id and
prospective project_id. It inserts no project/private content/audience permission.
The same exact retry reuses those IDs and record; changed input conflicts. No
user-input hash-to-ID derivation. Authority I/O uses the reserved IDs outside locks.
The final `BEGIN IMMEDIATE` reloads reservation, command digest, incarnation,
workspace/current native state and all original permit deadlines, then atomically
inserts project, declared creator intent, audit and result. A denial can leave a
bounded pending non-authoritative record; #37 must accept retention/expiration
limits before implementation. Restore invalidates old pending operations.

Other writes resolve owners and reserve first-share identity as needed; capture
facts, obtain decisions outside locks, then enter `BEGIN IMMEDIATE` and recheck
all source revision/metadata CAS/epoch/generation/incarnation/deadline bindings.
Commit mutation, domain relationships, audit and idempotency result together;
any failure rolls all product effects back. Rename increments metadata revision.
Audience/share/link/archive/restore increment metadata revision and security_epoch;
link/unlink additionally allocate/end generations and atomically revoke affected
disclosures. Lifecycle restore is distinct from backup reconciliation.

Committed retries return the original immutable result only after current actor,
authority and incarnation checks. They never restore revoked state, repeat an
effect or renew a permit; changed input conflicts. A cached historical operation
success cannot clear quarantine. Read/byte projection similarly rechecks current
facts at the last response boundary; direct campaign/media/export/CLI/tool paths
must refuse linked work if they cannot compose the same checks.

## Restore admission, quarantine and run fences

Controlled restore verifies the complete bundle and creates a fresh store
incarnation **in the restored copy before exposure**. Normal restart retains the
incarnation. A raw file copy is never auto-admitted as a new/fresh store. Quarantine
makes copied project audience and disclosure security state ineffective, including
project metadata/audience reads; no copied manager intent bypasses it. Independent
current workspace recovery authority and explicit positive current-incarnation
reconciliation are necessary to regain access.

For **every restored campaign**, check the positive reconciliation overlay before
choosing standalone or project policy. Missing links, empty project tables and
pre-project backups all remain blocked; absence never proves standalone/fresh.
Recovery explicitly selects standalone or project, exact native owner/current
campaign revision, selected new link/disclosures and current recipient/source
proofs. Atomically create new effective intent/disclosure generations/epochs,
activate the overlay and save audit plus a **new** idempotency result. Retain
historical security rows for audit without making them effective. Partial recovery
leaves other campaigns blocked.

Today's `verify_backup`/`restore_store` requires the current exact schema version;
it does not admit an old-schema backup through this proposed flow. A future
trusted admission path must use matching-release restore into isolation, then
append the accepted migration/incarnation fence before any access. #37 must
accept/implement that compatibility and raw-copy/admission distinction. JSON
reference checks do not demonstrate it.

Old permits, cursors, operation results and pending reservations cannot authorize
the new incarnation. Restored or legacy pending runs never emit new inference or
drafts, including after reconciliation. Retain original actor-private receipts,
uncertain spend and outcomes without release, retarget, replay or adoption. New
explicit runs pin current incarnation/project/epoch/link/resource manifest and
still require original actor/campaign/provider binding, source grants and draft
mandate on every advance and tool commit. A linked legacy run without a manifest
cannot advance; a security epoch change invalidates all project-bound pending
work. Accounting retention is not disclosure to a current reader.

## Executable evidence and remaining acceptance

Run with existing installed test dependencies:

```sh
python scripts/check_project_access_contract.py
python -m unittest discover -s tests -p test_project_access_contract.py -v
python -m unittest discover -s tests -v
python scripts/evaluate_agent_behavior.py
```

The [authored fixtures](../examples/project-access-contract.v1.json) contain five
positive vectors across create, list, shared resource read and recovery families.
The two create commands differ only in composed/decomposed `Café 東京` spelling;
canonicalization preserves their distinct bytes/digests. Literal canonical text
and SHA-256 triplets are fixed in the fixture and pinned independently in the
checker. Thirteen field-replacement negatives cover full owner, target, hashes,
incarnation, original wall/monotonic deadlines, unsupported obligation, nonallow,
unknown action/attribute and overflow. Three parser negatives and three recovery
reference negatives are required by exact ID, as is the full positive set.

The [checker](../scripts/check_project_access_contract.py) verifies the frozen
profile digest, unchanged local producer schema blob, closed field sets, literal
canonical bytes/digests, request/result/native cross-bindings and fixed synthetic
clocks. It bounds input bytes/depth/numbers, rejects duplicate/unknown/invalid
input and forbids remote/dynamic schema references before validation. It cannot
load callable oracles, execute imported transport adapters or issue permits.
The recovery reference is only a closed synthetic lookup of
`(current_incarnation,campaign_id)` to positive reconciliation **before** policy
choice; missing entry denies. These are artifact/reference checks, not executed
native persistence, recovery, real service decisions or runtime authorization.

| Boundary / evidence | State and next owner |
| --- | --- |
| Product cardinality/disclosure/missing-link rules | Human-accepted PR #69, commit `0e6e1e2f9847d18c789bd3f1d4a771973877b5e7`; preserved here. |
| Accepted producer M0 wire/reference | Pinned `d8eb4f4`; real service/client/composed gates #79/#81/#83/#84 remain. No producer registration inferred. |
| Current producer development audit | Advisory source audit at `6cd477db124379c9d773769311076db73846244b`, not default/main acceptance; inspected ResourceFacts/DecisionRequest/DecisionResult/NativeTarget compatible. PrincipalContext/ApplicationRegistration differ; development schema blob `b1798f901bfe04a3df06520fa698a9108443b2f8` is not adopted. |
| Current recipient port | Unaccepted dependency. Development workspace-access-check-76 resolves trusted repository context/allows predicates, not HTTP sessions/decision leases or a recipient directory. UUID persistence does not prove opaque demo-ID support. #36/Gateplane owns acceptance. |
| This project profile / fixtures | Proposed A3a artifacts; independent exact-head review, verification and current CI required. Does not accept producer/storage dependencies. |
| Native adapter / client / performance | #36/Gateplane must accept registration/attester, complete native/hash profile, original multi-decision deadlines, real private client, recipient/revoke semantics, opaque-ID reconciliation and aggregate list budget. |
| Storage / recovery | #37 serial owner must accept allocation/constraints/retention/admission/reconciliation/run invalidation; no slot reserved or migration run. |
| Runtime commands/API/media/UI | Blocked until both owner agreements and a new frozen task contract; existing source command path remains sole writer. |

Future **native SQLite** acceptance must use real commands and temporary stores,
not these JSON checks: race two links for one campaign; attempt full-owner
substitution/insertion/update with FKs both on and off; cross-owner/null legacy
admission; stale revision/epoch/generation and unlink/relink ABA; first-share
reservation conflict; exact create retry before/after commit and reopen, changed
input conflict and denied reservation with no project; late decisions at response
and transactional commit; atomic domain/audit/result rollback. Restore tests must
reopen verified new-incarnation stores and deny copied project metadata/audience,
old permits/cursors/operations/runs and restored standalone campaigns with absent
links/pre-project metadata. Prove fresh independent explicit reconciliation
success, partial-workspace recovery denial for other campaigns, historical bytes
unchanged, current source/recipient checks and no inference/provider effects.

Serial next step: independent artifact review/verification on the exact commit,
then #36/Gateplane and #37 separately accept their agreements. Only a coordinator
may dispatch the next native slice after those gates. #55 stays open; real issuer,
provider, hosting, customer data and operational performance retain their separate
release gates. The portable zero-cost demo remains the release priority.
