"""Catalog validation and local placement classification."""
import json
import re

from scripts.campaign_drafts import VIDEO_ID


TERMS = {
    "video-editing": ("video editing", "video editor", "voiceover timing", "video timeline", "davinci resolve", "premiere pro"),
    "audiobook": ("audiobook", "audiobooks", "audio book", "fiction narration", "character voices", "narrator direction"),
}


def read_catalog(path):
    """Read only independently supplied descriptions with an explicit source."""
    records = json.loads(path.read_text())
    if not isinstance(records, list) or not records:
        raise ValueError("The catalog must be a nonempty JSON array.")
    seen = set()
    for index, row in enumerate(records, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Catalog row {index} must be an object.")
        video_id = row.get("video_id", "")
        description = row.get("description", "")
        if (not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id)
                or row.get("source") not in ("creator_supplied", "licensed", "synthetic")
                or not isinstance(description, str) or not description.strip() or len(description) > 3000):
            raise ValueError(f"Invalid catalog row {index}. Use a video ID, permitted source and description (up to 3,000 characters).")
        if video_id in seen:
            raise ValueError(f"Duplicate video ID at catalog row {index}.")
        seen.add(video_id)
    return records


def rule_assignment(description):
    matches = [route for route, terms in TERMS.items()
               if any(re.search(r"\b" + re.escape(term) + r"\b", description.lower()) for term in terms)]
    return matches[0] if len(matches) == 1 else "review"
