# Live campaign capability benchmark · #123

The companion task corpus defines 20 realistic campaign requests and a four-part
0–2 quality rubric before runner implementation. Fourteen development tasks cover
recommendations, facts, measurement, classification, explicit draft authority and
catalog injection. Six evaluation-only tasks cover unavailable actions, missing
reporting, follow-ups, limited budget and unverified sources. These authored tasks
and proposed rubrics need domain-review calibration. They are not independent
expert labels, a representative user distribution or a statistically powered pilot.

Expected state and authority are graded in code. Recommendation quality is graded
separately by a reviewer using task-specific criteria, actual tool results and the
saved outcome. No LLM judge or model self-rating is treated as a validated grade.
A successful HTTP response or saved reply alone cannot pass the capability benchmark.
The rubric permits equivalent valid approaches and does not prescribe tool order.

The evaluation-only split is visible in the repository, not a secret test set.
Keep its grading criteria and reference facts out of model prompts and skill
examples; develop improvements against the development split first. A future
independent set and user pilot are needed to measure generalization and usefulness.

Live execution must use the same qualified foreground provider path and application
commands as the protected preview, with an isolated authored native campaign per
trial. It must never touch the hosted invite database or live ad/voice services.
Model, provider route, source revision, prompt/settings, corpus digest, usage,
duration and outcome must be recorded. Each conversation turn has the existing
application budget; a whole-batch envelope must be authorized before any live work.
Unknown outcomes stop the batch without retry. Keys remain process-local; private
trial evidence and review packets remain under ignored `.local/` with restricted
permissions. Public summaries exclude prompts, replies and raw provider errors.

The required CI gate remains deterministic and keyless. Contract and authored
transport tests verify this benchmark's runner and graders without claiming live
capability. Repeated real-model trials, human-reviewed quality scores and a fair
baseline comparison remain necessary before making an effectiveness claim.

## Plan without a key

```sh
.venv/bin/python scripts/evaluate_live_capability.py
.venv/bin/python scripts/evaluate_live_capability.py plan --split all
```

The default lists the development tasks and rubric without making network calls.
CI publishes the all-task plan beside the deterministic gate's artifact. The
old #51 corpus and policy simulation are unchanged. The new corpus is SHA-pinned;
edited criteria cannot silently become an accepted benchmark version. Updating
tasks or criteria requires an explicit reviewed version, not automatic rebaselining.

## Run an explicitly authorized sample

From a clean committed checkout, this example permits one task and one trial,
with a $0.25 local ceiling. It is a smoke sample, not full benchmark acceptance:

```sh
.venv/bin/python scripts/evaluate_live_capability.py run-live \
  --case CAP123-001 --trials 1 --model openai/gpt-4.1-mini \
  --max-run-cost-usd 0.25 --max-total-cost-usd 0.25 \
  --output-dir .local/live-capability/mini-smoke
```

Enter the key only at the hidden prompt. No key argument or automatic environment
key reuse is supported. This command spends the authorized provider account's
balance. Set a spending limit on the provider key too: our reservation ceilings
are not an external billing guarantee. A `$0` run requires a currently qualified
zero-price route; free-provider rate limits are reported as infrastructure results.

Use `--case` repeatedly to select tasks, or `--split development`, `holdout` or
`all`. A complete benchmark uses all 20 tasks and at least three trials per task.
The six evaluation-only cases remain separate from development, despite being
visible in source. Multi-message tasks retain one real conversation and receive
an independent application run ceiling for each user message. The batch envelope
therefore counts messages as well as trials. For example, CAP123-018 has two
messages: three trials at $0.25 require a $1.50 envelope. Unused reservations are
not a prediction of actual spend. The command validates the whole envelope before
requesting a key or making a provider call; it never silently shrinks the task set.

Each trial uses a fresh authored SQLite campaign and the exact preview command
composition, qualified metadata, pinned provider route and receipt accounting.
Fictional catalog rows enter the existing `creator_supplied` schema because the
benchmark author supplies them; their `authored:` references and catalog label
retain the fixture provenance. No real inventory, ad delivery or asset production
is implied. No grading rubric, task criteria or reference answer enters the model
context. Placement classification uses the selected live main model, not a fixture
classifier. No alternative agent loop or task-script fallback is installed.

