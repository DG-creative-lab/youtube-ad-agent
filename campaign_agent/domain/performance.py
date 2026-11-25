"""Pure thresholds and buyer-correction policy for saved reviews."""

MIN_LOCAL_ARRIVALS = 3
LOW_COMPLETION_RATE = 0.5


def apply_correction(proposal, correction):
    if correction["kind"] == "keep_takes":
        changes = {
            "title": "Test clearer comparison instructions",
            "change": "Compare revised instructions with the current wording in a local test.",
            "hold_constant": "Keep the ad, both takes and the choice controls the same.",
        }
    else:
        changes = {
            "title": "Test how the ad sets up the comparison",
            "change": "Compare a clearer invitation to try both takes with the current ad invitation.",
            "hold_constant": "Keep the placements, takes and viewer experience the same.",
        }
    return {**proposal, **changes, "correction": correction}
