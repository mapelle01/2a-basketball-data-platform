"""Review policy — decides whether a validated content item auto-publishes or
needs a human to look at it first.

Deterministic and conservative: while the engine is young (sandbox season),
high-impact or narrative pieces route to MANUAL_REVIEW so a person signs off
before anything reaches SCHEDULED/PUBLISHED. Routine pieces (a plain match
result) can flow automatically.

The thresholds live here so the review posture is one obvious knob, tightened
or relaxed per season without touching the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from .story import StoryObject, StoryType


# Story types that always warrant a human glance (editorial / high-visibility).
_ALWAYS_REVIEW = {
    StoryType.TRIPLE_DOUBLE,
    StoryType.SEASON_HIGH,
    StoryType.MILESTONE,
    StoryType.UPSET,
    StoryType.COMEBACK,
    StoryType.ROUND_RECAP,      # the round's flagship piece
    StoryType.PLAYER_OF_ROUND,  # names a single player as THE story
}

# Above this planner priority, review regardless of type.
REVIEW_PRIORITY_THRESHOLD = 80


@dataclass(frozen=True)
class ReviewDecision:
    requires_review: bool
    reason: str


def decide_review(story: StoryObject) -> ReviewDecision:
    if story.story_type in _ALWAYS_REVIEW:
        return ReviewDecision(True, f"{story.story_type.value} always reviewed")
    if story.priority >= REVIEW_PRIORITY_THRESHOLD:
        return ReviewDecision(
            True, f"priority {story.priority} >= {REVIEW_PRIORITY_THRESHOLD}"
        )
    return ReviewDecision(False, "routine content, auto-approved")
