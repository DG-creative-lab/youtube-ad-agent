---
name: campaign-adversarial-review
description: Review consequential changes to campaign persistence, approvals, provider effects or agent execution, including security and pre-handoff review.
---

# Campaign adversarial review

1. Establish the diff or design under review and the product outcome at risk. Read the [architecture](../../../docs/architecture-plan.md) and the executable paths that can affect that outcome, including unchanged callers and alternate writers. Trace entry point, identity, authority, commit or provider call, result and recovery.
2. State the invariant in observable terms. Select the failure paths the change actually makes possible. For example, can a stale package approval reach dispatch, can a cancelled worker commit late, can a retry duplicate an effect after a lost receipt, or can a partial report become a complete claim? Challenge the strongest assumption using a different reachable path or a realistic interleaving.
3. When the change touches untrusted input, credentials, authority, model tools or memory, read the [security boundary checks](references/security-boundaries.md). Use the smallest local test or inspection that establishes the outcome. Exercise the real entry point with a fake dependency when the disputed behavior is dispatch or recovery.
4. Report actionable findings by consequence. Give the trigger, impact, file and line, and the smallest effective fix. Separate reproduced behavior, source-only evidence and assumptions still requiring validation. Keep an explicit review read-only unless the task also authorizes fixes.
