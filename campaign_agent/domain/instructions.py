"""Approved instruction components and their shared tool contract."""

# Provider proposals can combine these neutral clauses; arbitrary viewer prose is not accepted.
INSTRUCTION_COMPONENTS = {
    "playback": {
        "both_in_full": "Play both takes in full.",
        "take_order": "Play Take A and Take B all the way through.",
    },
    "focus": {
        "delivery": "Compare their delivery.",
        "pacing": "Compare how their pacing fits the scene.",
    },
    "choice": {
        "scene_fit": "Then choose the delivery that best fits the scene.",
        "moment_fit": "Then choose the take that fits this moment.",
    },
}


ASSESSMENT_REASONS = {
    "insufficient_visits": ("insufficient_evidence", "Insufficient evidence"),
    "continue_observation": ("keep_collecting", "Keep collecting evidence"),
    "revised_not_higher": ("prepare_another_test", "Consider another instruction test"),
}

INSTRUCTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {key: {"type": "string", "enum": list(options)}
                   for key, options in INSTRUCTION_COMPONENTS.items()},
    "required": list(INSTRUCTION_COMPONENTS),
}


def render_instruction_choices(choices):
    if (not isinstance(choices, dict) or set(choices) != set(INSTRUCTION_COMPONENTS)
            or any(not isinstance(choices[key], str) or choices[key] not in options
                   for key, options in INSTRUCTION_COMPONENTS.items())):
        raise ValueError("Choose approved, neutral comparison instruction components.")
    return " ".join(options[choices[key]] for key, options in INSTRUCTION_COMPONENTS.items())
