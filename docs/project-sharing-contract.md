# Project ownership and team sharing: proposed v1

15 November 2026 · [Issue #55](https://github.com/DG-creative-lab/youtube-ad-agent/issues/55) · [Factory plan](agent-platform-factory-plan.md) · [Native ownership](tenancy.md)

## Status and first outcome

This is a **proposed product/consumer contract**, not implemented project access, producer registration or permission to dispatch runtime work. Source baseline: merged PR #68, **23b0bc0f5afc6b016b46b646423272a8bf7e203b**. Human document acceptance does not complete #55. The portable demo and release packaging retain priority.

A team member will open a brand-owned project, see permitted campaign links and explicitly shared package versions, and perform only currently authorized actions. Editors use the existing campaign commands. Reviewers can inspect a shared version without acquiring the author's conversation, model credential or execution authority.

Projects are logical collections, not filesystem paths or agent sandboxes. Versioned briefs/guidance (#56), new creative artifacts (#57), learning promotion (#58), cross-brand projects, invitations/groups and conversation sharing are later work. Real issuer/Gateplane, hosting, provider qualification and customer-data activation retain their existing gates.

## Current implementation and owned gaps

| Boundary | Current source on the baseline | Required extension |
| --- | --- | --- |
| Ownership | [workspaces.py](../campaign_agent/workspaces.py) binds immutable brand/workspace/installation and campaign owners. | Product-owned projects and links; no campaign owner transfer. #55/#37. |
| Access | [AccessRequest](../campaign_agent/ports/access.py) requires campaign_id; [GateplaneAccess](../campaign_agent/adapters/gateplane.py) resolves an existing campaign revision and hardcodes a campaign target. CAPABILITIES contains no project actions. | Native project/workspace resolver, pre-campaign create/list authority and relationship-aware permits. #36 owns the extension. No fake campaign target. |
| Producer | [Pinned wire v1](../campaign_agent/contracts/README.md) permits generic targets and bounded namespaced scalar facts. | Accepted application registration, trusted disclosure-fact profile and decision semantics. Schema validity is not project-policy acceptance or service conformance. |
| Content and runs | Existing campaign/package, media, conversation and run owners enforce their own boundaries. | Explicit resource projections and additional project fences in the same command path, rather than parallel writers. |
| Persistence | [migrations.py](../campaign_agent/migrations.py) has four ordered/checksummed slots; [recovery](storage-recovery.md) supports one worker, SQLite and immutable private files. | One #37 owner appends project schema/restore fences. No previous checksum edits or hosted database substitution. |

## Product rules

### Ownership, cardinality and lifecycle

Client/tenant → brand → immutable workspace → project → linked campaigns. A project has one immutable (client_id, brand_id, workspace_id, installation_id) owner, an opaque server-generated ID, display name, metadata revision and security epoch. A workspace has many projects; a project has many campaigns; each campaign has **zero or one active project link**. Cross-brand projects are unsupported even within one tenant.

Linking never changes campaign_owners, campaign IDs, revision JSON, approvals, experiment/finding lineage, asset ownership or content fingerprints. Migration leaves existing campaigns unlinked. Linking is explicit, not a folder-name inference or automatic grant backfill.

States are active and archived. Archive retains history and blocks ordinary project content reads and new linked-campaign effects. A currently authorized manager may read minimal management metadata and explicitly restore. Owner transfer and physical deletion are outside v1.

Audience, sharing, link/unlink and archive/restore changes increment a monotonic security epoch. Every link has a fresh immutable generation. Unlink/relink or archive/restore cannot revive an older permit/run when the same IDs reappear. V1 conservatively invalidates all project-bound pending work after a security-epoch change. Metadata-only rename increments its compare-and-swap revision without renewing access or invalidating otherwise unchanged campaign work.

### Team disclosure intent and current authority

The product stores a manager's **resource-disclosure intent**, referring to an exact externally identified human in the same workspace. It does not create identities, workspace membership, tokens or delegation. Candidate subject resolution requires a producer-supported current membership interface. The present context/decide facade has no directory or membership-admin API; do not invent one. Arbitrary actor/email/browser-role input is not membership evidence. Unsupported recipient resolution keeps sharing unavailable.

| Intent label | Maximum product action family; every action also requires its current external decision |
| --- | --- |
| Viewer | Project metadata and explicitly shared resource versions. |
| Editor | Viewer actions plus the linked campaign's existing workspace read/draft commands, with their source grants and explicit per-request draft mandate. |
| Reviewer | Viewer actions plus review of explicitly shared package versions. Approval requires current campaign approval capability and exact product approval checks. |
| Manager | Viewer actions plus project metadata, audience, link and archive/restore management. No automatic campaign edit or approval. |

Record an explicit set of intents when a subject needs several families. Creation records creator attribution and a declared initial manager intent, not an external grant. Later reads/management still need the registered project decision. Gateplane administration alone grants no campaign approval. Self-intent changes require the same share-management decision and external capability limits as changes for another subject.

Effective access intersects verified staff/session/workspace membership, exact native owner/target, current action decision, active state, intent, link generation and resource disclosure. A project allow cannot replace a denied source action. Membership revocation or unavailable authority blocks new access despite retained intent. Membership reinstatement cannot recreate an explicitly revoked project intent. No second membership database, invitation system or background membership synchronization is added.

All linked-campaign entrypoints need this additional project check: direct campaign URLs, media/downloads, export, CLI, agent tools and resumed work. An entrypoint unable to enforce it must refuse linked-campaign access. There is no legacy/standalone fallback while a link is active. Viewer/reviewer intent alone permits the shared projection, not the unrestricted campaign workspace/history; editor intent still needs the existing source grants. Manager intent alone cannot edit a campaign.

Link and unlink require current management decisions for the project **and** campaign relationship, with both native owners resolved. Unlink returns the campaign to standalone policy and may broaden visibility; confirmation must state that consequence. It removes active project disclosure references to that campaign and invalidates project-bound work without deleting source content. A revoked viewer cannot unlink to regain access.

### Explicit resource sharing and private history

A link reveals only permitted link metadata. It does not automatically share a package, all revisions or the brand's asset catalog. V1 team content is an explicitly shared **campaign package version**, identified by native campaign ID, revision, fingerprint, projection version and selected permitted media references. Store a native reference rather than a copied package with a new owner. Sharing/approval of one version never shares future drafts. Re-resolve current approval status through the native owner rather than persisting a permanent approved badge.

Resource reads require project-read and resource-read decisions, the source command's required current capability, exact active disclosure/link and native source validation. Even with a campaign-read allow, viewer intent cannot use the unrestricted latest-campaign route. The typed shared-package route returns only that version's declared projection, never whole database rows, run outcomes or private evidence inspectors.

Conversation titles/messages, prompts, raw tool traces, provider settings/selections, accounting receipts and credentials remain **actor-private**. Exclude them from project lists, counts, search, exports, team feeds and context assembly. Existing conversation/run actor checks remain; sharing a package never lets another member resume, supersede or cancel its author's run. Conversation sharing needs another disclosure/execution contract.

Private bytes resolve project resource → exact native package version → permitted catalog entry/digest → immutable brand-owned blob. Project ID, digest, catalog ID or copied URL grants no authority. Recheck current project/source permission and disclosure before projecting private responses or emitting bytes, including range/download paths. Do not list the entire brand catalog or mint a new bearer URL. Already delivered bytes cannot be recalled.

Existing public comparison publications are separate exact-content grants. Project share revocation, unlink and archive **do not unpublish** or renew them. Management confirmation must explain that an existing public comparison may remain reachable. Revocation uses the publication owner in a separately authorized action; a manager without source permission cannot enumerate hidden publication inventory. Any cascade needs its own partial-failure/recovery contract.

## Access and application command handoff

### Producer/#36 acceptance gate

Proposed internal capability identifiers are youtube:project.create, youtube:project.list, youtube:project.read, youtube:project.edit, youtube:project.share, youtube:project.link, youtube:project.archive, youtube:project.resource.read, youtube:project.resource.share, youtube:project.recover and youtube:campaign.project_link. Wire identifiers would append .v1. These are **not implemented in CAPABILITIES or accepted as registered producer policy**.

The #36 and Gateplane owners must accept a youtube-project-v1 native profile before runtime dispatch:

- Workspace-target create/list without a fabricated campaign revision. Create binds the server-reserved proposed project ID/initial intent in its exact command hash; no private project is readable before commit.
- Project-target actions and exact source campaign/resource decisions. Server-resolve owner, state, store incarnation, security epoch, intent revision, link generation and resource version/digest. Register a workspace recovery action whose authority is independent of restored project audience rows.
- Canonical input/subject hashes, native resource-version format, trusted attester and disclosure-fact provenance. Reuse wire v1; add no new envelope field or producer ORM dependency. Attributes stay within its namespaced scalar limits; large manifests are referenced by product-computed digests, never raw conversations or credentials.
- Current recipient resolution and intent semantics. Gateplane owns membership and action decisions; product intent only narrows eligibility. Unsupported registration, obligation, target or effect fails closed.
- Exact application/installation/tenant/workspace/actor/session, target, command/subject hash, authority-version and obligation checks. Preserve each original deadline and the existing maximum five-second decision-use window, plus local logout/expiry fences.

There is no assumed directory, batch-decision, invite, membership-admin or delegation API. A clearly labelled offline fixture can exercise a proposed contract; real producer/private-client/issuer conformance remains a separate gate.

### Proposed commands and staff routes

The following are handoff names/inputs, **not shipped endpoints**. UI and typed agent tools use the same owning application commands. Session/native lookup supplies identity and owner; browser selectors only nominate candidates. Mutations retain existing CSRF/origin/no-store behavior. No public-viewer project API is added.

| Command / proposed route | Declared fields and behavior |
| --- | --- |
| list / GET /api/projects | Optional opaque cursor; verified workspace and fixed page size. Authorized metadata only, no total counts/private previews. |
| create / POST /api/projects | operation_id, bounded name. Server reserves ID; current workspace-create decision; atomic initial records. No client/brand/actor assertions. |
| read / GET /api/project | project_id. Authorized metadata and separately bounded permitted links/resources. No full audience, transcripts or hidden totals. |
| rename/archive/restore / POST /api/project/change | operation_id, project_id, expected_revision, one declared action and bounded action fields. Current management decision; compare-and-swap. |
| set/revoke intent / POST /api/project/audience | operation_id, project_id, expected_revision, verified recipient reference and intent set/revoke. No external membership writes. Audience listing is a separate management-authorized paginated read. |
| link/unlink / POST /api/project/campaign | operation_id, project_id, expected_revision, campaign_id, expected_campaign_revision, action and expected_link_generation when applicable. Resolve/authorize both sides. |
| share/unshare / POST /api/project/resource | operation_id, project_id, expected_revision, typed package-version reference, action. Current native source grants, exact revision/fingerprint and link. |
| shared read / GET /api/project/resource | project_id, opaque resource_ref. Typed package projection after current access/source joins. Bytes use that same authorized reference, never a filesystem path. |

Reject unknown fields. Names are bounded to 120 Unicode characters/480 UTF-8 bytes without control characters, treated as data and escaped when rendered. Opaque operation/project/resource IDs have the accepted profile's bounded format. Accept no arbitrary SQL/URL/path, executable skill or provider credential. Unknown and inaccessible IDs use a uniform unavailable response without foreign names/counts or useful redirects.

Project/campaign switching starts fresh conversation context and resets draft permission to Review only. A campaign-bound provider selection cannot be carried to another campaign; account credentials remain personal. Opening history does not silently start, retarget or authorize a run.

### Decision capture, commit/response fences and recovery

Capture the command and required native facts; obtain all current external decisions **outside SQLite writer locks**. A project permit must bind staff session/full owner, current store incarnation, exact command/action, relevant state/security epoch/intent revision, active link generation and resource identity, retaining each original expiry. Current CommandPermit's campaign revision/hash is insufficient. Extend the existing owner; create neither a competing access journal nor authority from a UI label.

Locally recheck those facts/deadlines immediately before projecting a private response/emitting bytes and inside a transaction accepting a write/tool result. Management mutations also compare metadata revision. No authority/provider I/O under the write transaction. Do not renew a permit by changing its timestamp, target or original hash over changed state.

Local revoke/unshare/unlink/archive/restore must reject late responses/results using epoch/generation checks. External revocation is bounded by the accepted decision-use window: Gateplane and SQLite are not one atomic transaction. Do not promise instant revocation or recall of bytes already sent. Every queued advance requires new current authority; a historical allow is not worker permission.

New foreground runs retain an immutable project-context manifest beside existing records: store incarnation, project/security epoch, campaign link generation and selected resource references actually used. Future guidance references require #56's version contract. The manifest is provenance, not authority. Each new inference/advance/tool commit still needs the original actor/campaign/provider binding and current project facts. On mismatch, block new effects and retain original outcome/receipts without retargeting, adopting, replaying or changing actor/cost accounting.

Legacy runs without a manifest cannot advance after their campaign is linked; start a new explicit request. Received receipts may be retained for accounting/recovery despite revoked disclosure, but cannot authorize another model call or draft. Retention is not a current user's read entitlement. Unattended execution/delegation remains #38 work.

## Persistence and restore

The initial topology remains one application worker with SQLite/private immutable files. #37 owns the next migration slot at dispatch time: baseline slot 5 is only a candidate, not a reservation against another writer. Preserve existing checksums/domain history and the offline adapter. No Postgres/object-storage cutover, onboarding or competing migration runner.

| Proposed record | Required constraints |
| --- | --- |
| projects | Globally unique ID, immutable owner matching brand_workspaces, positive metadata revision/security epoch, state, creator/updater attribution/timestamps. |
| audience intent | Exact owner/project/external subject, explicit bounded intent set, active/revoked state and immutable change history. No membership token/grant or provider setting. |
| campaign links | Same owner on both sides; database-enforced one active link per campaign; new immutable generation and retained link/unlink history. |
| resource references | Same-owner active link generation, allowlisted type/native version/fingerprint/projection version, explicit active/revoked disclosure. No copied private payload. |
| operations/change records | Unique (client, brand, workspace, actor, operation_id), exact command/input hash, result reference and attribution. Same-input retry returns its original result only after current authorization; different input conflicts. No secrets/whole request blob. |
| run manifests | Immutable original run/actor/campaign relationship/resource binding and store incarnation. Existing run IDs, request hashes, receipts and billing owner remain unchanged. |
| store recovery state | Current store incarnation and per-project reconciliation/quarantine overlay, separate from immutable historical rows. Normal restart retains it; controlled restore generates a fresh incarnation and quarantines restored security state before private traffic. |

Use composite constraints and/or verified immutable-owner triggers across every relationship; foreign_keys enabled on a single test connection is insufficient. Enforce competing links/revisions with database uniqueness and atomic compare-and-swap. Commit change, relation/intent/disclosure, audit event and idempotency result together. Denial, stale revision, invalid native reference or race leaves no partial writes. Audit records exclude secrets/private transcripts.

Migration leaves campaign revision bytes, approvals/fingerprints/actors/timestamps, experiments/findings, media/catalogs, conversations, provider selections and ledger receipts unchanged. Never infer unknown legacy owners, create projects from folder names or implicitly share history. Retry is idempotent; unsupported schemas fail without partial adoption. Archive/unlink/unshare retain source records and audit history.

Whole-store backup/restore includes project/operation/audit/manifest records consistently with the database/blob inventory. Restore preserves history and invalidates old staff/public authority through the existing recovery owner. **Fresh sessions and external decisions alone are insufficient:** restoring an older backup can resurrect product-owned intent/disclosure/link state revoked after that backup, while external workspace membership still permits the actor.

Before serving any restored private project traffic, the trusted restore path generates a fresh store incarnation and applies a fail-closed quarantine overlay to all restored audience/disclosure/link security state. Preserve original historical rows/manifests/receipts; copied state is not effective authority. Normal restart keeps its current incarnation; restore cannot reuse the backup's incarnation. Bind new permits, cursors and run manifests to the current incarnation. Refuse old permits/cursors, historical operation-result replay as reactivation, and new effects from restored pending work even after new sign-in or later project reconciliation.

Clear quarantine only through an explicit new recovery/re-sharing operation, with a current registered workspace recovery decision independent of copied manager/audience rows, verified native ownership, current recipient/source permissions and deliberate selected resource versions. Reconcile intents/disclosures/links, advance security epochs/link generations and save the new incarnation-bound activation/audit/idempotency result atomically. Copied manager intent is not recovery authorization. If the producer recovery profile or reconciliation is unavailable, keep project content and effects blocked; do not infer which post-backup revocations still apply.

After reconciliation, new explicit authorized requests can run; old manifests cannot be adopted into the new incarnation. Received uncertain receipts/reservations remain original accounting/recovery evidence, never cancellation, replay or draft permission. Reopen the restored store to verify both denied old authority and the permitted explicit recovery path.

## Query and acceptance requirements

Use indexed actor-intent/owner/link lookups and keyset pagination. Return at most 20 items and inspect/authorize at most 20 candidates per page; zero/fewer visible rows may have an opaque continuation cursor. Bind cursor to actor/session/owner/current store incarnation/query/last scanned position, expire within five minutes, and expose neither readable hidden IDs nor authority. Reauthorize every page, reveal no unauthorized totals/names, and never scan until a page fills or fetch all team conversations. No unbounded per-row network work or assumed batch service. The producer profile must accept a practical aggregate request budget before lists are enabled.

Planned fixture workload: 1,000 projects across two tenants, 100 links/project and 100 subjects with uneven visibility. Record query plans, scanned candidates, decision count, response bytes and P50/P95. Proposed target: product/database overhead P95 ≤200 ms/page on a declared machine, excluding separately recorded authority latency; page JSON ≤100 KiB. These are **future acceptance targets, not measurements or a production SLA**. Real authority latency, aggregate deadlines/batching need owner acceptance; a five-second decision-use limit is not a request-wide network timeout.

| Future scenario | Required observable evidence |
| --- | --- |
| Allowed team path | Manager creates/links and explicitly shares a package version; eligible viewer reads; editor saves an unapproved revision under its own mandate; separately authorized reviewer approves exact content. Reopen and inspect attribution/owner/fingerprint. |
| Isolation/disclosure | Two tenants and sibling brands; valid wrong project/campaign/version/digest and guessed IDs expose no foreign metadata/bytes. Denied source grant cannot be bypassed through direct campaign/media/export. Team projections exclude unshared history, conversations and provider/accounting records. |
| Revocation/races | Revoke membership/intent after list, during decision lookup, after inference and before commit/bytes. Report bounded external staleness honestly; local epoch/generation rejects stale results. Unlink/relink/archive/restore cannot revive old work. Legitimate fresh access also succeeds. |
| Recovery/provider | Missing/wrong personal key, foreign/private/superseded run, copied selection and project switch cause no unauthorized completion. Retain original uncertain receipt/cost owner without draft/replay; reload/history alone never dispatches. |
| Atomicity/migration | Competing links, operation reuse with changed input, stale revision and failed source checks commit no partial state/audit. Migrate authored histories and compare bytes; rollback/idempotency, reopen and restore. |
| Restore after revocation | Back up active viewer/shared V1; revoke intent or unshare V1 locally while external membership/source grants remain allowed; restore that older backup; fresh same-member session and decisions still reveal no private bytes or new inference. Copied manager rows, old cursors/permits/manifests and operation replays cannot reactivate it. An independently authorized recovery actor deliberately re-shares selected content, and a new allowed request succeeds; historical bytes/receipts remain unchanged. |
| API/media/UI/performance | Authorized/empty/unavailable pages; expired/foreign opaque cursors; bounded query/decision/payload counts; range/private-byte guards. Actual desktop/narrow/keyboard flow shows explicit sharing, role limits, unlink/archive/public-link warning and Review-only reset. |

Runtime evidence uses real application/ASGI commands and temporary SQLite with independently authored current-access/provider adapters. Include denied zero-effect and legitimate allowed paths. Source inspection, fixture execution, live model quality and human usability remain distinct. Code slices require full offline regression, locked client tests/build, independent exact-head review/browser verification and final CI.

## Serial delivery gates

| Slice | Gate/owner | Reviewable result |
| --- | --- | --- |
| A3-contract (this PR) | Coordinator authors four docs; independent source review/document verification; human document merge. | Proposed product/native access/storage contract only. |
| A3a access/persistence agreement | #36/Gateplane accepts registration, pre-campaign/list/recipient resolution, trusted facts/permit/revocation and request budget; #37 accepts migration/constraints. | Versioned accepted adapter/storage agreement and labelled conformance fixtures. Producer changes stay with its owner. |
| A3b native commands | Accepted A3a; one owner for projects/next migration/access permits and legacy direct-entrypoint guards. | Atomic native commands/recovery with no linked-campaign bypass. Public project routes remain unavailable until enforcement composes. |
| A3c staff/media/foreground | Accepted A3b; retain source owners and #38/#39 actor/receipt/provider semantics. | Bounded HTTP projections, private-byte joins and original relationship-bound runs. |
| A3d UI | Accepted APIs/#52 projection; one frontend owner. | Navigation/explicit version sharing, personal account/chat context and composed browser evidence. |

No row claims dispatch or accepted dependencies. Keep #55 open through implementation acceptance. Refresh main, producer acceptance, migration ownership and a complete task contract before runtime dispatch. Real issuer/Gateplane, hosting, customer data, paid providers and production performance remain separate release gates.