A run is bounded by the existing eight-call application limit per user message
and a trial deadline checked between commands; an in-flight bounded provider
request may finish after that deadline. Provider/model errors receive separate
codes. Provider failures, unknown billing, safety failures and unexpected execution
errors stop remaining trials. Unknown outcomes are not retried. Inspect the retained
receipt journal before authorizing any subsequent work; this tool does not add a
second reconciliation policy. Checkpoints preserve incomplete work on interruption.

## Review actual answers

The new output directory has mode 0700; journals and files use 0600. Each trial
contains `campaign.sqlite3`, `trial.private.json`, a readable `review.md` and a
`review.json` template. The packet contains the actual conversation, tool results,
before/after facts, provider settings and diagnostics.
It also retains the exact outbound model request body and its hash for diagnosing
context, tool-schema or prompt problems; authentication headers are never captured.
These request bodies stay in private evidence, outside public summaries. Read and fill
the template's four scores, critical-violation check, reviewer and evidence-based
notes. These are human judgments; the runner never generates positive scores.

Score each dimension 0 (incorrect), 1 (partial) or 2 (complete), using the more
specific anchors and task criteria in the packet. All dimensions must be at least
1, the sum at least 6/8 and critical violations empty. An excellent-sounding reply
cannot compensate for a failed state or authority check. Missing review fields
remain pending. Reviews are bound to the exact task, code, rubric and trial digest;
stale, swapped, missing or edited trial evidence cannot silently become a pass.
These checks detect accidental evidence mixing; they are not cryptographic
attestation against someone deliberately rewriting the entire report and review.

```sh
.venv/bin/python scripts/evaluate_live_capability.py grade \
  --run-dir .local/live-capability/mini-smoke --name reviewed-v1
```

Grading writes new JSON and Markdown reports without overwriting prior reports.
`summary.md` and graded summaries exclude raw prompts/replies and review notes;
private packets retain them for diagnosis. Do not publish the whole private run
directory. After review and known billing, remove it manually under the local
retention policy. Never delete an unknown-outcome journal merely to start fresh.

The report separates task failures, actual authority failures, provider errors,
model errors, pending reviews and unrun tasks. Every planned trial remains in the
overall success denominator. Per-dimension review counts/scores and failure codes
guide diagnosis. Known cost, billing completeness, cost per successful task and
recorded mean duration are separate metrics; missing billing is not zero cost.
Until all planned evidence and reviews are complete, the final success rate is
unknown; a separate confirmed-success lower bound is shown. Pending reviews are
not reported as either proven capability successes or a measured zero-quality agent.
The duration covers the local preview command flow and provider work, not hosted
Turso performance or a browser load benchmark. Small samples and repeated trials
do not establish statistical significance or real-world campaign lift.

Exit 2 means invalid configuration/evidence; `run-live` exits 1 while review is
outstanding. `grade` exits zero only for all 20 tasks with at least three trials
each, actual live execution and every automated and human grade passing. A fully
reviewed subset can have `status: pass` while `full_benchmark_passed` remains false.
Authored-provider tests always retain fixture provenance and cannot qualify as a
live benchmark. A full pass is against the proposed rubric, whose domain-review
calibration remains explicitly unvalidated; it is not a product-effectiveness claim.

## Compare a candidate with a baseline

```sh
.venv/bin/python scripts/evaluate_live_capability.py compare \
  --baseline .local/live-capability/baseline/reviewed-v1.json \
  --candidate .local/live-capability/candidate/reviewed-v1.json
```

Comparison requires the same frozen tasks, repetition count and run ceiling,
complete evidence and reviews, and actual live provenance. It rejects incomplete
or mismatched data rather than excluding failed/unrun trials. Reports retain model,
route, prompt, source and settings so changes remain visible. Deltas are descriptive;
compare one intentional change at a time and use human review before promoting
an improvement. There is no automatic prompt/skill rewrite, RLHF or model training.

## Prepared Mini / Terra comparison · 20 November 2026

Use `openai/gpt-4.1-mini` and `openai/gpt-6.1-terra` on the **same clean source
revision**, planner prompt `campaign-planner-v8`, frozen v1 corpus and unchanged
`campaign-quality-v1` rubric. Start with one trial each of CAP123-001 (campaign
advice), CAP123-009 (classification advice without saving), and CAP123-011 (an
authorized unapproved placement draft). These are development cases, not the
evaluation-only split. The earlier Mini trial on v7 is historical diagnostic
evidence; do not present it as a model-only comparison with Terra on v8.

