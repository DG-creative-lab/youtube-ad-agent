# OpenRouter foreground session contract · v1

14 November 2026 · A2 / [#54](https://github.com/DG-creative-lab/youtube-ad-agent/issues/54).
Status: proposed implementation contract for human review. This document adds no
runtime, live model, credential store, migration or deployment. Acceptance of the
contract permits the bounded offline implementation slices below; it does not
authorize provider calls or spending. [Architecture](architecture-plan.md) ·
[Factory plan](agent-platform-factory-plan.md#6-openrouter-and-user-funded-inference).

## Product and compatibility

The account control offers **Connect OpenRouter**, **Replace key** and
**Disconnect**. The composer retains the offline models and adds a searchable
provider catalogue with compatibility, prices, data handling and a per-request
budget. Connecting or choosing a model never sends a completion. Changing model,
connection or budget starts a new conversation; typed text is retained. **Changes**
still governs draft permission independently. The platform supplies no model key.

The first consumer is the existing foreground main-model/tool loop. Structured
review and instruction-draft requests use the same transport and ledger, with
their own schema-compatibility profile. Unmigrated web inference paths stay offline;
they cannot use an environment key. The placement specialist remains simulated.
Voice/audio generation, new tools, ad effects and background inference are separate.

Current baseline: PR #64 merged at
`53553876308ccb0558eb61b829064639a12e0d0d`. `PlacementAgent` owns conversations,
eight turns, reservation/receipt recovery and transactional tool commits;
`OpenRouterInference` currently reads the environment and permits configured free
models only. Hosted composition currently enables simulated models only. Those
are current behaviors; everything below is a target contract.

The iwoca comparison uses `frontend/src/openrouter-session.ts`,
`OpenRouterSettings.tsx` and `src/acquisition/workspace_models.py`: sessionStorage
holds a handle while a five-minute server-memory map retains the raw key. Reuse
the account/composer interaction and pinned-selection pattern. This application
will use the browser-retention policy below instead of that connection map.

## Credential lifetime and binding

- **Raw key: active-tab JavaScript memory only.** No localStorage, sessionStorage,
  IndexedDB, service worker, URL, clipboard copy action, analytics or durable
  server storage. Clear the password field immediately after reading it, including
  failed connection attempts. Disconnect, identity/scope change, logout and expiry
  clear memory. Client timeout after a request does not prove server cancellation.
- sessionStorage may contain only a random `tab_id`, opaque `connection_id` and
  model display preference. Reload loses the key and shows **Reconnect to resume**;
  saved conversations/receipts remain readable. A tab ID is correlation, not proof
  of identity or authority; copied browser metadata never suffices to dispatch.
- Supply the key in one `X-OpenRouter-Key` header only on the explicit provider
  commands listed below. HTTPS is required outside the existing loopback demo.
  Reject duplicate key headers, CR/LF, an empty value or more than 512 ASCII bytes
  before transport construction. Do not echo the rejected value.
  The BFF necessarily sees the key transiently and passes it directly to a fixed
  provider adapter. No global variable, process map, environment mutation or worker
  queue retains it. Best-effort clearing cannot promise forensic memory erasure.
- Before any provider I/O, resolve the authenticated actor, current staff-session
  identity and native tenant/brand/workspace/installation/campaign on the server.
  Match the connection and constant-time compare its key verifier. Browser IDs,
  provider account metadata, model arguments and shared projects grant no access.
- Persist a random 256-bit connection ID, operation ID, actor, staff-session token
  digest, full native scope, tab correlation, random salt and
  `SHA256(salt || raw_key)` verifier, created/expiry/revocation times. The verifier
  is internal restricted metadata; never return it, include it in prompts, traces,
  user exports or transcript payloads. It may exist in the private connection
  table and operator whole-store backups; restore invalidates its connection.
  Do not persist the key, suffix, provider label,
  creator/account identity or the complete key-introspection response.
- A connection expires at the earlier of staff-session expiry or one hour after
  creation; a request cannot extend it. Replacement revokes the old connection.
  An explicit reconnect may prove possession of the same key against an unexpired
  original connection in the same staff session/scope. Expired/replaced connections
  cannot be rebound to old runs: create a new operation. Restoring a store
  invalidates connections with staff sessions, retaining historical accounting.
- Recheck provider key validity before each new inference outside the write
  transaction. A local mismatch causes zero provider requests; an upstream-invalid
  key can require a validation GET, but must cause zero completion dispatch after
  that denial. Revocation between validation and dispatch can still produce a
  rejected completion attempt; retain its attempted/unknown accounting truthfully.

Disconnect uses the current local authenticated session and CSRF proof to revoke
only its own connection, even during upstream authority outage. It requires no
provider request or raw key. Browser clearing always works if that request fails.
Logout invalidates dispatch through the original staff-session binding. A request
already sent cannot be unsent; record its usage/receipt, but revoked/superseded work
cannot save a draft, commit a tool outcome or authorize another inference.

Ingress, proxy/APM/tracing and crash reporting must suppress the credential header
and sensitive request objects before capture; sanitized exceptions alone do not
provide this property. Disable request-body/header capture on these routes and
test sentinels through logs, errors, DB/backups, exports and captured provider
envelopes. The provider Authorization header is the sole permitted outgoing key
location. The legacy server `.env` key is never a web fallback.

## Application API · `openrouter-session/v1`

All routes use existing staff/local-operator authentication, origin/CSRF/body-size
checks and strict unknown/duplicate-field rejection. Public viewer routes have no
provider endpoints. IDs are opaque 32-byte random references; display labels are
data, never an endpoint or price selection. POST responses and secret-bearing
requests use `Cache-Control: no-store`; no service-worker cache. Raw provider
responses and URLs in errors are not forwarded.

| Command | Exact JSON body | Result / rule |
| --- | --- | --- |
| `POST /api/openrouter/connect` | `operation_id`, `tab_id`; optional `resume_connection_id` | Key header required. Current read+agent.run access, bounded key-introspection GET, then atomic scoped admission. Returns `schema_version:1`, `connection_id`, `expires_at`, `state:"connected"`; no key or account data. Replay of identical scope/key/operation returns the original connection; different inputs conflict. Replacement explicitly disconnects first. |
| `POST /api/openrouter/models` | `connection_id`, `tab_id`, `search`, `cursor` (null initially) | Key header and connection proof required. Returns `schema_version:1`, `catalogue_revision`, `observed_at`, `expires_at`, `models`, `next_cursor`. Each row: `id`, `name`, `input_usd_per_million`, `output_usd_per_million`, `state`, `reason_codes`. Row states: `candidate`, `eligible`, `blocked`. Advertised tool support alone means candidate. |
| `POST /api/openrouter/select` | `operation_id`, `connection_id`, `tab_id`, `model_id`, `catalogue_revision`, `profile` (`planner` or `structured_review`), `max_run_cost_usd` | Key header required. Refresh/revalidate selected model/endpoint and qualified charging profile. Atomically pin selection; return `selection_id`, normalized model, server-derived routing/privacy/profile version, prices and budget. Candidate/unqualified route cannot be selected for inference. |
| `POST /api/openrouter/disconnect` | `connection_id`, `tab_id` | No key. Owner/session-local revocation is idempotent; returns `disconnected:true`. Wrong owner rejected without provider I/O. |
| `POST /api/openrouter/reconcile` | `run_id`, `inference_position` | Key header required. Accounting only for an owned ledger row with a saved generation ID; never obtains/replays completion text. A current authorized session in the original actor/native scope may prove the original key against an expired connection verifier for this purpose alone; it cannot re-enable that connection or inference. Returns `state`, `reserved_cost_usd`, `actual_cost_usd` (null if unknown). |
| Existing `POST /api/agent/placements` | Existing fields plus `provider_selection_id` only for OpenRouter | Key header required for OpenRouter; selection resolves connection/scope/model/budget. Existing run/session/catalog IDs, `after_message` and `draft_permission` retain their meanings. Supplied `model` must equal the selection. No browser actor/account/price/endpoint selectors. |
| Existing `POST /api/agent/run` | Existing `run_id` | Key header only if the next step needs a new inference. Resolve original binding/selection from run; do not accept replacements. Reads and receipt-only recovery need no key. Structured review/draft command routes follow the same optional selection reference rule. |

`operation_id` and `tab_id` use the existing 32-lowercase-hex UUID convention;
connection/selection IDs are 64 lowercase hex. Model IDs must exactly match a
bounded server-returned catalogue entry; percent-encode validated author/slug
segments when building the fixed upstream metadata path. No arbitrary hostname,
redirect, model alias/router, model-fallback array, plugin or provider header.
`search` is at most 100 characters; maximum 20 returned rows; opaque cursor is
bound to this connection/scope/revision and expires with its catalogue.

Failures use `{error, code, retryable}` with sanitized fixed messages: 400
`invalid_request`; 401 `sign_in_required`; 403 `access_denied` or
`credential_mismatch`; 409 `selection_stale`, `operation_conflict`,
`waiting_for_credentials`, `connection_expired`, `route_unqualified`,
`budget_exhausted` or `inference_outcome_unknown`; 429 `admission_busy`; 503
`authority_unavailable` or `catalogue_unavailable`. `retryable:true` permits only
a proven-unsent preflight retry with the same operation ID. It never authorizes
resubmitting a possibly sent completion. Existing non-provider route error shapes
remain compatible. No unknown key material in validation messages.

Fixture compositions inject only fake provider transports and reject live keys;
they never choose a real transport because a key/environment variable is present.
Real local/hosted composition must explicitly install the adapter. A successful key
probe does not prove completion permission: reject management/provisioning keys,
expired keys and unusable/unknown key restrictions; application identity still
comes exclusively from the existing authenticated context.

## Fixed provider and selection policy

Only `https://openrouter.ai` is allowed. Provider transport paths are GET
`/api/v1/key`, `/api/v1/models`, `/api/v1/models/{author}/{slug}/endpoints` and POST
`/api/v1/chat/completions`. Optional accounting-only GET `/api/v1/generation?id=…`
requires an already saved generation ID and original binding; no list/search of
account generations. No redirects, automatic POST retries or endpoint supplied by
the browser. Set a five-second metadata deadline and a 30-second completion
deadline, bounded response bytes and validated JSON. Network failure is sanitized.

Catalogue metadata is cached for at most five minutes, capped at 2 MB / 2,000
models; oversized/incomplete data fails closed. Authenticated projections are
cached only under full connection/scope, never globally shared. A request refreshes
the chosen endpoint before every inference; a UI cache cannot authorize dispatch.
At most one catalogue refresh per connection at a time; at most two endpoint
detail reads for one selection. No N-provider requests for every displayed row.

Select text-input/text-output chat routes whose endpoint metadata and reviewed
profile support the actual request: tools, required tool choice, disabled parallel
calls and the chosen output-cap field for planner; strict structured response
format for review/draft. Validate all results locally through the existing schemas
and application commands. Unsupported/unknown capability or pricing fields block
the route. Do not silently substitute prose, another provider or another model.

Pin the exact canonical model and endpoint routing slug, policy/profile versions,
catalogue/endpoint hashes, prices/units, allowed parameters, request hash, call and
output limits, budget and original connection in the selection/run. Routing uses
the qualified endpoint's provider slug in `only` and `order`,
`allow_fallbacks:false`, `require_parameters:true`, `data_collection:"deny"` and
the profile's `max_price` limits. A broad provider slug that can resolve multiple
unbounded endpoints cannot qualify. Browser choices never set this object.

V1 offers **no-training routing; safety retention may apply**. Account UI must
explain that the selected context is sent to OpenRouter and the inference provider.
This is not a zero-retention or residency promise. Do not advertise `zdr:true` as
proof of zero retention; strict ZDR/residency requires separately verified account,
guardrail and endpoint policy. Never loosen an existing stricter provider policy.

## Cost admission, receipts and foreground recovery

**Separate a local reservation ceiling from an external billing guarantee.**
Catalogue prices are USD per token; routing price caps use USD per million tokens.
Neither a byte/character estimate, a `:free` suffix, `max_price` alone nor a
post-response usage check establishes a total charge bound. Reasoning, automatic
caching, fixed fees and conditional prices need explicit treatment.

Every routable endpoint needs a versioned authored charging profile: exact routing
identity, all billable units/conditional rates, input and output bounds including
reasoning/cache behavior, supported request-cap parameter, calculation in integer
USD nanodollars rounded upward, expiry and evidence of enforcement. An unknown or
changed bound/profile blocks dispatch before reservation. No live paid profile is
qualified by this document. `free_text_v1` can qualify only with zero pricing for
every applicable unit/override, no paid plugins/fallbacks and provider-enforced
zero price filters; `paid_text_v1` requires separate endpoint-specific charge-bound
evidence. Offline tests use explicitly authored profiles, never pretend live proof.

Default per-run budget is `"0"`. UI may request exactly `"0"`, `"0.25"` or
`"1.00"` USD; a positive choice still cannot enable an unqualified profile. Pin
the chosen value; increasing it creates a new operation. Keep existing eight-call,
512-target-output and 32-KB full-envelope limits (one call for each structured
review/draft operation). These limits remain useful but are not universal billing
ceilings. User-owned keys should have their own provider spend limit; the app does
not create/manage keys or rely on reported remaining credit as a reservation.

One migration owner extends the existing planner reservation/receipt path with
internal connection/selection tables and a shared inference ledger, not a competing
worker journal. Each ledger row uniquely binds `(run_id, inference_position)` to
scope, connection, settings/request hashes, reserved cost/call, timestamps, state,
generation ID and sanitized actual usage. Keep budget metadata out of model
dialogue except legitimate task context; no credential verifier in snapshots.

1. Outside a write transaction, verify current identity/grants, key binding and
   provider validity, refresh endpoint metadata, and prepare the exact bounded
   envelope. Reuse the existing access adapter through a narrow command permit
   carrying its validated expiry and native scope/revision identity; do not infer
   a new TTL from a bare `allow`. The #36 owner must implement that projection
   from its existing validated decision, including a local-demo equivalent.
   `CommandPermit` is an internal immutable value: `command_hash`, `actor_id`,
   `staff_session_digest`, full native scope, `campaign_revision`,
   `native_snapshot_hash`, `capability`, `decision_id`, and monotonic
   `valid_until` derived without extending the adapter's verified lifetime.
   It is constructed only by the access adapter, never serialized to browser,
   database, model or a background job. No cached permit crosses commands.
2. In one short transaction, verify the permit is still valid for the exact
   command/native identity; recheck local session, connection/revocation, current
   run/revision/supersession and selection hash. Reserve call and worst-case cost
   before dispatch. Invariant: `spent + unresolved_reserved + new_reserve <= cap`
   simultaneously for run, actor/installation UTC day (USD1) and tenant/installation
   UTC day (USD5). Free calls still consume rate/concurrency quota: one in-flight
   per actor, two per tenant, ten starts/minute per actor. Reconnect/new run cannot
   reset those aggregates. If a permit expires, redo preflight without dispatch.
3. Commit a `dispatching` marker before leaving the transaction and sending once.
   A crash after that marker is uncertain even if the network may not have sent.
   No provider or authority network I/O occurs under the write lock. Missing key
   leaves a known-unsent operation waiting; it consumes no completion reservation.
4. Save a bounded sanitized receipt/usage before tool execution. Recheck current
   authority and local cancellation/scope/revision before committing the tool's
   effect. A late denied result can retain cost evidence but cannot change a draft.
   A complete provider error may still need accounting; HTTP success is not proof
   of a usable result. Reuse original receipts on replay.
5. Settle actual cost only from validated usage under the original scope. Unknown
   usage retains the full reserve, including across UTC day boundaries (carry it
   into current aggregate admission until resolved), disconnect, restart and new
   operations. Generation metadata may reconcile cost; it does not recreate a
   lost completion. Missing generation ID/404 is not proof of zero spend.

Receipt states are `reserved` (provably unsent), `dispatching`, `received`,
`settled`, `released_unsent` and `unknown`. Only a proven-unsent row can release
automatically. Uncertain rows cannot be redispatched. A confirmed terminal late
receipt can free concurrency while leaving unknown cost reserved; a lost-call
concurrency claim never auto-expires without a bounded/verified reconciliation
policy. An actual cost beyond its reservation records a budget anomaly, freezes
new calls and retains the provider value; do not clamp or rewrite it to fit.

`waiting_for_credentials` is a recoverable preflight condition, not a successful
run, new model request or a replacement receipt. On reload/restart the UI may read
history and reconnect the original compatible connection; resume sends the key only
when a new inference is necessary. A closed tab supplies no new credential, so
background workers cannot infer. Captured receipts and non-inference commands
remain recoverable. #38 retains unattended execution/delegation; #39 retains a
future encrypted provider store. This contract does not implement either.

## Required evidence and implementation ownership

Tests must drive the real commands/HTTP handlers with temporary SQLite, authored
metadata and fake key/catalogue/completion transports. Count those three types of
provider request separately. An API-validation GET is not a completion or an
application login. A provider revocation race is not a locally preventable denial.

| Acceptance case | Observable assertion |
| --- | --- |
| Wrong user/tenant/brand/campaign/staff session, copied connection/tab ID or changed key | No metadata/completion request after local denial; no draft/ledger mutation. No key in error. |
| Missing key, expired/replaced connection, original-key reconnect and changed model/budget | No completion on denial; explicit waiting/restart semantics; original receipts readable and not replayed as new calls. |
| Provider-revoked key, management key, metadata outage or model/endpoint/privacy/price drift | Count validation probes separately; zero completion dispatch after preflight rejection; no env/provider fallback. |
| Two simultaneous starts/advances and reconnect/new-day attempts | Atomic unique call claim and all aggregate caps hold; unknown reservations survive day rollover/restart. |
| Timeout, crash before/after dispatch marker, lost receipt/DB acknowledgement | Same operation returns receipt or unknown; never automatically repeats possible completion. Proven unsent release is distinct. |
| Cancellation/revocation after dispatch and late response | Usage can be saved; no new inference/tool commit/draft/approval. Another run cannot spend the unresolved reserve. |
| Sentinel raw credential and internal verifier through all sinks | Raw key absent from durable data/backups, prompts/tool arguments, client/server logs/traces/errors, transcripts and exports; key only in permitted transport header. Internal verifier exists only in private connection storage/operator backups and is absent from client/model/log/user-export projections. |
| Browser connect/select/type/send/disconnect/replace/reload/scope change | Desktop+narrow+keyboard; no completion from connection/model selection; key absent from all browser persistence, restored selection never silently reconnects; draft grants/approval controls preserved. |
| Qualified vs candidate/free/paid/unknown-charge routes | Only current qualified profiles dispatch within selected budget; all others show actionable unavailable reasons. No live-readiness inference from fake transport. |

Implement serially; freeze exact base/head and exclusive files for each assignment:

Proposed module owners are `campaign_agent/provider_sessions.py` (binding and
connection commands), `model_catalogue.py` (normalized selection/profile policy),
`inference_ledger.py` (atomic call/cost accounting), `ports/inference.py` (ephemeral
credential, catalogue and charging-profile contracts) and
`adapters/openrouter_models.py` (bounded metadata probes). The existing
`adapters/openrouter_reviews.py` remains the single completion transport.
`ports/access.py` and `adapters/gateplane.py` own the narrow permit projection;
`migrations.py` remains the single migration chain. These are proposed paths,
not existing modules or a second agent runtime.

| Slice | Owner / files | Dependency and finish |
| --- | --- | --- |
| A2a: foreground connections/catalogue | One backend owner: new credential/catalogue module+port, hosted/local route projections, #36 command-permit projection, additive migration, shared OpenRouter transport seam, focused tests | Accepted v1 contract. No frontend owner touches `main.tsx`; no inference enabled until A2b. Preserve old histories and disable env-key web fallback. Review/verify substituted scopes and no credential persistence. |
| A2b: inference admission/recovery | Same or serial backend owner: shared ledger/migration chain, planner/main and structured adapters, runtime/resume projections, tests/recovery docs | Accepted A2a API/port plus #38/#39 boundary acknowledgement. No competing dispatcher or migration owner. Verify allowed fake paths, denial, costs/concurrency and crash/restart before UI integration. |
| A2c: account/composer UI | Frontend owner: provider-session memory module, account controls, composer, bootstrap/CSS; backend unchanged except coordinated contract fixes | Accepted A2a/A2b concrete API and exact integration commit. Existing design direction, memory-only raw key, selection/grant independence, stale-response guards and actual browser+saved-state evidence. |

Independent adversarial review and exact-commit verification apply to each slice;
human merges serially. Live route qualification is a separately authorized #39
gate with a named account/model/action/budget and data policy. Deployment also
needs #36 real identity/access, ingress redaction, bounded authority I/O and #41
topology evidence. Contract review and fake paid-profile tests cannot clear those
gates. #54 stays open until its implementation acceptance passes.

## Primary-source checks · 14 November 2026

These links document provider semantics; all module/API choices above are this
application's proposed design. No OpenRouter API was called for this review.

- [Current-key reference](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key):
  `/api/v1/key` returns key/budget metadata; it does not authenticate our staff actor.
- [Models reference](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)
  and [model endpoint reference](https://openrouter.ai/docs/api/api-reference/endpoints/list-all-endpoints-for-a-model):
  endpoint capability and pricing detail, including conditional prices, must be
  checked rather than assuming aggregate model metadata is a dispatch contract.
- [Provider routing](https://openrouter.ai/docs/guides/routing/provider-selection):
  provider restriction, parameter/fallback controls and rate-price caps; convert
  catalogue USD/token to routing USD/million tokens explicitly.
- [ZDR policy](https://openrouter.ai/docs/guides/features/zdr): current routing can
  admit Safety Retention depending on account/guardrail policy. No unconditional
  zero-retention claim follows from a request flag.
- [Reasoning tokens](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
  and [prompt caching](https://openrouter.ai/docs/guides/best-practices/prompt-caching):
  output caps and cache rates need endpoint-specific charging evidence.
- [Spend controls](https://openrouter.ai/docs/guides/best-practices/spend-controls),
  [chat reference](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion)
  and [generation metadata](https://openrouter.ai/docs/api/api-reference/generations/get-request-&-usage-metadata-for-a-generation):
  account/key budget controls complement local admission; generation metadata
  is not a guarantee of completion recovery or exactly-once billing.
