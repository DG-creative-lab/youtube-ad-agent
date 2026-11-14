---
name: campaign-verification
description: Independently verify a campaign-agent slice or release against its task contract on an exact commit. Use for acceptance checks, fresh-state or restart verification, integration verification and truthful evidence handoffs.
---

# Campaign verification

1. Read [AGENTS.md](../../../AGENTS.md), the accepted task contract, issue acceptance
   criteria and [engineering workflow](../../../docs/engineering-workflow.md).
   Resolve the actual full base, head and integration SHAs and contract version.
   Derive expected behavior from those artifacts, not the builder's explanation.
   If a required contract/base is absent or changed, return blocked to the coordinator.
2. Verify in an isolated checkout at the named commit with clean tracked source,
   lockfiles and workflows. Record `git rev-parse HEAD` and `git status --short`;
   list generated artifacts separately. Keep databases, media and ports isolated.
   Do not fix source during this pass. Put fault injection in a separate disposable
   copy and never substitute its results for acceptance of the actual head.
3. Select checks for the changed outcome and trust boundary. Use existing
   [test guidance](../campaign-tests/SKILL.md) and verification commands. Run the
   offline suite for behavior changes; build the planner when affected. For UI
   changes, use the [design direction](../../../docs/design-direction.md), exercise
   the real browser path and inspect saved state or export as well as the screen.
   Check restart/replay, current access or provider denial when the slice makes
   those failures reachable. Include a legitimate allowed path for authority changes.
   Use [adversarial review](../campaign-adversarial-review/SKILL.md) for consequential
   source review; verification does not replace it.
4. Stay within the contract's commands, data, network and effects. Use authored
   fixtures and fake providers for offline checks. Never obtain credentials,
   spend or deploy to unblock verification. A required unavailable dependency is
   blocked; an inapplicable check is not_run with a reason. Do not weaken expected
   outcomes, silently skip a failing check or report source inspection as execution.
5. Return the [stage evidence record](../../../docs/factory/stage-evidence.yaml):
   exact commits, contract version, dirty status, cwd/commands/exit results,
   acceptance-scenario evidence, findings, limitations and next owner. Classify
   each check as executed, source_inspection or historical and its outcome as
   passed, failed, blocked or not_run. Historical/provider-simulated evidence
   cannot establish current integration success, live model quality, usability
   or production readiness. Leave observed provider/spend counts unknown unless
   established; do not invent zeros.
6. Recommend ready for human merge only when every required acceptance check has
   passed on the relevant final commit and material findings are resolved. Return
   needs repair for failures and blocked for unavailable required checks. New
   source commits require affected verification to run again; preserve prior
   evidence under its original SHA. Return to the coordinator; do not merge,
   close issues or dispatch dependent work from a verification-only assignment.