Prepare both plans without credentials or network calls:

```sh
.venv/bin/python scripts/evaluate_live_capability.py plan \
  --case CAP123-001 --case CAP123-009 --case CAP123-011 --trials 1 \
  --model openai/gpt-4.1-mini --max-run-cost-usd 0.25 --max-total-cost-usd 0.75
.venv/bin/python scripts/evaluate_live_capability.py plan \
  --case CAP123-001 --case CAP123-009 --case CAP123-011 --trials 1 \
  --model openai/gpt-6.1-terra --max-run-cost-usd 0.25 --max-total-cost-usd 0.75
```

This proposes six conversation runs, $0.25 each, a $0.75 envelope per model and
**$1.50 across both models**. It does not authorize spending. A smaller first
check can use only CAP123-001 once per model: $0.25 each, $0.50 combined. After
explicit account/budget approval, replace `plan` with `run-live` and give each
model a different new `.local/live-capability/` output directory. Enter credentials
only at the hidden prompt. Run sequentially and inspect the first model's report
before starting the second; execution/provider/safety errors or unknown billing
stop the sample across models as well as inside each batch. Do not chain these
paid commands into an unconditional shell batch.

Both use the existing eight-call, 512-output-token and at-most-32,000-input-token
profile and 180-second trial deadline. Neither receives a rubric, reference
answer, task-specific prompt patch or fixture response. Record the actual pinned
route, settings, prompt/source revision and usage, including default reasoning
behavior. A different provider or reasoning configuration is a visible comparison
factor; this is a comparison of deployed configurations, not a pure causal test
of model weights. Do not silently increase Terra's limits after a failure. Any
changed configuration requires a separately named run and matched rerun where
appropriate. One trial per task is a smoke sample; repeat successful configurations
at least three times before drawing a reliability conclusion.

At preparation time, standard catalogue rates are Mini $0.40 input / $1.60 output
and Terra $1 input / $5 output per million tokens. Terra is more expensive per
token. Its Flex route may have lower rates and different latency; live endpoint
qualification decides the actual pinned route. Prices are observations, not a
forecast or guaranteed invoice. [Mini](https://openrouter.ai/openai/gpt-4.1-mini)
· [Terra](https://openrouter.ai/openai/gpt-6.1-terra).

Terra's public routes advertise tool calling and prompt-length price tiers.
The qualifier accepts a tier only when its known `min_prompt_tokens` threshold
is strictly above the enforced input ceiling; applicable or unknown conditions
remain blocked. Original endpoint metadata stays fingerprinted and is revalidated
before dispatch. OpenAI documents Terra tool calling through Responses, while
OpenRouter advertises normalized tool support. Metadata qualification is **not**
proof of successful tool-call interoperability. Verify the first live call and
retain any provider failure rather than treating it as a quality score or silently
switching API, route, model or budget. [Terra API contract](https://developers.openai.com/api/docs/models/gpt-6.1-terra).

Review the saved answers using the frozen task-specific criteria and all four
dimensions, alongside state/authority checks. In diagnosis, distinguish an invalid
tool argument, failure to recover, an omitted requested answer, an unsupported
claim and a provider/configuration failure. Compare reviewed success, dimension
scores, tool rejections, actual settled cost per success and recorded duration.
Human scores remain pending until a reviewer supplies them; proposed assistant
scores are not human-certified grades. Do not retune the v1 rubric to reward a
preferred model or claim campaign lift from this sample.

The reported $100/month OpenAI allowance has not been verified. These commands
authenticate to **OpenRouter**, whose billing is not established as covered by
that allowance. Direct OpenAI credits, eligible organization/project, expiry and
model restrictions need account verification before budgeting against them.
Using them directly would require a separately qualified OpenAI adapter through
the same application ports and benchmark, secure credential setup and receipt
accounting; do not send an OpenAI key to the OpenRouter prompt. Better ad copy or
a separate decision model can be evaluated in later scoped tasks after this
comparison; an allowance does not itself authorize a provider migration or spend.
