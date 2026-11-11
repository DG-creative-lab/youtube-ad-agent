#!/usr/bin/env python3
"""Reproducible, zero-provider comparison of instruction decision policies."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from random import Random
from statistics import mean, pstdev
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from campaign_agent.agent.run import AgentRuntime, DEMO_REQUEST
from campaign_agent.creatives import EXAMPLES
from campaign_agent.handoff import DEMO_MEDIA_DIR, package_fingerprint
from campaign_agent.instruction_policy import (
    ADDITIONAL_BATCH_SIZE, INITIAL_SAMPLE_SIZE, POLICY_V1, SAMPLE_CAP, recommend_instruction_action,
)
from campaign_agent.instruction_tests import (
    ASSESSMENT_VERSION, EVIDENCE_PROTOCOL, MIN_TEST_ARRIVALS, InstructionTests, recorded_assessment,
)

SPEC_PATH = ROOT / "examples/instruction-policy-comparison.json"
ARMS = ("original", "revised")
COHORTS = ("participant", "rehearsal", "fixture", "unknown")


def load_spec():
    spec = json.loads(SPEC_PATH.read_text())
    if (spec["bayesian_policy"] != POLICY_V1
            or (spec["initial_visits"], spec["batch_visits"], spec["sample_cap"]) !=
            (INITIAL_SAMPLE_SIZE, ADDITIONAL_BATCH_SIZE, SAMPLE_CAP)
            or spec["observation_window_ms"] != EVIDENCE_PROTOCOL["observation_window_ms"]
            or spec["assessment_version"] != ASSESSMENT_VERSION
            or spec["assessment_minimum_per_arm"] != MIN_TEST_ARRIVALS):
        raise ValueError("The application policy changed. Version and review the comparison specification before scoring.")
    return spec


def outcome_stream(spec, scenario, seed):
    """Potential visits shared across policies, including an optional second batch."""
    rng = Random(seed)
    visits = []
    count = scenario["initial_count"]
    total = spec["sample_cap"] if count == spec["initial_visits"] else count
    for index in range(total):
        arm_index = int(rng.random() >= 0.5)
        outcome = rng.random()
        batch = int(index >= spec["initial_visits"])
        arrival = (index * spec["arrival_interval_ms"] if not batch else
                   spec["batch_arrival_ms"] + (index - spec["initial_visits"]) * spec["arrival_interval_ms"])
        probability = scenario["probabilities"][arm_index]
        completed = None
        if outcome < probability:
            completed = arrival + scenario.get("completion_delay_ms", 2000)
        elif outcome < probability + scenario.get("late_probabilities", [0, 0])[arm_index]:
            completed = arrival + spec["observation_window_ms"] + 1000
        visits.append({
            "id": index, "arm": ARMS[arm_index], "source": "participant", "batch": batch,
            "admitted_ms": arrival,
            "arrived_ms": None if scenario.get("missing_first_arrival") and index == 0 else arrival,
            "completed_ms": completed,
        })
    if scenario.get("other_cohorts"):
        for source in COHORTS[1:]:
            for arm in ARMS:
                for _ in range(20):
                    visits.append({
                        "id": len(visits), "arm": arm, "source": source, "batch": 0,
                        "admitted_ms": 0, "arrived_ms": 0,
                        "completed_ms": 2000 if arm == "revised" else None,
                    })
    return visits


def evidence_at(spec, visits, cutoff, include_batch=False):
    """Project events committed by this cutoff into the application's two evidence views."""
    rows = [{"arm": arm, "cohorts": {
        source: {"mature_arrivals": 0, "completions": 0, "unresolved": 0} for source in COHORTS
    }} for arm in ARMS]
    native = [{"arm": arm, "arrivals": 0, "completions": 0} for arm in ARMS]
    for visit in visits:
        if visit["admitted_ms"] > cutoff or (visit["batch"] and not include_batch):
            continue
        index = ARMS.index(visit["arm"])
        arrival, completion = visit["arrived_ms"], visit["completed_ms"]
        completion = completion if completion is not None and completion <= cutoff else None
        if visit["source"] == "participant":
            native[index]["arrivals"] += 1
            native[index]["completions"] += int(completion is not None)
        counts = rows[index]["cohorts"][visit["source"]]
        if arrival is None or arrival + spec["observation_window_ms"] > cutoff:
            counts["unresolved"] += 1
        else:
            counts["mature_arrivals"] += 1
            counts["completions"] += int(completion is not None and completion <= arrival + spec["observation_window_ms"])
    snapshot = {
        "id": package_fingerprint({"rows": rows, "cutoff_ms": cutoff}), "rows": rows,
        "protocol": {**EVIDENCE_PROTOCOL, "decision_policy": spec["bayesian_policy"],
                     "additional_batch_size": spec["batch_visits"], "sample_cap": spec["sample_cap"]},
    }
    return snapshot, native


