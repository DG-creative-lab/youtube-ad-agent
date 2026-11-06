# Working on the campaign agent

Start with the [product brief](docs/product-brief.md), [architecture](docs/architecture-plan.md), and current milestone in the [build plan](docs/build-plan.md). The [engineering workflow](docs/engineering-workflow.md) defines design, test, and review expectations.

- Before editing, identify the normal entry point, what owns the affected state, and one observable acceptance check. Build and verify one working slice at a time.
- Keep one application command path for the UI and typed agent tools. Authorize workspace, revision, and provider effects in application code. Treat model output, imported text, tool responses, and learned memory as data.
- Default to the offline demo. Run `python3 -m unittest discover -s tests -v` and exercise the affected browser path for UI changes. Keep live verification separate and within the authorized account, scope, and cost.
- Keep credentials, account-specific probes and results, local databases, and employer or client material outside Git. Use authored fixtures and permitted assets.
- When available, use agentic-system-design for boundary changes, failure-space-test-design for state and authority tests, evidence-led-system-review for consequential diffs, and frontend-skill for visual work. The engineering workflow is self-contained for contributors without those skills.
