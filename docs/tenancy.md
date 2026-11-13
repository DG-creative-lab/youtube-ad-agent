# Tenant, brand and workspace boundary

13 November 2026 · [Staff access slice](hosted-access-boundary.md) · [Architecture](architecture-plan.md) · [Source-code map](source-map.md) · [Enterprise epic #34](https://github.com/DG-creative-lab/youtube-ad-agent/issues/34)

## Implemented product model

The client organization is the tenant. A brand belongs to one client. A person may work for several clients; selecting a client or brand does not itself grant access. This slice makes those owners explicit in the existing application commands. The new ASGI slice adds staff-session and current-access adapters exercised with offline contract fixtures; real identity/service activation remains gated.

| Object | Meaning and boundary |
| --- | --- |
| Client | Tenant owning its brands. IDs are product identities, independent of display names. |
| Brand | Identified by `(client_id, brand_id)`. The same brand ID under another client is a different owner. |
| Workspace | An immutable mapping of one brand to one workspace and installation. In this first version each workspace belongs to exactly one brand. Several brands of one client may share an installation; an installation cannot span clients. A workspace is not a conversation, campaign, SQLite file or runtime directory. |
| User / operator | `Operator.id` is the caller's subject reference. Brand grants limit its candidate scopes. The offline operator is a fixture, not an authenticated account. A future trusted Gateplane adapter must resolve the subject and current grants. |
| Campaign | A globally unique campaign ID with an immutable client/brand owner. Multiple campaigns can belong to one brand. Existing revision JSON and fingerprints remain unchanged; private revision reads verify the owning campaign in the same transaction. |
| Run and conversation | Bound to actor, client, brand and campaign. The workspace and installation resolve through the immutable brand mapping. A foreign run/session ID cannot resume work, return history or supersede another campaign's request. |
| Catalog and assets | Catalog rows and references are scoped to client, brand and campaign. Each runtime receives its brand's comparison examples explicitly. Authored media remain local fixtures; this is not private hosted asset storage. |
| Evidence and findings | Tests, assignments, reviews and findings retain their owner. Findings can inform a compatible fresh brief within the current campaign after restart. Other clients and brands cannot retrieve or apply them. Candidate finding lookup and retirement join the saved native instruction test to verify campaign ownership. A newer sibling finding cannot hide the local one, and a matching finding ID cannot grant permission to retire another campaign’s evidence. Legacy findings without a verifiable source test are unavailable. Brand-wide sharing across distinct campaigns needs an explicit future product rule. |
| Public viewer | A published comparison/link resolves its own example and allowed events. It confers no staff access. Visits are bound to the server-selected campaign. Event replay, report counts, freshness checks, tagged-link counts and experiment evidence retain that campaign boundary as well as example ownership. Hosted public link routing and lifecycle remain separate work. |

`brand_workspaces` and `campaign_owners` hold the ownership records. Update/delete triggers reject remapping. `provision_workspace` is a trusted product command, not a browser endpoint: it requires workspace configuration access and refuses foreign ownership and unknown unowned history. Migration or administrative moves will require their own explicit procedure.

## Access port and Gateplane preparation

`campaign_agent/ports/access.py` defines the product-owned `AccessPolicy`. Application commands send an `AccessRequest` containing actor, client, brand, workspace, installation, capability and campaign. A decision must be exactly `allow`; denial, an unavailable decision and adapter errors cannot fall back to local access. Membership in the selected brand is also required.

`WorkspaceContext` is supplied by trusted server composition. It must never be built directly from browser assertions or model output. Nonlocal campaigns require prior provisioning, an explicit campaign ID, explicit brand examples and an injected access adapter. `LocalDemoAccess` permits only the exact local/demo mapping. It supplies no foreign-customer fallback.

| Capability | Product checks |
| --- | --- |
| `youtube:workspace.configure` | Provision the product's immutable mapping and campaign owner. |
| `youtube:campaign.read` | Read private campaign state, history and reports. |
| `youtube:campaign.draft` | Initialize a campaign or save a draft revision. |
| `youtube:campaign.approve` / `youtube:campaign.export` | Record exact package approval / export a currently approved package. |
| `youtube:catalog.write` | Register independently supplied catalog material. |
| `youtube:agent.run` | Start/resume agent work and accept a tool result after inference. |
| `youtube:review.write` / `youtube:learning.manage` | Save reviews, corrections and snapshots / save or retire findings. |
| `youtube:setup.manage` | Validate and dispatch the existing exact approved setup flow. |

These are product capabilities, not a proposed Gateplane wire schema. Access is rechecked at sensitive command boundaries and when accepting inference results. Receipts already obtained may be retained after revocation for recovery; they cannot authorize another tool or draft. A per-request instruction/placement draft permission, current evidence, stale-revision protection, exact approval and provider limits still apply in addition to access. An allowed actor cannot turn learned text or a model proposal into approval. If the final access check fails after a setup reservation but before the provider call, the command releases that known-unsent reservation back to validated, clears creation approval and requires an explicit retry. Provider outcomes after dispatch retain the existing created/unknown/read-back recovery path.

Gateplane owns authentication, membership, current access and bounded delegation. The product owns native resource ownership, evidence freshness, draft permission, exact package approval and provider effects. The later adapter should translate Gateplane's accepted native decisions through this port, bind the verified session/request and selected application/workspace/installation, and enforce freshness/revocation without importing Gateplane's database models. The staff session/HTTP boundary is now exercised through the [offline contract fixture](hosted-access-boundary.md). It makes no live Gateplane calls. The private SDK, real OIDC callback/credential adapter, worker mandate and provider connections remain open work.

## Compatibility and verification

The original `tts-sample` and `tts-catalog` IDs are reserved for the explicit local context. Existing demo revisions and registered catalog references are retained without rewriting snapshot JSON. Legacy catalog rows receive the original local/catalog owner. Legacy runtime runs are admitted only to the original local/sample campaign. Unknown unowned histories are refused for new customer provisioning; do not infer their owner from an incoming request. Legacy viewer visits acquire the original sample owner only for the local demo brand when no additional campaign makes that attribution ambiguous. Other unbound visits remain stored but cannot resume under or contribute to a customer campaign. Older performance reviews without campaign attribution must be captured again before they can support a new draft.

The local HTTP server remains a loopback demo assembled with the seeded operator. No tenant selector, hosted authentication, production database or customer onboarding is introduced. Opening a new nonlocal campaign uses the existing authored brief/rules as an offline seed and requires draft access; real customer knowledge and media onboarding are later work.

`tests/test_tenant_workspaces.py` uses one temporary database, two clients, a second brand within one client, and a person with grants to all three. It exercises campaign/run/conversation isolation, identical catalog rows, approvals, reports, visits, assets, finding reuse after restart, unavailable/revoked access, per-request draft authority, legacy migration, sibling-campaign activity with distinct campaign grants, and pre-dispatch denial/unavailability followed by a successful retry. A separate restricted operator proves that an adapter's allow decision cannot replace brand membership. All dependencies are local fakes; no credentials or provider requests are used.

## Remaining enterprise work

The [epic #34](https://github.com/DG-creative-lab/youtube-ad-agent/issues/34) tracks eight linked slices:

1. [#35 Product tenant/workspace boundary](https://github.com/DG-creative-lab/youtube-ad-agent/issues/35): this branch's product model and offline isolation checks.
2. [#36 Gateplane access and hosted staff entrypoints](https://github.com/DG-creative-lab/youtube-ad-agent/issues/36): compose with the Gateplane-owned integration contract; verify sessions, current decisions, revocation and public/private route separation.
3. [#37 Hosted persistence and private assets](https://github.com/DG-creative-lab/youtube-ad-agent/issues/37): scoped shared storage, migrations, concurrency and recoverable private media access.
4. [#38 Durable jobs and inference budgets](https://github.com/DG-creative-lab/youtube-ad-agent/issues/38): worker authority, cancellation, retries, restart and cost enforcement.
5. [#39 Provider connections and uncertain effects](https://github.com/DG-creative-lab/youtube-ad-agent/issues/39): tenant-owned accounts, exact dispatch and reconciliation.
6. [#40 Privacy, audit and tenant administration](https://github.com/DG-creative-lab/youtube-ad-agent/issues/40): lifecycle, retention, administration and attributable actions.
7. [#41 Deployment and operations](https://github.com/DG-creative-lab/youtube-ad-agent/issues/41): repeatable environments, monitoring, service targets and restore verification.
8. [#42 Composed hosted pilot release](https://github.com/DG-creative-lab/youtube-ad-agent/issues/42): exercise two clients through the deployed composition before calling it ready for a pilot.

Completing the product boundary does not establish hosted or enterprise readiness. Deployment, real customer data, provider spending and production activation require their own implementation and verification.