def fixed_action(spec, snapshot, collecting):
    counts = [row["cohorts"]["participant"] for row in snapshot["rows"]]
    mature = sum(row["mature_arrivals"] for row in counts)
    target = spec["sample_cap"] if collecting else spec["initial_visits"]
    if mature < target or any(row["unresolved"] or not row["mature_arrivals"] for row in counts):
        return "wait_for_evidence"
    lift = counts[1]["completions"] / counts[1]["mature_arrivals"] - counts[0]["completions"] / counts[0]["mature_arrivals"]
    lower, upper = spec["fixed_policy"]["collect_band"]
    if not collecting and lower - 1e-12 <= lift <= upper + 1e-12:
        return "collect"
    return "reuse" if lift > spec["fixed_policy"]["reuse_lift"] + 1e-12 else "keep"


def replay(spec, visits, policy):
    collecting = False
    checkpoint = None
    trace = []
    for cutoff in spec["cutoffs_ms"]:
        snapshot, _ = evidence_at(spec, visits, cutoff, include_batch=collecting)
        if policy == "bayesian":
            decision = recommend_instruction_action(snapshot, batch_checkpoint_id=checkpoint)
            action = decision["action"]
        else:
            action = fixed_action(spec, snapshot, collecting)
        counts = [row["cohorts"]["participant"] for row in snapshot["rows"]]
        trace.append({"cutoff_ms": cutoff, "action": action, "counts": counts})
        if action in ("reuse", "keep"):
            break
        if action == "collect":
            if collecting:
                raise ValueError("A policy requested a second extra batch.")
            collecting = True
            checkpoint = snapshot["id"]
    extra = sum(visit["source"] == "participant" and visit["batch"] == 1
                and visit["admitted_ms"] <= trace[-1]["cutoff_ms"] for visit in visits) if collecting else 0
    return {"action": trace[-1]["action"], "collected_batch": collecting, "extra_visits": extra, "trace": trace}


def score(spec, scenario, result):
    worthwhile = scenario["probabilities"][1] - scenario["probabilities"][0] > spec["bayesian_policy"]["minimum_lift"] + 1e-12
    action = result["action"]
    value = 0
    if action in ("reuse", "keep"):
        suffix = "if_worthwhile" if worthwhile else "otherwise"
        value = spec["bayesian_policy"][f"{action}_{suffix}"]
    cost = spec["bayesian_policy"]["batch_cost"] if result["collected_batch"] else 0
    return {**result, "mistaken_reuse": action == "reuse" and not worthwhile,
            "worthwhile_not_reused": worthwhile and action != "reuse", "net_value": value - cost}


def native_trace(spec, visits):
    trace = []
    for cutoff in spec["cutoffs_ms"]:
        _, rows = evidence_at(spec, visits, cutoff, include_batch=True)
        context = {"rows": rows, "minimum_per_version": MIN_TEST_ARRIVALS, "correction": {"kind": "keep_takes"}}
        assessment = InstructionTests.validate_assessment(context, recorded_assessment(context))
        trace.append({"cutoff_ms": cutoff, "kind": assessment["kind"], "reason_code": assessment["reason_code"],
                      "rows": rows})
    return trace


def compare(spec):
    runs = []
    for scenario in spec["scenarios"]:
        for seed in range(spec["seed_start"], spec["seed_start"] + spec["repetitions"]):
            visits = outcome_stream(spec, scenario, seed)
            policies = {name: score(spec, scenario, replay(spec, visits, name)) for name in ("bayesian", "fixed")}
            difference = policies["bayesian"]["net_value"] - policies["fixed"]["net_value"]
            winner = "tie" if abs(difference) <= 1e-12 else ("bayesian" if difference > 0 else "fixed")
            runs.append({"scenario": scenario["id"], "seed": seed, "stream_sha256": package_fingerprint(visits),
                         "winner": winner, **policies, "native": native_trace(spec, visits)})
    sources = ("scripts/compare_instruction_policies.py", "campaign_agent/instruction_policy.py",
               "campaign_agent/instruction_tests.py")
    return {"specification": spec, "specification_sha256": package_fingerprint(spec),
            "source_sha256": {source: sha256((ROOT / source).read_bytes()).hexdigest() for source in sources},
            "assessment_version": ASSESSMENT_VERSION, "runs": runs}


