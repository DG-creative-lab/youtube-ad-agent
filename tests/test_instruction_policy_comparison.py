from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.compare_instruction_policies import (
    compare, evidence_at, load_spec, outcome_stream, replay, score, walkthrough,
)


class InstructionPolicyComparisonTests(unittest.TestCase):
    def setUp(self):
        self.spec = load_spec()

    def test_projection_preserves_cutoff_maturity_late_outcomes_and_cohorts(self):
        visits = [
            {"id": 0, "arm": "original", "source": "participant", "batch": 0,
             "admitted_ms": 0, "arrived_ms": 0, "completed_ms": 2000},
            {"id": 1, "arm": "revised", "source": "participant", "batch": 0,
             "admitted_ms": 0, "arrived_ms": 0, "completed_ms": 301000},
            {"id": 2, "arm": "revised", "source": "rehearsal", "batch": 0,
             "admitted_ms": 0, "arrived_ms": 0, "completed_ms": 2000},
            {"id": 3, "arm": "original", "source": "participant", "batch": 1,
             "admitted_ms": 341000, "arrived_ms": None, "completed_ms": None},
        ]
        early, native = evidence_at(self.spec, visits, 2000)
        self.assertEqual(early["rows"][0]["cohorts"]["participant"],
                         {"mature_arrivals": 0, "completions": 0, "unresolved": 1})
        self.assertEqual(native[0]["completions"], 1)
        final, native = evidence_at(self.spec, visits, 650000)
        self.assertEqual(final["rows"][1]["cohorts"]["participant"],
                         {"mature_arrivals": 1, "completions": 0, "unresolved": 0})
        self.assertEqual(native[1], {"arm": "revised", "arrivals": 1, "completions": 1})
        included, _ = evidence_at(self.spec, visits, 650000, include_batch=True)
        self.assertEqual(included["rows"][0]["cohorts"]["participant"]["unresolved"], 1)
        self.assertEqual(included["rows"][1]["cohorts"]["rehearsal"]["completions"], 1)

    def test_nonparticipant_conflict_does_not_change_policy_decisions(self):
        original = next(row for row in self.spec["scenarios"] if row["id"] == "no-effect")
        conflict = next(row for row in self.spec["scenarios"] if row["id"] == "cohort-conflict")
        clean = outcome_stream(self.spec, original, 41002)
        contaminated = outcome_stream(self.spec, conflict, 41002)
        for policy in ("bayesian", "fixed"):
            self.assertEqual(replay(self.spec, clean, policy), replay(self.spec, contaminated, policy))

    def test_future_batch_outcomes_do_not_change_initial_collection_decision_or_charge_twice(self):
        visits = []
        for index in range(50):
            arm = "original" if index % 2 == 0 else "revised"
            batch = int(index >= 40)
            arrival = index * 1000 if not batch else 341000 + (index - 40) * 1000
            completed = index // 2 < (6 if arm == "original" else 10)
            visits.append({"id": index, "arm": arm, "source": "participant", "batch": batch,
                           "admitted_ms": arrival, "arrived_ms": arrival,
                           "completed_ms": arrival + 2000 if completed else None})
        changed = deepcopy(visits)
        for visit in changed[40:]:
            visit["completed_ms"] = visit["arrived_ms"] + 2000
        first = replay(self.spec, visits, "bayesian")
        second = replay(self.spec, changed, "bayesian")
        self.assertEqual(first["trace"][:4], second["trace"][:4])
        self.assertEqual(first["trace"][3]["action"], "collect")
        for result in (first, second):
            self.assertEqual(sum(step["action"] == "collect" for step in result["trace"]), 1)
            self.assertEqual(result["extra_visits"], 10)
            self.assertLessEqual(sum(count["mature_arrivals"] + count["unresolved"]
                                     for count in result["trace"][-1]["counts"]), 50)
        scenario = {"probabilities": [0.3, 0.5]}
        valued = score(self.spec, scenario, {**first, "action": "keep"})
        self.assertEqual(valued["net_value"], -0.01)

    def test_known_truth_scores_wrong_reuse_and_cheaper_baseline_wins(self):
        reused = {"action": "reuse", "collected_batch": False}
        benefit = {"probabilities": [0.3, 0.5]}
        fixed = score(self.spec, benefit, reused)
        collected = score(self.spec, benefit, {**reused, "collected_batch": True})
        self.assertEqual((fixed["net_value"], collected["net_value"]), (1, 0.99))
        harmful = score(self.spec, {"probabilities": [0.5, 0.3]}, reused)
        self.assertTrue(harmful["mistaken_reuse"])
        self.assertEqual(harmful["net_value"], -9)
        waited = score(self.spec, benefit, {"action": "wait_for_evidence", "collected_batch": False})
        self.assertTrue(waited["worthwhile_not_reused"])
        self.assertEqual(waited["net_value"], 0)

    def test_comparison_is_reproducible_and_keeps_native_actions(self):
        spec = deepcopy(self.spec)
        spec["repetitions"] = 1
        first = compare(spec)
        self.assertEqual(first, compare(spec))
        native = {step["kind"] for run in first["runs"] for step in run["native"]}
        self.assertLessEqual(native, {"insufficient_evidence", "keep_collecting", "prepare_another_test"})
        self.assertNotIn("reuse", native)
        sparse = next(row for row in first["runs"] if row["scenario"] == "sparse")
        self.assertEqual(sparse["winner"], "tie")
        self.assertEqual((sparse["bayesian"]["action"], sparse["fixed"]["action"]),
                         ("wait_for_evidence", "wait_for_evidence"))

    def test_walkthrough_uses_application_persistence_and_preserves_existing_database(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "walkthrough.sqlite3"
            result = walkthrough(path)
            self.assertEqual(result["source_counts"], [[2, 20], [18, 20]])
            self.assertTrue(result["finding_survived_restart"])
            self.assertTrue(result["package_requires_approval"])
            with self.assertRaisesRegex(ValueError, "existing state"):
                walkthrough(path)
