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
