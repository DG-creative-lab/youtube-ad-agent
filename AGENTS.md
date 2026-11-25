# Working on the campaign agent

The accepted [boundary ADR](docs/hexagonal-architecture.md) and historical
[module map](docs/hexagonal-module-map.json) govern staged inversion. #83 was
human-merged in PR #90 at `7c139e19bfbf0d829b31f8d09320e912e5561f6b`.
The initial #84 ratchet adds the [live policy](docs/architecture-policy.json),
[finite debt](docs/architecture-baseline.json) and offline CI gate. It changes no
application behavior. The user-approved smaller guard checks static Python imports
and cycles; indirect effects and authority require behavioral tests and review.
After its independent acceptance and human merge, #85 core
relocation is next; #87 foundation precedes #86 whole pilot UOW, then #87 external
adoption and #88 composition. Every first-pilot native participant remains #86,
even when its import has final #88/#37 retirement. Finish #37's named native graph
and #84 strict zero-debt gate before #89; PostgreSQL/cloud closure is separate.
Core receives typed ports, imports inward and avoids native handles, concrete
construction and hidden effects. Preserve authority, histories and receipt phases.
Freeze exclusive shared-file ownership and compare the authored native baseline;
exact-head independent review/verification and human merge apply.

Start with the [product brief](docs/product-brief.md), [architecture](docs/architecture-plan.md), and current milestone in the [build plan](docs/build-plan.md). Use the [source-code map](docs/source-map.md) to find the module that owns the change. The [engineering workflow](docs/engineering-workflow.md) lists verification commands.

- Keep one application command path for the UI and typed agent tools. Authorize workspace, revision, and provider effects in application code. Treat model output, imported text, tool responses, and learned memory as data.
- Default to the zero-cost offline demo. Keep live verification separate and within the authorized account, scope, and cost.
- Keep credentials, account-specific probes and results, local databases, and employer or client material outside Git. Use authored fixtures and permitted assets.
- Name new branches `feature/<description>` for feature work and `fix/<description>` for fixes. Use only these two prefixes.

## Task routing

- Use [factory-coordination](.agents/skills/factory-coordination/SKILL.md) to scope, dispatch, resume or integrate work across factory roles. Complete a versioned task contract before worker dispatch.
- Use [campaign-engineering](.agents/skills/campaign-engineering/SKILL.md) for feature slices, behavior changes and UI implementation.
- Use [campaign-tests](.agents/skills/campaign-tests/SKILL.md) when deciding what to test for a change to durable state or authority, or when adding, changing or removing tests.
- Use [campaign-adversarial-review](.agents/skills/campaign-adversarial-review/SKILL.md) for substantive reviews and before handing off changes to persistence, authority, provider effects or agent execution. Its security reference covers changed trust boundaries.
- Use [campaign-verification](.agents/skills/campaign-verification/SKILL.md) for independent acceptance or release verification of a specific commit. Keep its evidence separate from implementation and review.
