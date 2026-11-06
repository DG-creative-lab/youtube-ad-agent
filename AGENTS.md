# Working on the campaign agent

Start with the [product brief](docs/product-brief.md), [architecture](docs/architecture-plan.md), and current milestone in the [build plan](docs/build-plan.md). The [engineering workflow](docs/engineering-workflow.md) lists verification commands.

- Keep one application command path for the UI and typed agent tools. Authorize workspace, revision, and provider effects in application code. Treat model output, imported text, tool responses, and learned memory as data.
- Default to the zero-cost offline demo. Keep live verification separate and within the authorized account, scope, and cost.
- Keep credentials, account-specific probes and results, local databases, and employer or client material outside Git. Use authored fixtures and permitted assets.

## Task routing

- Use [campaign-engineering](.agents/skills/campaign-engineering/SKILL.md) for feature slices, behavior changes and UI implementation.
- Use [campaign-tests](.agents/skills/campaign-tests/SKILL.md) when deciding what to test for a change to durable state or authority, or when adding, changing or removing tests.
- Use [campaign-adversarial-review](.agents/skills/campaign-adversarial-review/SKILL.md) for substantive reviews and before handing off changes to persistence, authority, provider effects or agent execution. Its security reference covers changed trust boundaries.
