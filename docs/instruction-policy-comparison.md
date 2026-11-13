# Offline instruction policy comparison

Specification `instruction-policy-comparison-v1` · SHA-256 `b3cbb162d81450922aee7204bf6c14abec60621dc9d19c65d606a0a9df5a3175`

Reproduce from the repository root with `python3 -B scripts/compare_instruction_policies.py --output docs/instruction-policy-comparison.md`. Add `--json /tmp/instruction-policy-comparison.json` to retain every seed, cutoff, count and action.

## Frozen rules and scoring

Each scenario uses 24 held-out simulation seeds, 41000–41023. Two independent random draws per visit select its arm with equal probability and its outcome. All policies receive the same potential event stream and review cutoffs. Original and revised within-window completion probabilities remain constant within each scenario.

The Bayesian policy uses the application's pinned Beta(1, 1) prior, five-percentage-point target, +1/−9 reuse payoffs, zero keep payoff and 0.01-unit cost per requested extra batch. Its review point is 40 resolved visits, with one optional batch of 10 and a cap of 50.

The fixed-lift policy waits for 40 resolved visits, collects 10 when observed lift is between 0 and 10 percentage points inclusive, and otherwise reuses above five points or keeps. After the extra batch it reuses above five points or keeps. Both policies wait for unresolved outcomes.

Net decision value uses the known within-window fixture effect. Reuse earns +1 when that effect exceeds five points and −9 otherwise. Keeping and waiting at the final cutoff earn zero. Each requested batch costs 0.01 once. Waiting has no time penalty. Worthwhile effects left unreused include unresolved final waits.

## Aggregate results

| Policy | Reuse | Keep | Final wait | Mistaken reuse | Worthwhile unreused | Extra batches | Extra visits | Waiting reviews | Mean value | Value SD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bayesian | 43 | 197 | 72 | 5 | 130 | 62 | 620 | 1348 | -0.0244 | 1.1920 |
| fixed | 111 | 129 | 72 | 44 | 101 | 61 | 610 | 1346 | -1.0564 | 3.2454 |

Keeping without collection earns zero in this scoring system. Both policy means should be compared with that reference. The SD describes variation across this coverage suite, whose scenarios include different effects and evidence availability.


Paired net-value comparisons across 312 runs give 69 Bayesian wins, 55 fixed-lift wins and 188 ties.

## Results by scenario

| Scenario | True rates, original / revised | Bayesian mean value | Fixed mean value | Bayesian / fixed / tie |
| --- | --- | ---: | ---: | --- |
| no-effect | 30% / 30% | -0.3767 | -3.0033 | 11 / 1 / 12 |
| harm | 50% / 25% | 0.0000 | 0.0000 | 0 / 0 / 24 |
| clear-benefit | 20% / 55% | 0.7442 | 0.9583 | 0 / 15 / 9 |
| small-benefit | 30% / 37% | 0.0396 | 0.4554 | 3 / 10 / 11 |
| below-target | 30% / 33% | -0.3771 | -3.3783 | 12 / 1 / 11 |
| at-target | 30% / 35% | -0.3775 | -4.1279 | 13 / 1 / 10 |
| low-rates | 2% / 10% | 0.0392 | 0.4104 | 8 / 10 / 6 |
| delayed | 20% / 55% | 0.7442 | 0.9583 | 0 / 15 / 9 |
| late-conflict | 30% / 30% | -0.3767 | -3.0033 | 11 / 1 / 12 |
| sparse | 0% / 90% | 0.0000 | 0.0000 | 0 / 0 / 24 |
| absent | 20% / 55% | 0.0000 | 0.0000 | 0 / 0 / 24 |
| missing-time | 20% / 55% | 0.0000 | 0.0000 | 0 / 0 / 24 |
| cohort-conflict | 30% / 30% | -0.3767 | -3.0033 | 11 / 1 / 12 |

## Paired examples

Examples are the first three runs for each winner in specification and seed order.

