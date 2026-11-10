import unittest

from campaign_agent.instruction_policy import POLICY_V1, recommend_instruction_action


def decision(original, revised, *, batch=None, cap=None, policy=POLICY_V1, unresolved=0, batch_checkpoint_id=None):
    snapshot = {
        "id": "authored-snapshot",
        "protocol": {"additional_batch_size": batch, "sample_cap": cap,
                     **({"decision_policy": policy} if policy else {})},
        "rows": [{"arm": arm, "cohorts": {"participant": {
            "mature_arrivals": arrivals, "completions": completed, "unresolved": pending,
        }}} for arm, (completed, arrivals), pending in (
            ("original", original, unresolved), ("revised", revised, 0),
        )],
    }
    return recommend_instruction_action(snapshot, batch_checkpoint_id=batch_checkpoint_id)


class InstructionPolicyTests(unittest.TestCase):
    def test_same_observed_lift_supports_different_actions_at_different_sample_sizes(self):
        small = decision((6, 20), (10, 20))
        large = decision((30, 100), (50, 100))
        self.assertEqual([(row["alpha"], row["beta"]) for row in small["arms"]], [(7, 15), (11, 11)])
        self.assertAlmostEqual(small["mean_lift"], 4 / 22)
        # Independent integration of the two posterior densities and their 5-point separation.
        self.assertAlmostEqual(small["probability_worthwhile"], 0.8210280449, places=8)
        self.assertAlmostEqual(large["probability_worthwhile"], 0.9843932047, places=8)
        self.assertEqual((small["action"], large["action"]), ("keep", "reuse"))
        self.assertEqual(small["batch_status"], "no_allowance")

    def test_batch_value_accounts_for_random_allocation_and_must_exceed_cost(self):
        # One visit has four equally likely arm/outcome pairs. In two of them
        # reuse has value 1/3, and in the other two keeping has value zero.
        policy = {**POLICY_V1, "minimum_lift": 0, "reuse_otherwise": -1, "batch_cost": 0.1}
        collect = decision((0, 0), (0, 0), batch=1, cap=1, policy=policy)
        self.assertAlmostEqual(collect["probability_worthwhile"], 0.5)
        self.assertAlmostEqual(collect["batch_gain"], 1 / 6)
        self.assertEqual(collect["action"], "collect")
        for cost in (1 / 6, 0.2):
            with self.subTest(cost=cost):
                result = decision((0, 0), (0, 0), batch=1, cap=1, policy={**policy, "batch_cost": cost})
                self.assertEqual(result["action"], "keep")

    def test_initial_review_point_defers_decision_even_when_all_visits_are_mature(self):
        for original, revised in (((0, 5), (5, 5)), ((19, 19), (0, 20))):
            with self.subTest(original=original, revised=revised):
                result = decision(original, revised, batch=10, cap=50)
                self.assertEqual((result["action"], result["batch_status"]),
                                 ("wait_for_evidence", "initial_sample_pending"))
                self.assertIsNone(result["batch_gain"])

    def test_unresolved_outcomes_defer_the_decision_without_a_batch_checkpoint(self):
        for original, revised, batch, cap, status, resolved_action in (
            ((6, 19), (10, 20), 10, 50, "initial_sample_pending", "collect"),
            ((2, 24), (20, 25), 10, 50, "no_batch_recommendation", "reuse"),
            ((6, 19), (10, 20), None, None, "no_allowance", "keep"),
        ):
            with self.subTest(status=status):
                pending = decision(original, revised, batch=batch, cap=cap, unresolved=1)
                self.assertEqual((pending["action"], pending["batch_status"]), ("wait_for_evidence", status))
                self.assertIsNone(pending["batch_gain"])
                completed, arrivals = original
                resolved = decision((completed, arrivals + 1), revised, batch=batch, cap=cap)
                self.assertEqual(resolved["action"], resolved_action)

    def test_pending_visits_reserve_space_and_the_cap_blocks_another_batch(self):
        for mature, unresolved, action, remaining in (
            (40, 1, "continue_batch", 9),
            (41, 0, "continue_batch", 9),
            (49, 1, "wait_batch", 0),
            (50, 1, "wait_batch", 0),
            (50, 0, "reuse", 0),
        ):
            with self.subTest(mature=mature, unresolved=unresolved):
                result = decision((6, mature - 20), (10, 20), batch=10, cap=50, unresolved=unresolved,
                                  batch_checkpoint_id="initial-collect-snapshot")
                self.assertEqual((result["action"], result["batch_remaining"]), (action, remaining))
                self.assertIsNone(result["batch_gain"])
