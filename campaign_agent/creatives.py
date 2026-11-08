"""Published, versioned examples and the media each one may serve."""

from dataclasses import dataclass

from .access import BrandScope, LOCAL_BRAND


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


def render_instruction_choices(choices):
    if (not isinstance(choices, dict) or set(choices) != set(INSTRUCTION_COMPONENTS)
            or any(not isinstance(choices[key], str) or choices[key] not in options
                   for key, options in INSTRUCTION_COMPONENTS.items())):
        raise ValueError("Choose approved, neutral comparison instruction components.")
    return " ".join(options[choices[key]] for key, options in INSTRUCTION_COMPONENTS.items())


@dataclass(frozen=True)
class Example:
    ref: str
    creative_ref: str
    scope: BrandScope
    title: str
    instruction: str
    passage: str
    takes: tuple[tuple[str, str, str], ...]
    preview: str


EXAMPLES = (
    Example(
        "editing-comparison-v1", "editing-voiceover-v1", LOCAL_BRAND,
        "Find the voice that fits the cut",
        "Watch the same clip twice. Which read fits the moment the light comes on?",
        "One small light can change how you see the whole room.",
        (("a", "Quick and direct", "editing-a.mp4"), ("b", "Measured and deliberate", "editing-b.mp4")),
        "editing-a.mp4",
    ),
    Example(
        "audiobook-comparison-v1", "audiobook-reading-v1", LOCAL_BRAND,
        "Hear the scene two ways",
        "Listen to both readings. Which delivery fits the moment in the story?",
        "Mara stopped at the door. On the other side, someone was humming the song she had forgotten.",
        (("a", "Brisk reading", "audiobook-a.mp3"), ("b", "Measured reading", "audiobook-b.mp3")),
        "audiobook-preview.mp4",
    ),
)
