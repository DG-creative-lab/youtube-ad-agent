# Staff access boundary and offline contract fixture

13 November 2026 · [Issue #36](https://github.com/DG-creative-lab/youtube-ad-agent/issues/36) · [Tenancy](tenancy.md)

## Implemented slice

The ASGI entrypoint invokes the existing campaign commands. Staff and public
viewer applications have separately pinned origins. The existing loopback
`http.server` remains the portable local demo; it is not wrapped or exposed as a
hosted server. The fixture CLI uses Uvicorn with one worker, loopback binding,
forwarded-header trust disabled and access logs disabled.

`StaffSessions` stores hashed opaque session handles, a server credential
reference, exact issuer/subject/upstream-session binding, selected native campaign,
CSRF secret and bounded expiry. It stores neither bearer tokens nor role-derived
permissions. `IdentityVerifier.verify_current` is a trusted upstream boundary,
not a JWT decoder. Each private command rechecks the active identity profile and
Gateplane context. Hosted composition requires HTTPS and a Secure, HttpOnly,
host-only session cookie. Only the explicitly constructed loopback fixture
permits HTTP and synthetic profile selection.

A client/brand/workspace selector grants no authority. `/api/session/context`
resolves a candidate campaign through immutable product ownership, checks the
returned application/installation/tenant/workspace and actor binding, and obtains
current read access before changing the session. Browser actor/role headers and
local operator tokens cannot replace this path. The planner clears cached run,
conversation and request state when the person or campaign scope changes.

`GateplaneAccess` uses the [pinned producer schema and product hash profiles](../campaign_agent/contracts/README.md).
Each check has fresh request/correlation identity and binds the exact native
owner, revision, snapshot digest and command inputs. Responses must match that
request, actor and target. Human workspace decisions need current membership
versions. Unknown versions/fields/obligations and unsupported obligations fail
closed. `approval_required` is a denial, not product approval. The adapter uses
monotonic elapsed time from before the decision call, a maximum five-second use
bound, credential expiry and current native facts. It does not cache positive
access across HTTP requests or treat historical receipts as credentials.

Capabilities intersect the product's existing per-request draft mandate and
exact package approval. The fixture buyer can prepare a draft but cannot approve
or export it. A reviewer can approve/export/setup but cannot draft as that buyer.
A platform administrator receives no implicit campaign approval. Resumed work
uses the current staff request; no unattended worker or delegation is introduced.

## Public comparison authority

Exporting an exactly approved package may publish its comparison contents under
opaque, expiring links. This requires current export access and does not alter
the approved snapshot/fingerprint. Public routes resolve client, brand, campaign,
content and permitted media server-side; callers cannot select them using an
arbitrary creative or content digest. The public app has no staff API, workspace
listing or arbitrary-file route, even if a staff cookie is sent to it.

Visits and events retain their native campaign. Active link checks and accepted
viewer writes share the SQLite transaction. Current media must match the
published contents. A revoked/expired link cannot open media or submit events.
Existing published links continue during a staff authority outage; they never
consult or acquire staff permissions. Private reads and new effects fail closed.
Local logout remains available during an authority outage.

The staff package API retains its original package/fingerprint and adds public
comparison links as separate transport metadata. Preview media remain private.
The simulated setup uses those already published destinations, and delivery
review reads the corresponding link activity. The offline acceptance journey
covers buyer draft → separate reviewer approval → export/publication → simulated
paused setup/read-back → public completion → correlated campaign observation.

Publication leases in the fixture last one hour. Expiry/revocation is enforced;
renewal, retention and production ad-link lifecycle require explicit operational
and provider rules before deployment. Re-export and setup validation return an
actionable conflict if any existing publication for that package has expired or
been revoked: prepare and approve a new package revision before exporting.
Export fails atomically rather than returning empty or partial comparison links;
retrying it does not renew or reactivate old links. Existing verified setup records are never
silently rewritten to point at a different link. Public instruction-experiment
publication and full hosted feature parity remain integration work; the portable
local workflow is retained. This slice does not expose arbitrary experiment IDs
through the new public viewer.

Setup validation rechecks the exact saved destinations, including when reusing a
validated setup and after provider validation. Creation rechecks them again after
reserving the operation and completing its current access check, immediately
before dispatch. Expired/revoked publications return the same republication
conflict. A failed pre-dispatch check releases the known-unsent reservation with
no provider call; it does not replace the saved links. An already dispatched or
uncertain operation retains receipt/read-back recovery without redispatch, even
if its publication subsequently expires.

## Run locally

Install once into an isolated environment. The CLI accepts only a fresh or already marked fixture database and refuses
existing product data. Restart retains native campaign/evidence state but clears
fixture sessions, requiring a new synthetic sign-in. Registry access may be needed for the
initial install; tests and the running fixture make no provider network calls.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
pnpm --dir web/planner build
.venv/bin/python scripts/hosted_access_fixture.py --db /tmp/hosted-access-fixture.sqlite3
```

Open `http://127.0.0.1:18985/fixture`. Choose **buyer-a**, prepare the offline
example, and verify approval is denied. Return to `/fixture` and choose
**reviewer-a**. The campaign draft remains, while the buyer's conversation is not
shown. Approve and export the package, then validate and create the simulated
paused setup. The comparison links open on the separate viewer origin. Choose
**buyer-b** to inspect the independent client workspace. All people, decisions,
media and deliveries are authored fixtures; this is not real sign-in.

```sh
.venv/bin/python -B -m unittest discover -s tests -v
```

## Remaining activation gates

The real Gateplane Python client (#81), lean service (#78), registered issuer and
maintained OIDC callback/session adapter (#77), control credential binding and
composed service/issuer verification remain dependencies of #36/#83. No real
Gateplane service, issuer, paid model, ad provider, customer data or hosting is
activated here. The factory deliberately has no default real identity verifier
or local-operator fallback. Browser fixture selection is unavailable in hosted
HTTPS composition.

SQLite/private assets, durable workers and budgets, provider connections,
privacy/audit administration, operations and composed pilot release remain
#37–#42. No multi-worker, distributed revocation, complete security hardening or
enterprise readiness claim follows from the offline fixture results. The
cross-service revocation race remains bounded by the accepted decision-use
window; it is not an atomic transaction with Gateplane.
