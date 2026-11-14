# Engineering workflow

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

The hosted access checks use Starlette’s in-process ASGI client with synthetic identity/access dependencies and temporary SQLite. Dependency installation may need registry access; the tests make no external provider calls. The original portable-demo runtime still uses the standard library.

Storage changes also run `tests/test_product_storage.py` against temporary native
histories and private media. The [storage/recovery guide](storage-recovery.md)
declares the single-instance topology, migration coverage, whole-store commands
and authority invalidation on restore. Use authored stores and temporary backup
destinations for these checks.
