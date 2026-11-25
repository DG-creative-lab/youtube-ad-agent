"""Published, versioned examples and the media each one may serve."""

from dataclasses import dataclass

from campaign_agent.domain.scope import BrandScope
from campaign_agent.domain.instructions import INSTRUCTION_COMPONENTS, render_instruction_choices
from .access import LOCAL_BRAND


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
        "Watch the same scene twice. Which read makes the room feel like home?",
        "The room hadn't changed. But with one small light, it felt like home.",
        (("a", "Quick and direct", "editing-a.mp4"), ("b", "Measured and deliberate", "editing-b.mp4")),
        "editing-a.mp4",
    ),
    Example(
        "audiobook-comparison-v1", "audiobook-reading-v1", LOCAL_BRAND,
        "Hear the scene two ways",
        "Listen to both readings. Which delivery fits the moment in the story?",
        "Only Mara knew that lullaby. Now someone behind the locked door was singing it back.",
        (("a", "Brisk reading", "audiobook-a.mp3"), ("b", "Measured reading", "audiobook-b.mp3")),
        "audiobook-preview.mp4",
    ),
)