def walkthrough(path):
    """Use the real application commands with authored eligible participant outcomes."""
    if path.exists():
        raise ValueError("Choose a new walkthrough database so existing state is preserved.")
    runtime = AgentRuntime(path, media_dir=DEMO_MEDIA_DIR)
    drafts, viewer = runtime.drafts, runtime.performance.viewer
    runtime.resume(runtime.start(DEMO_REQUEST))
    campaign = drafts.campaign_id
    baseline = drafts.review_package(campaign, 2)["fingerprint"]
    original = drafts.approve_package(campaign, 2, baseline)["package"]
    content = package_fingerprint(original["groups"][0]["content"])
    for _ in range(3):
        viewer.open_example(EXAMPLES[0].creative_ref, content_fingerprint=content)
    review = runtime.performance.review(campaign, 2, baseline, "balanced")
    runtime.performance.save_correction(
        campaign, 2, baseline, review["id"], "keep_takes", "Keep both recordings.", uuid4().hex,
    )
    review = runtime.performance.review(campaign, 2, baseline, "balanced")
    runtime.resume(runtime.start_next_test(campaign, 2, baseline, review["id"]))
    fingerprint = drafts.review_package(campaign, 3)["fingerprint"]
    drafts.approve_package(campaign, 3, fingerprint)
    test = runtime.instruction_tests.start(campaign, 3, fingerprint, allow_additional_batch=True)
    arrival = 1_700_000_000_000
    with patch("campaign_agent.measurement.time_ns", return_value=arrival * 1_000_000):
        for arm, completions in (("original", 2), ("revised", 18)):
            with patch("campaign_agent.instruction_tests.secrets.choice", return_value=arm):
                for index in range(20):
                    visit = runtime.instruction_tests.open(test["id"], uuid4().hex)
                    if index < completions:
                        refs = (visit["creative_ref"], visit["visit_id"], visit["example"]["ref"])
                        for take in ("a", "b"):
                            viewer.record(*refs, uuid4().hex, "start", take)
                            viewer.record(*refs, uuid4().hex, "finish", take)
                        viewer.record(*refs, uuid4().hex, "choose", "a")
    with patch("campaign_agent.instruction_tests.time_ns", return_value=(arrival + 300000) * 1_000_000):
        snapshot = runtime.instruction_tests.save_evidence_snapshot(campaign, 3, fingerprint, uuid4().hex)
    finding = runtime.instruction_findings.save(campaign, 3, fingerprint, snapshot_id=snapshot["id"])
    fresh = drafts.start_brief(campaign, 3, fingerprint, title="Offline comparison walkthrough",
                               goal="Review tested editing instructions on a fresh brief.", context="video-editing")
    target = (campaign, fresh["revision"], drafts.review_package(campaign, fresh["revision"])["fingerprint"])
    reopened = AgentRuntime(path, media_dir=DEMO_MEDIA_DIR)
    eligible = reopened.instruction_findings.read(*target)
    if eligible is None or eligible["finding"] != finding:
        raise ValueError("The finding did not survive restart.")
    saved = reopened.instruction_findings.apply(
        *target, finding_id=finding["id"], correction_id=eligible["correction"]["id"], draft_permission="instruction_test",
    )
    package = reopened.drafts.review_package(campaign, saved["revision"])
    if (package["approval"] is not None or package["package"]["groups"][0]["content"]["instruction"] != finding["after"]):
        raise ValueError("The walkthrough did not produce the expected unapproved wording draft.")
    return {"source_counts": [[2, 20], [18, 20]], "action": finding["decision"]["action"],
            "probability_worthwhile": finding["decision"]["probability_worthwhile"],
            "fresh_brief_revision": fresh["revision"], "draft_revision": saved["revision"],
            "finding_survived_restart": True, "package_requires_approval": True}


def summary(results):
    values = [result["net_value"] for result in results]
    return {
        "reuse": sum(result["action"] == "reuse" for result in results),
        "keep": sum(result["action"] == "keep" for result in results),
        "wait": sum(result["action"] not in ("reuse", "keep") for result in results),
        "mistaken_reuse": sum(result["mistaken_reuse"] for result in results),
        "worthwhile_not_reused": sum(result["worthwhile_not_reused"] for result in results),
        "batches": sum(result["collected_batch"] for result in results),
        "extra_visits": sum(result["extra_visits"] for result in results),
        "mean_value": mean(values), "value_sd": pstdev(values),
        "wait_reviews": sum(step["action"] in ("wait_for_evidence", "wait_batch", "continue_batch")
                            for result in results for step in result["trace"]),
    }


