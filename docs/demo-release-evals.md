# Demo eval release gate · #123

This build combines the existing offline behavior portfolio, paired Bayesian
simulation and real-command learning checks into one deterministic gate. It adds
no application endpoint, model framework, database schema or UI surface. The
deployed product uses live OpenRouter; recorded model responses belong to the
offline evals and local rehearsal.

```sh
.venv/bin/python scripts/evaluate_demo_release.py --output-dir /tmp/demo-evals
```

Use a new output directory and a clean committed checkout. An existing directory
is never overwritten or mixed with new traces. Exit zero requires the complete
canonical offline gate; dirty, changed-during-run, missing, partial, noncanonical
or failing evidence exits nonzero. A dirty development checkout still produces
suite diagnostics but cannot certify the gate. Output failures exit 2.

## Frozen inputs and evidence

[The companion manifest](../examples/demo-release-evals.v1.json) was specified at
merged PR #129, before implementing this runner. Its SHA-256 is pinned in the
runner. It references the unchanged [11-case #51 corpus](agent-behavior-evals.md)
and the existing [policy specification](../examples/instruction-policy-comparison.json).
Editing expected outcomes or reducing the seed count cannot produce a canonical
pass. A deliberate specification update requires a versioned review, not an
automatic rebaseline. This fingerprint guard is not protection against a reviewer
accepting changes to both the runner and specification.

| Suite | Execution and acceptance |
| --- | --- |
| Agent behavior | All 11 #51 authored model scripts through the actual dispatcher and temporary native commands. Retain exact target, authority, revision, provenance, transcript and replay expectations. |
| Policy simulation | All 13 scenarios × 24 seeds from #23–#27. Reproduce the previously published policy counts and paired outcomes, with per-seed evidence cutoffs and stream fingerprints. Check sparse/unresolved evidence and collection limits. |
| Learning reuse | Six companion cases through real campaign, experiment, finding and draft commands with temporary authored media. Compatible restart prepares the exact tested wording without approval. Missing permission, stale participant evidence, mismatched context, retired finding and foreign brand cannot write. Historical source approval and placements remain intact. |

The learning setup reuses the existing 2/20 versus 18/20 application walkthrough,
including actual viewer events, a saved snapshot and a finding reopened from
SQLite. The foreign-brand case provisions another workspace in the same database;
it does not simulate isolation merely by changing an identifier in an assertion.
No existing corpus is edited and no application policy is relaxed.

The simulation reports mistaken reuse, worthwhile effects not reused, extra visits
and net decision value for Bayesian, fixed-lift and a zero-cost keep/no-change
reference. The previously reviewed mixture gives Bayesian 69 wins, fixed 55 and
188 ties. Both mean values are below the keep reference under these assumptions.
Passing means reproducing the reviewed behavior, not making the Bayesian policy
look better or claiming real campaign lift. Future policy improvements need their
own reviewed experiment and held-out specification.

## Published report and failure checks

The output contains `report.json`, a readable `report.md`, three suite reports and
30 per-case JSON traces. Each trace carries code revision, manifest digest and
authored provenance; the summary links to each trace. Policy traces contain all
24 paired streams for their scenario. No credentials, private database files,
account probes, live prompts/responses or private model reasoning are imported.
Network, DNS, completion transport and setup-provider attempts are blocked and
counted, including caught attempts. Unexpected exceptions use static diagnoses.

Normal unittest discovery tests the gate itself. Fault-injection checks replace a
legitimate model action with an unavailable approval tool and simulate reuse of a
cached eligibility decision after new evidence. Both produce failing gate evidence
with the actual unchanged or incorrectly changed revision, rather than accepting
an expected denial as proof that the evaluator detects a regression.

CI runs the gate on its checked-out revision, appends the summary to the job, and
uploads only the authored report directory for 14 days using a SHA-pinned action.
Failed gate runs also upload their available evidence. Download the artifact to
follow its relative suite and trace links; the job summary also lists case IDs
and diagnoses. The separate planner CI job remains unchanged. CI workflow changes
are part of review; the candidate workflow cannot certify itself as tamper-proof.

## Separate gates still required

The [live capability benchmark](live-capability-benchmark.md) adds a separate
20-task corpus, optional repeated real-provider trials and explicit human grading.
Its keyless plan is published beside this gate's CI evidence. No live call runs
in required CI, and an unreviewed reply cannot count as a capability pass.

The report labels hosted smoke and live model quality as **not run**. It does not
import an old deployment pass or equate offline success to release approval. The
pitch release still needs review, CI and a browser check against the deployed
revision: avatar/account access, real model configuration, a saved conversation
reopened with its model and activity, and representative failure states. Use fake
providers for deterministic error coverage. Any live sample requires explicit
credentials, account scope and budget.

The old #123 requirement for an offline composer in the hosted preview is
superseded by the owner's live-only product decision implemented in PR #129.
Offline fixture interaction remains available in local evals/rehearsal. Learning
and policy simulation results do not score the quality of live model prose.

After the functional MVP, the [queued UI direction](design-direction.md#next-ui-build--owner-direction-19-november-2026)
covers softer corners, dark mode, collapsible navigation, artefact panels and
inline expandable agent activity. It is a separate build.