| Winner | Scenario | Seed | Bayesian action / value | Fixed action / value |
| --- | --- | ---: | --- | --- |
| bayesian | no-effect | 41001 | keep / 0.00 | keep / -0.01 |
| bayesian | no-effect | 41002 | keep / 0.00 | reuse / -9.01 |
| bayesian | no-effect | 41006 | keep / 0.00 | keep / -0.01 |
| fixed | no-effect | 41020 | reuse / -9.01 | reuse / -9.00 |
| fixed | clear-benefit | 41000 | reuse / 0.99 | reuse / 1.00 |
| fixed | clear-benefit | 41001 | keep / -0.01 | reuse / 1.00 |
| tie | no-effect | 41000 | keep / 0.00 | keep / 0.00 |
| tie | no-effect | 41003 | keep / 0.00 | keep / 0.00 |
| tie | no-effect | 41004 | keep / 0.00 | keep / 0.00 |

## Existing assessment

The existing `evidence-reasons-v2` assessment runs through its real recorded-assessment and validation functions. It sees assigned participant visits and completions recorded by each cutoff, including completions after the Bayesian observation window. Its 20-visits-per-arm minimum remains intact.

Its native actions appear below at 340000 ms and at the final 650000 ms cutoff. The latter exposes the potential extra batch for a common full-budget observation. That exposure is supplied by the evaluator. The assessment specifies neither a batch size nor a reuse/keep terminal choice, so acquisition cost and comparable net utility are left unscored.

| Native action | Initial review | Full-budget review |
| --- | ---: | ---: |
| insufficient_evidence | 301 | 59 |
| keep_collecting | 5 | 166 |
| prepare_another_test | 6 | 87 |

Native counts below use the order insufficient evidence / keep collecting / prepare another test.

| Scenario | Initial review | Full-budget review |
| --- | --- | --- |
| no-effect | 23 / 0 / 1 | 1 / 11 / 12 |
| harm | 23 / 0 / 1 | 1 / 1 / 22 |
| clear-benefit | 23 / 1 / 0 | 1 / 23 / 0 |
| small-benefit | 23 / 0 / 1 | 1 / 12 / 11 |
| below-target | 23 / 0 / 1 | 1 / 11 / 12 |
| at-target | 23 / 0 / 1 | 1 / 12 / 11 |
| low-rates | 23 / 1 / 0 | 1 / 16 / 7 |
| delayed | 23 / 1 / 0 | 1 / 23 / 0 |
| late-conflict | 23 / 1 / 0 | 1 / 23 / 0 |
| sparse | 24 / 0 / 0 | 24 / 0 / 0 |
| absent | 24 / 0 / 0 | 24 / 0 / 0 |
| missing-time | 23 / 1 / 0 | 1 / 23 / 0 |
| cohort-conflict | 23 / 0 / 1 | 1 / 11 / 12 |

## Fresh-brief walkthrough

The separate integration example uses authored participant outcomes of 2/20 versus 18/20. The application returned `reuse` with probability 99.999957% of exceeding the target. Its real commands saved a finding, started fresh brief revision 4, reopened SQLite and prepared wording draft revision 5. The finding survived restart and the package requires buyer approval.

To inspect it in the planner, run the comparison with `--walkthrough-db /tmp/policy-walkthrough.sqlite3` using a new path, then serve that database with the portable demo.

## Assumptions and limits

All outcomes are authored simulations and all execution is offline with zero provider calls. The scenario mixture is a coverage suite and has no estimated frequency in real campaigns. Aggregate averages weight its scenarios equally. The observed ranking depends on the declared payoffs, collection band, sample budget and fixture probabilities.

Sparse has ten initial visits and absent has none. Missing-time removes the first arrival timestamp. Delayed records successes at 295 seconds, within the five-minute window. Late-conflict adds late completions to 40% of revised visits while both arms retain the same 30% within-window success probability. Cohort-conflict adds 20 visits per arm for each of rehearsal, fixture and unknown sources, with every revised nonparticipant visit completing. Those cohorts remain outside all decision denominators.

The walkthrough is a separate deterministic integration example. The comparison seeds were generated after the rules were fixed and were not used to tune thresholds. These results assess this implementation under these assumptions. A viewer pilot would measure the campaign's actual completion effects.

## Source fingerprints

- `scripts/compare_instruction_policies.py` has SHA-256 `428619ae706ce7c9318bc0ef994638293a64030566303a134765a60a8b7dd295`.
- `campaign_agent/instruction_policy.py` has SHA-256 `593989a8b2a3140e488c9d0c86600d871a952c6a84ff9cf807314865aeef8194`.
- `campaign_agent/instruction_tests.py` has SHA-256 `1383d9dfc4503021b3ce5f17c9dfe961d2702206d62eca14c047b54bffce7fcf`.
