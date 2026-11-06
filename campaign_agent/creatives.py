"""Published, versioned examples and the media each one may serve."""

from dataclasses import dataclass

from .access import BrandScope, LOCAL_BRAND


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