def markdown(report):
    spec, runs = report["specification"], report["runs"]
    lines = [
        "# Offline instruction policy comparison", "",
        f"Specification `{spec['version']}` · SHA-256 `{report['specification_sha256']}`", "",
        "Reproduce from the repository root with `python3 -B scripts/compare_instruction_policies.py "
        "--output docs/instruction-policy-comparison.md`. Add `--json /tmp/instruction-policy-comparison.json` "
        "to retain every seed, cutoff, count and action.", "",
        "## Frozen rules and scoring", "",
        f"Each scenario uses {spec['repetitions']} held-out simulation seeds, "
        f"{spec['seed_start']}–{spec['seed_start'] + spec['repetitions'] - 1}. Two independent random draws per visit "
        "select its arm with equal probability and its outcome. All policies receive the same potential event stream "
        "and review cutoffs. Original and revised within-window completion probabilities remain constant within each scenario.", "",
        "The Bayesian policy uses the application's pinned Beta(1, 1) prior, five-percentage-point target, "
        "+1/−9 reuse payoffs, zero keep payoff and 0.01-unit cost per requested extra batch. "
        "Its review point is 40 resolved visits, with one optional batch of 10 and a cap of 50.", "",
        "The fixed-lift policy waits for 40 resolved visits, collects 10 when observed lift is between "
        "0 and 10 percentage points inclusive, and otherwise reuses above five points or keeps. "
        "After the extra batch it reuses above five points or keeps. Both policies wait for unresolved outcomes.", "",
        "Net decision value uses the known within-window fixture effect. Reuse earns +1 when that effect exceeds "
        "five points and −9 otherwise. Keeping and waiting at the final cutoff earn zero. Each requested batch costs "
        "0.01 once. Waiting has no time penalty. Worthwhile effects left unreused include unresolved final waits.", "",
        "## Aggregate results", "",
        "| Policy | Reuse | Keep | Final wait | Mistaken reuse | Worthwhile unreused | Extra batches | Extra visits | Waiting reviews | Mean value | Value SD |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ("bayesian", "fixed"):
        row = summary([run[name] for run in runs])
        lines.append(f"| {name} | {row['reuse']} | {row['keep']} | {row['wait']} | {row['mistaken_reuse']} | "
                     f"{row['worthwhile_not_reused']} | {row['batches']} | {row['extra_visits']} | "
                     f"{row['wait_reviews']} | {row['mean_value']:.4f} | {row['value_sd']:.4f} |")
    lines += ["", "Keeping without collection earns zero in this scoring system. "
              "Both policy means should be compared with that reference. The SD describes variation across this "
              "coverage suite, whose scenarios include different effects and evidence availability.", ""]
    wins = Counter(run["winner"] for run in runs)
    lines += ["", f"Paired net-value comparisons across {len(runs)} runs give {wins['bayesian']} Bayesian wins, "
              f"{wins['fixed']} fixed-lift wins and {wins['tie']} ties.", "",
              "## Results by scenario", "",
              "| Scenario | True rates, original / revised | Bayesian mean value | Fixed mean value | Bayesian / fixed / tie |",
              "| --- | --- | ---: | ---: | --- |"]
    for scenario in spec["scenarios"]:
        selected = [run for run in runs if run["scenario"] == scenario["id"]]
        tally = Counter(run["winner"] for run in selected)
        rates = " / ".join(f"{rate:.0%}" for rate in scenario["probabilities"])
        lines.append(f"| {scenario['id']} | {rates} | {mean(run['bayesian']['net_value'] for run in selected):.4f} | "
                     f"{mean(run['fixed']['net_value'] for run in selected):.4f} | "
                     f"{tally['bayesian']} / {tally['fixed']} / {tally['tie']} |")
    lines += ["", "## Paired examples", "",
              "Examples are the first three runs for each winner in specification and seed order.", "",
              "| Winner | Scenario | Seed | Bayesian action / value | Fixed action / value |",
              "| --- | --- | ---: | --- | --- |"]
    for winner in ("bayesian", "fixed", "tie"):
        for run in [run for run in runs if run["winner"] == winner][:3]:
            lines.append(f"| {winner} | {run['scenario']} | {run['seed']} | "
                         f"{run['bayesian']['action']} / {run['bayesian']['net_value']:.2f} | "
                         f"{run['fixed']['action']} / {run['fixed']['net_value']:.2f} |")
    lines += ["", "## Existing assessment", "",
              f"The existing `{report['assessment_version']}` assessment runs through its real recorded-assessment "
              "and validation functions. It sees assigned participant visits and completions recorded by each cutoff, "
              "including completions after the Bayesian observation window. Its 20-visits-per-arm minimum remains intact.", "",
              "Its native actions appear below at 340000 ms and at the final 650000 ms cutoff. "
              "The latter exposes the potential extra batch for a common full-budget observation. "
              "That exposure is supplied by the evaluator. The assessment specifies neither a batch size nor "
              "a reuse/keep terminal choice, so acquisition cost and comparable net utility are left unscored.", "",
              "| Native action | Initial review | Full-budget review |",
              "| --- | ---: | ---: |"]
    initial = Counter(next(step["kind"] for step in run["native"] if step["cutoff_ms"] == spec["initial_review_ms"]) for run in runs)
    final = Counter(run["native"][-1]["kind"] for run in runs)
    for action in sorted(initial.keys() | final.keys()):
        lines.append(f"| {action} | {initial[action]} | {final[action]} |")
    lines += ["", "Native counts below use the order insufficient evidence / keep collecting / prepare another test.", "",
              "| Scenario | Initial review | Full-budget review |", "| --- | --- | --- |"]
    native_kinds = ("insufficient_evidence", "keep_collecting", "prepare_another_test")
    for scenario in spec["scenarios"]:
        selected = [run for run in runs if run["scenario"] == scenario["id"]]
        start = Counter(next(step["kind"] for step in run["native"]
                             if step["cutoff_ms"] == spec["initial_review_ms"]) for run in selected)
        end = Counter(run["native"][-1]["kind"] for run in selected)
        lines.append(f"| {scenario['id']} | {' / '.join(str(start[kind]) for kind in native_kinds)} | "
                     f"{' / '.join(str(end[kind]) for kind in native_kinds)} |")
    walk = report["walkthrough"]
    lines += ["", "## Fresh-brief walkthrough", "",
              "The separate integration example uses authored participant outcomes of 2/20 versus 18/20. "
              f"The application returned `{walk['action']}` with probability "
              f"{walk['probability_worthwhile']:.6%} of exceeding the target. Its real commands saved a finding, "
              f"started fresh brief revision {walk['fresh_brief_revision']}, reopened SQLite and prepared wording draft "
              f"revision {walk['draft_revision']}. The finding survived restart and the package requires buyer approval.", "",
              "To inspect it in the planner, run the comparison with `--walkthrough-db /tmp/policy-walkthrough.sqlite3` "
              "using a new path, then serve that database with the portable demo.", "",
              "## Assumptions and limits", "",
              "All outcomes are authored simulations and all execution is offline with zero provider calls. "
              "The scenario mixture is a coverage suite and has no estimated frequency in real campaigns. "
              "Aggregate averages weight its scenarios equally. The observed ranking depends on the declared "
              "payoffs, collection band, sample budget and fixture probabilities.", "",
              "Sparse has ten initial visits and absent has none. Missing-time removes the first arrival timestamp. "
              "Delayed records successes at 295 seconds, within the five-minute window. Late-conflict adds "
              "late completions to 40% of revised visits while both arms retain the same 30% within-window success probability. "
              "Cohort-conflict adds 20 visits per arm for each of rehearsal, fixture and unknown sources, "
              "with every revised nonparticipant visit completing. Those cohorts remain outside all decision denominators.", "",
              "The walkthrough is a separate deterministic integration example. The comparison seeds were generated "
              "after the rules were fixed and were not used to tune thresholds. "
              "These results assess this implementation under these assumptions. A viewer pilot would measure "
              "the campaign's actual completion effects.", "",
              "## Source fingerprints", ""]
    lines.extend(f"- `{source}` has SHA-256 `{digest}`." for source, digest in report["source_sha256"].items())
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write the reproducible Markdown report.")
    parser.add_argument("--json", type=Path, help="Write every event-stream hash, evidence cutoff and action.")
    parser.add_argument("--walkthrough-db", type=Path, help="Keep the application walkthrough in a new SQLite database.")
    args = parser.parse_args()
    if args.walkthrough_db and args.walkthrough_db.exists():
        parser.error("Choose a new walkthrough database so existing state is preserved.")
    report = compare(load_spec())
    if args.walkthrough_db:
        report["walkthrough"] = walkthrough(args.walkthrough_db)
    else:
        with TemporaryDirectory() as directory:
            report["walkthrough"] = walkthrough(Path(directory) / "walkthrough.sqlite3")
    rendered = markdown(report)
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
