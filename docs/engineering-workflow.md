# Engineering workflow

The staged map includes #87 foundation contracts/offline injection before #86;
#86 owns every pilot native participant and its minimal factory, with #87 final
external adoption and #88 consolidation afterward.

## Architecture migration gates

#83 was accepted in PR #90 at `7c139e19bfbf0d829b31f8d09320e912e5561f6b`.
On 16 November the user chose a smaller #84 dependency checker, superseding the
unpublished broad analyzer. The [ADR](hexagonal-architecture.md) and historical
[module map](hexagonal-module-map.json) retain application/migration obligations.
The [live policy](architecture-policy.json) classifies 67 Python files after the #85 policy slice by exact
path. Web/legacy-client inventory remains in the historical map; this checker
analyzes Python imports only. Tests are excluded consumers, never runtime dependencies.

Run from a committed candidate with the **current accepted integration base**:

```sh
python3 scripts/check_architecture.py --base-ref 9fabf358b30cbc794455c1da78440043593d1497
python3 scripts/check_architecture.py --base-ref 9fabf358b30cbc794455c1da78440043593d1497 --format json --details
python3 -m unittest discover -s tests -p test_architecture_boundaries.py -v
```

The example SHA applies to this first #85 slice. After each merge, use the latest
accepted base, not a historical SHA. CI supplies PR `base.sha` or push `before`,
fetches history, runs the selected base's checker from a temporary file when
present, then runs the candidate checker. Missing/nonancestor/self bases fail.
The first seed requires exact accepted #83, clean committed source, unchanged
protected application blobs/modes and a single candidate commit parented directly
to that base. Its CI synthetic merge may have exactly base/candidate parents and
the identical candidate tree. Other initial histories fail; seed replay cannot
accept a later revision. This is a one-time independently reviewed introduction.
Workflow/review/branch configuration is an external trust boundary: a candidate-
controlled workflow cannot make itself tamper-proof.

The checker parses imports at every AST depth, including functions and
TYPE_CHECKING. It resolves aliases, relative imports, package children and loaded
local initializers as module edges. Local modules take precedence over the finite
core stdlib permission list. Domain imports domain; ports import domain/ports;
application imports domain/application/ports; outbound imports domain/ports/outbound;
inbound imports domain/application/ports. Package markers are inert. Exact bootstrap
paths may import runtime roles, while support/developer tools are consumers only.
Core external imports outside the listed stdlib families and inbound sqlite3
imports are forbidden without a named existing exception. These permissions concern
imports: allowing datetime does not prove a call to datetime.now is deterministic.
Every edge within a cyclic strongly connected component is checked separately.
New/moved Python files need explicit classification; surviving roles cannot change
under the ordinary shrink gate.

