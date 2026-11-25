# Offline agent behavior portfolio

The [demo release gate](demo-release-evals.md) runs this unchanged corpus alongside
the policy simulation and six learning-reuse cases, then publishes a combined CI
report with per-case traces. Canonical portfolio acceptance below remains scoped
to #51; hosted readiness and live model quality are separate results.

The [v1 corpus](../examples/agent-behavior-evals.v1.json) independently specifies
11 authored scenarios for existing campaign commands. The corpus was frozen
before runner implementation at version `1.0.0`, schema `1`, SHA-256
`9c082805b752a1c8393ec7b392e9ac11c8e28c3d261b25f3bed3579cc6592b32`.
Its provenance, input scripts, native outcomes and exact dispatch bounds are data.
Changes require a newly reviewed specification and accepted runner fingerprint;
editing an expectation cannot produce a canonical passing report.

Run from the repository root with the existing test environment:

```sh
.venv/bin/python scripts/evaluate_agent_behavior.py
.venv/bin/python scripts/evaluate_agent_behavior.py --output /tmp/agent-behavior-report.json
.venv/bin/python -m unittest discover -s tests -p test_agent_behavior_evals.py -v
```

The command creates fresh temporary SQLite databases and authored media, executes
the actual `AgentRuntime` / planner / typed dispatcher / application commands,
then reopens native state. No service, credential, installation or network access
is needed. The finite authored `next_turn` adapter supplies legal and malicious
requests; the simulated classifier uses the existing offline classification port.
Existing focused runtime, provider and recovery regressions remain in place.
The new test module executes the portfolio through normal unittest discovery and
tests reporting failures, rather than copying that regression suite.

| Case | Observable boundary |
| --- | --- |
| AB51-001 | Current capability facts, unavailable voice production and explicit draft mandates |
| AB51-002 | One focused clarification with no draft |
| AB51-003 | Current revision/placement facts and approval mismatch; reject fabricated action wording |
| AB51-004 | Forced placement save under Review only is denied |
| AB51-005 | Revoked current run grant blocks dispatch, including after reopening |
| AB51-006 | Same-brand foreign actor cannot read, resume or append to another conversation |
| AB51-007 | An independent edit invalidates a pinned revision and survives reopening |
| AB51-008 | Catalog payload observed before an invented-ID attack; legitimate source-bound save still succeeds |
| AB51-009 | Saved brief goal observed before an attempted approval tool; factual native reply |
| AB51-010 | Follow-up supersedes an in-flight valid save; late receipt cannot write |
| AB51-011 | Explicit placement grant saves an unapproved draft once; ambiguity, provenance and replay retained |

Each case compares actual persisted run statuses, steps/errors, transcript counts,
assistant wording, current draft/approval and adapter counters to the frozen
expectations. Historical revision rows and all unrelated native tables must remain
unchanged. Cases with historical approval also reread the exact old approved
package. Injection witnesses serialize the real model-port context/history and
check the named native tool result before returning the malicious request.

`main_model_dispatches` counts authored simulator calls and
`classifier_dispatches` counts the simulated classifier port. They are separate
from `external_transport_calls` and `effect_provider_calls`. Runtime completion
transports, socket connection/DNS entry points and setup-provider operations are
guarded and counted; attempted calls fail the case even if a caller catches the
guard's error. Ambient environment configuration is cleared during each fixture.
No corpus field selects an account, provider, credential, import, callable or shell
command. An unexpected extra model/classifier call fails instead of falling back.

The JSON report includes case IDs, corpus version and exact digest, specification
base, code revision/dirty flag, status, mismatch field names and observed native
evidence. UUIDs, timestamps, private paths and provider exception text are excluded
from case evidence. Compare `cases` across two fresh executions for reproducibility;
the code metadata can change when the checkout changes.

Only a complete canonical passing portfolio exits zero. `full_acceptance` means
complete canonical **portfolio** acceptance; it does not mean project release
acceptance. Release still requires a clean exact commit, independent review and
verification, and final CI. A development report can pass while recording a dirty
checkout.

```sh
.venv/bin/python scripts/evaluate_agent_behavior.py --case AB51-008
```

A subset records `partial: true`, retains unselected `notrun` rows, clears
`full_acceptance` and exits nonzero, even if selected cases pass. Unknown or
duplicate selections, missing/malformed/noncanonical/empty/incomplete corpora
are `blocked` with nonzero exit and no case execution. `--corpus` accepts only
the exact frozen bytes, including when copied to another path. Execution errors
and outcome mismatches are `failed`; available partial native evidence and
instrumented counters remain visible, and unavailable evidence is `null`.
Reports never overwrite an existing output file; an output failure exits `2` and
prints a blocked JSON report to stdout. Other incomplete/failing runs exit `1`.

The tests replace a proposed save with a factual reply and verify that the real
dispatcher leaves revision 1 unchanged and the CLI returns a failed report. They
also exercise counted, caught DNS attempts and a denied setup-provider call.
Disposable source fault injection can demonstrate the same nonzero failure
without changing the accepted corpus or committing a broken implementation.

These scenarios establish deterministic command containment for supplied authored
responses. They do not measure LLM instruction following, prompt-injection
resistance, answer/creative/classification quality, live billing or hosted readiness.
The current saved brief goal is campaign data; customer project guidance does not
exist. Instruction experiments, reporting and live foreground admission retain
their focused tests and separate authorization gates.
