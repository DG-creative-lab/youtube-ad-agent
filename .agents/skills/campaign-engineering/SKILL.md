---
name: campaign-engineering
description: Plan, implement and verify a feature slice, behavior fix or UI change in the YouTube campaign agent.
---

# Campaign engineering

1. Read the relevant [build milestone](../../../docs/build-plan.md) and [architecture boundary](../../../docs/architecture-plan.md). Trace the normal entry point through the application command to the state or effect it owns. Identify one user-visible acceptance check before editing. For a bug, reproduce the failure at that entry point when feasible.
2. Deliver the smallest usable slice. Reuse existing commands and adapters. Give a new interface or dependency a specific responsibility and a current caller. Keep provider mechanics behind existing ports. Keep a speculative prototype separate from the application.
3. When behavior changes, run the [offline checks](../../../docs/engineering-workflow.md#verification). For UI work, read the [design direction](../../../docs/design-direction.md), drive the changed browser path and check the resulting state or export. For visual changes, inspect desktop and narrow layouts. Report the exercised path and any provider or runtime behavior still awaiting verification.

For changes to a commit point or external effect, name the durable records, authority check and recovery path before implementation. Follow the test and review routing in [AGENTS.md](../../../AGENTS.md).

[pstack feature playbook](https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/playbooks/feature.md) · [pstack prototype playbook](https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/playbooks/prototype.md)
