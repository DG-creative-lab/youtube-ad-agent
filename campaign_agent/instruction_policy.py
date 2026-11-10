"""Offline decision policy for saved instruction-test evidence."""

from functools import cache, lru_cache
from math import comb, cos, fsum, pi, prod


POLICY_V1 = {
    "version": "instruction-beta-v1",
    "prior_alpha": 1,
    "prior_beta": 1,
    "minimum_lift": 0.05,
    "reuse_if_worthwhile": 1.0,
    "reuse_otherwise": -9.0,
    "keep_if_worthwhile": 0.0,
    "keep_otherwise": 0.0,
    "batch_cost": 0.01,
}
INITIAL_SAMPLE_SIZE = 40
ADDITIONAL_BATCH_SIZE = 10
SAMPLE_CAP = INITIAL_SAMPLE_SIZE + ADDITIONAL_BATCH_SIZE
# Bound the polynomial calculation, including for older tests without a batch allowance.
MAX_MODEL_VISITS = 400
DECISION_TOLERANCE = 1e-10


def _legendre_value(order, x):
    previous, value = 0.0, 1.0
    for degree in range(1, order + 1):
        previous, value = value, ((2 * degree - 1) * x * value - (degree - 1) * previous) / degree
    return value, order * (previous - x * value) / (1 - x * x)


@lru_cache(maxsize=32)
def _gauss_legendre(order):
    nodes = []
    for index in range(1, order + 1):
        x = cos(pi * (index - 0.25) / (order + 0.5))
        for _ in range(20):
            value, slope = _legendre_value(order, x)
            step = value / slope
            x -= step
            if abs(step) < 1e-15:
                break
        _, slope = _legendre_value(order, x)
        nodes.append((x, 2 / ((1 - x * x) * slope * slope)))
    return tuple(nodes)


def _lift_probability(total_visits, minimum_lift):
    # Integrate the original beta density times the revised survival function
    # at x + minimum_lift. With integer shapes both factors are polynomials.
    # NIST DLMF 8.17.5 and 3.5(v) give the binomial sum and quadrature rule.
    scale = (1 - minimum_lift) / 2
    grid = [(scale * (x + 1), scale * weight)
            for x, weight in _gauss_legendre((total_visits + 3) // 2)]

    @cache
    def original_density(alpha, beta):
        trials = alpha + beta - 1
        factor = trials * comb(trials - 1, alpha - 1)
        return [weight * factor * x**(alpha - 1) * (1 - x)**(beta - 1) for x, weight in grid]

    @cache
    def revised_survival(alpha, beta):
        trials = alpha + beta - 1
        terms = [(comb(trials, k), k, trials - k) for k in range(alpha)]
        return [fsum(coefficient * p**success * (1 - p)**failure for coefficient, success, failure in terms)
                for p in (x + minimum_lift for x, _ in grid)]

    def probability(original, revised):
        value = fsum(a * b for a, b in zip(original_density(*original), revised_survival(*revised), strict=True))
        return min(1.0, max(0.0, value))

    return probability


def _predictive(alpha, beta, visits):
    """Beta-binomial completion counts for a given arm allocation."""
    denominator = prod(range(alpha + beta, alpha + beta + visits))
    for completed in range(visits + 1):
        failures = visits - completed
        numerator = comb(visits, completed) * prod(range(alpha, alpha + completed)) * prod(range(beta, beta + failures))
        yield (alpha + completed, beta + failures), numerator / denominator


def _action_values(probability, policy):
    return {action: probability * policy[f"{action}_if_worthwhile"] + (1 - probability) * policy[f"{action}_otherwise"]
            for action in ("keep", "reuse")}


def _value_after_batch(original, revised, size, probability, policy):
    # Match the experiment's independent 50/50 assignment of each new visit.
    return fsum(
        comb(size, original_visits) / 2**size * weight_a * weight_b
        * max(_action_values(probability(future_a, future_b), policy).values())
        for original_visits in range(size + 1)
        for future_a, weight_a in _predictive(*original, original_visits)
        for future_b, weight_b in _predictive(*revised, size - original_visits)
    )


def recommend_instruction_action(snapshot, *, batch_checkpoint_id=None):
    """Recompute from the pinned prior and cumulative participant counts."""
    protocol = snapshot["protocol"]
    policy = protocol.get("decision_policy")
    if policy is None:
        return {"snapshot_id": snapshot["id"], "action": "unavailable", "reason": "unpinned_policy"}
    arms = []
    for row in snapshot["rows"]:
        counts = row["cohorts"]["participant"]
        arrivals, completions = counts["mature_arrivals"], counts["completions"]
        alpha = policy["prior_alpha"] + completions
        beta = policy["prior_beta"] + arrivals - completions
        arms.append({"arm": row["arm"], **counts, "alpha": alpha, "beta": beta, "mean": alpha / (alpha + beta)})

    mature = sum(arm["mature_arrivals"] for arm in arms)
    unresolved = sum(arm["unresolved"] for arm in arms)
    assigned = mature + unresolved
    size = protocol["additional_batch_size"]
    cap = protocol.get("sample_cap")
    remaining = max(0, cap - assigned) if size is not None else None
    decision = {"snapshot_id": snapshot["id"], "policy": policy, "arms": arms, "assigned": assigned,
                "batch_size": size, "sample_cap": cap, "batch_checkpoint_id": batch_checkpoint_id}
    if mature > MAX_MODEL_VISITS:
        return {**decision, "action": "unavailable", "reason": "model_visit_limit", "model_visit_limit": MAX_MODEL_VISITS}

    if size is None:
        batch_status = "no_allowance"
    elif assigned > cap - size:
        if not batch_checkpoint_id:
            batch_status = "no_batch_recommendation"
        elif remaining or unresolved:
            batch_status = "in_progress"
        else:
            batch_status = "sample_cap"
    elif assigned < cap - size or unresolved:
        batch_status = "initial_sample_pending"
    else:
        batch_status = "evaluated"
    probability = _lift_probability(mature + (size if batch_status == "evaluated" else 0), policy["minimum_lift"])
    original, revised = ((arm["alpha"], arm["beta"]) for arm in arms)
    worthwhile = probability(original, revised)
    values = _action_values(worthwhile, policy)
    action = "reuse" if values["reuse"] > values["keep"] + DECISION_TOLERANCE else "keep"
    gain = None
    if batch_status == "in_progress":
        action = "continue_batch" if remaining else "wait_batch"
    elif unresolved or batch_status == "initial_sample_pending":
        action = "wait_for_evidence"
    elif batch_status == "evaluated":
        gain = max(0.0, _value_after_batch(original, revised, size, probability, policy) - max(values.values()))
        if gain > policy["batch_cost"] + DECISION_TOLERANCE:
            action = "collect"
    return {**decision, "action": action, "batch_status": batch_status, "batch_gain": gain,
            "batch_remaining": remaining if batch_checkpoint_id or action == "collect" else None,
            "mean_lift": arms[1]["mean"] - arms[0]["mean"], "probability_worthwhile": worthwhile,
            "action_values": values}