The readable [baseline](architecture-baseline.json) has **86 module-edge exceptions** after the first #85 slice:
58 external imports and 28 direction violations (initial #84 seeded 88). Each has source, target, rule,
owner issue, whole-import removal milestone and reason. There are no source-site
IDs, compressed profiles or runtime-effect metadata. Repeated imports, different
aliases or symbols on an admitted edge remain admitted; the waiver covers that
module coupling. It does not authorize runtime effects. Missing/duplicate/malformed
configurations fail, including deletion of an empty baseline.

The checker recognizes one planned CampaignDrafts relocation from
`scripts/campaign_drafts.py` to `campaign_agent/application/campaigns.py`.
It permits only the five existing exceptions to move together, with unchanged
metadata, actual matching imports and an application role. The destination must
match the pinned original source exactly except for the default database path's
one directory-depth adjustment. This is not a general waiver-growth mechanism.
The checker change must be accepted on the current integration base before the
relocation can pass CI's trusted-base check. After the move, ordinary shrinking
rules apply. The existing selected-base trust boundary still applies.

To retire an exception, eliminate the forbidden module edge and remove its row.
Surviving metadata must be identical; new exceptions fail. Stale rows fail and
must be removed. Two accepted shrinks compare each candidate with its immediately
preceding accepted base. The tool compares only the selected base: choosing an
older ancestor does **not** establish cumulative retirement. No update or automatic
acceptance mode exists. `--details` adds current import lines and full ownership
rows to JSON. `--strict` rejects every active exception; zero means import-debt zero.
Exit 0 means pass, 1 means forbidden/strict import debt, 2 means invalid source,
configuration or Git trust (including stale exceptions).

**Limits:** this is a static Python import guard. It does not analyze dynamic
imports, exec/reflection, reexported symbol provenance, injected callbacks,
transitive calls, SQL/native handle flow, cache lifetime, runtime effects or web
imports. Behavioral/authority tests and human review cover those risks. Removing
an import, adding a port or passing strict does not prove the architecture migration
or its security/transaction requirements complete. The deeper use/partial-adoption
obligations in the accepted map remain review and migration acceptance criteria.

Initial #84 is merged in PR #91 and remains open for strict zero. #85 begins with
pure scope/error/video-ID ownership; orchestration and other policies remain. Then
#87 foundation → #86 whole pilot UOW → #87 external → #88 composition → #37 named
native graph → #84 import strict zero → #89 broader conformance. PostgreSQL/cloud
closure is separate. Keep the unchanged native recipe, behavior tests, canonical
portfolio and independent review/verification for actual migration slices.

Keep repo-wide rules in [AGENTS.md](../AGENTS.md) and load the relevant skill for the task. The repo skills carry the project-specific procedure. General design, testing and review skills can supplement them when the work calls for deeper analysis.

| Task | Playbook |
| --- | --- |
| Scope, dispatch, resume or integrate factory work | [Factory coordination](../.agents/skills/factory-coordination/SKILL.md) |
| Build a feature, change behavior or implement a screen | [Campaign engineering](../.agents/skills/campaign-engineering/SKILL.md) |
| Decide what to test or review existing coverage | [Campaign tests](../.agents/skills/campaign-tests/SKILL.md) |
| Review a consequential change or inspect a trust boundary | [Adversarial review](../.agents/skills/campaign-adversarial-review/SKILL.md) |
| Independently verify acceptance on an exact commit | [Campaign verification](../.agents/skills/campaign-verification/SKILL.md) |

## Factory handoffs

Use the [launch board](factory/launch.md) for issue dependencies and first-wave
handoffs. Copy the [task contract](factory/task-contract.yaml) before dispatch and
the [stage evidence record](factory/stage-evidence.yaml) for each build, review,
verification or integration pass. These templates contain unresolved fields and
are not active assignments or evidence of completed checks.

Freeze a reachable base/plan commit, accepted dependency contracts and exclusive
file/resource ownership. Isolate worker branches, databases, media and ports;
do not rely on another checkout's dirty files. Independent roles return evidence
to the coordinator. Integrate serially, refresh affected review and verification
on the exact resulting commit, and retain human merge authority. Skills guide
the work; executable checks establish the properties they exercise.

## Verification

Run the offline suite locally for behavior changes. GitHub Actions runs the same
Python checks and a separate planner build on pushes to main and pull requests.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -v
```

For planner changes, install the locked dependencies and run the existing
TypeScript check and Vite production build:

```sh
pnpm --dir web/planner install --frozen-lockfile
pnpm --dir web/planner build
```

CI pins Node.js 24.22.3 and pnpm 10.33.0, matching the planner's package-manager
version. Setup actions are pinned to full commit SHAs. Both jobs run without
provider credentials; dependency installation may access public package registries,
but application/provider checks stay offline. A passing build does not establish
browser behavior or live model quality.

Exercise affected UI behavior in the browser. Use the [design direction](design-direction.md) for visual and accessibility checks. Keep live model, provider and human usability evidence separate from the offline suite.

The [offline agent behavior portfolio](agent-behavior-evals.md) executes the frozen
authored corpus through native commands and temporary SQLite during normal
unittest discovery. Run its reproducible JSON report separately with
`.venv/bin/python scripts/evaluate_agent_behavior.py`; only a complete canonical
pass exits zero. Subsets and invalid or changed corpora cannot report full
portfolio acceptance. This checks command containment, not live model quality.
Runner/tests/documentation-only changes use the unchanged planner CI job for the
client invariant checks and build; they do not require browser verification.

The hosted access checks use Starlette’s in-process ASGI client with synthetic identity/access dependencies and temporary SQLite. Dependency installation may need registry access; the tests make no external provider calls. The original portable-demo runtime still uses the standard library.

Storage changes also run `tests/test_product_storage.py` against temporary native
histories and private media. The [storage/recovery guide](storage-recovery.md)
declares the single-instance topology, migration coverage, whole-store commands
and authority invalidation on restore. Use authored stores and temporary backup
destinations for these checks.
