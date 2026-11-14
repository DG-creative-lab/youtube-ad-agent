---
name: factory-coordination
description: Scope, dispatch, resume and integrate bounded campaign-agent work across builders, independent reviewers and verifiers. Use for factory task contracts, dependency readiness, worker handoffs, ownership conflicts or integration decisions.
---

# Factory coordination

1. Read [AGENTS.md](../../../AGENTS.md), the current [build plan](../../../docs/build-plan.md),
   [source map](../../../docs/source-map.md) and [launch board](../../../docs/factory/launch.md).
   Refresh the actual issue/PR state and remote base; a launch-board snapshot is
   not proof that dependencies are complete. Preserve release priorities.
2. Copy the [task contract](../../../docs/factory/task-contract.yaml). Fill every
   required identity, full base/plan SHA, integration target, outcome, scope,
   owned files/resources, acceptance scenario, dependency contract/version and
   role assignment before dispatch. Confirm that commits and handoffs are
   reachable by the assigned worker. An unresolved field, unaccepted dependency
   or overlapping ownership keeps the task blocked. Version contract changes;
   never let a worker silently reinterpret a dependency.
3. Give each builder an isolated checkout and `feature/…` or `fix/…` branch,
   authored fixtures, temporary database/media roots and distinct ports. Worktrees
   isolate files, not tools, credentials or shared services. Limit available data,
   network and effects to the contract; do not pass secrets or private customer
   material. Allow dependency installation only when explicitly in scope. Routine
   setup is not permission for provider calls, spending or deployment.
4. Dispatch the smallest dependency-ready slice with exclusive file/resource
   ownership. Keep one owner for a migration chain, dispatcher or shared bootstrap
   within a wave. Give research/design workers read-only boundaries. Route product
   changes to [campaign engineering](../campaign-engineering/SKILL.md), test decisions
   to [campaign tests](../campaign-tests/SKILL.md), and consequential reviews to
   [adversarial review](../campaign-adversarial-review/SKILL.md); reuse their rules.
5. Collect a separate [stage evidence record](../../../docs/factory/stage-evidence.yaml)
   from builder, independent reviewer and [verifier](../campaign-verification/SKILL.md).
   Transfer raw contract/diff/artifacts without leaking intended findings into an
   independent assessment. Require exact head SHA and truthful executed,
   source-inspection or historical evidence. Keep task stage distinct from issue
   state. A PR, assigned worker or green historical run is not accepted completion.
6. Stop affected work on changed contracts, overlapping ownership, inaccessible
   bases, required out-of-scope effects or unavailable verification dependencies.
   Return decisions to the coordinator; do not post messages or change external
   trackers unless the assignment authorizes those actions. Permit at most two
   repair attempts under the same contract before returning to specification.
7. Integrate accepted changes serially. After a rebase, merge or fix, identify the
   resulting commit and refresh affected independent review and verification.
   Preserve historical evidence with its original SHA; do not relabel it as a
   check of new bytes. Finish with findings, limitations and the next owner.
   Human merge authority remains in force; neither this skill nor a worker
   recommendation grants merge, deployment or live-effect permission.

On resume, reload the contract, accepted dependencies, current branch/head and
latest stage records. Reconcile stale worker results before dispatching another
attempt. Do not claim persistent sidebar threads or unattended scheduling unless
those mechanisms were actually created and observed.
