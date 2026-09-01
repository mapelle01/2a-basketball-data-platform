"""Content Planner — deterministic scoring + selection of stories.

Not every detected story deserves a post. The planner computes a content
score from five dimensions and selects the top-N per round. No ML in v1;
a plain weighted sum is transparent and easy to tune.

Scoring dimensions (0..100 each):
  - importance         → intrinsic weight of the story type
  - novelty            → is this a first / new / rare event?
  - statistical_strength → how large are the numbers?
  - visual_strength    → does this story render well? (photo? big number?)
  - editorial_strength → is there a narrative?

Final content_score = weighted average, in 0..100.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set

from .story import StoryObject, StoryStatus, StoryType


# ---------------------------------------------------------------------------
# Type importance — the baseline "how much does this story type matter?"
# ---------------------------------------------------------------------------
TYPE_IMPORTANCE = {
    StoryType.ROUND_RECAP: 90,
    StoryType.STAT_LEADERBOARD: 80,
    StoryType.PLAYER_OF_ROUND: 88,
    StoryType.TEAM_OF_ROUND: 82,
    StoryType.TRIPLE_DOUBLE: 95,
    StoryType.SEASON_HIGH: 85,
    StoryType.BEST_PERFORMANCE: 78,
    StoryType.BIGGEST_WIN: 78,
    StoryType.CLOSEST_GAME: 72,
    StoryType.UPSET: 82,
    StoryType.COMEBACK: 80,
    StoryType.WIN_STREAK: 70,
    StoryType.LOSS_STREAK: 55,
    StoryType.TOP_SCORER: 70,
    StoryType.TOP_REBOUNDER: 60,
    StoryType.TOP_ASSIST_PROVIDER: 60,
    StoryType.DOUBLE_DOUBLE: 55,
    StoryType.MATCH_FINAL: 50,
    StoryType.POSITION_CHANGE: 60,
    StoryType.LEADERBOARD_CHANGE: 55,
    StoryType.MILESTONE: 80,
    StoryType.DID_YOU_KNOW: 45,
    StoryType.IRON_MAN: 58,
    StoryType.SHARPSHOOTER: 74,
    StoryType.PERFECT_NIGHT: 80,
    StoryType.PLAYMAKER: 60,
    StoryType.DEFENSIVE_ANCHOR: 72,
    StoryType.LONE_FLAG: 76,
    StoryType.YOUNG_GUN: 74,
    StoryType.VETERAN: 70,
    StoryType.BEST_FIVE: 80,
    StoryType.BEST_FIVE_IDEAL: 82,
    StoryType.BEST_DUO: 72,
    # A live streak beats an isolated 20+ game — it says a whole arc, not just
    # a night. Priority also scales with length inside the detector's facts.
    StoryType.PLAYER_STREAK_SCORING: 84,
    StoryType.PLAYER_STREAK_DD: 86,
}


WEIGHTS = {
    "importance": 0.30,
    "novelty": 0.15,
    "statistical_strength": 0.20,
    "visual_strength": 0.15,
    "editorial_strength": 0.20,
}


@dataclass(frozen=True)
class ScoreBreakdown:
    importance: int
    novelty: int
    statistical_strength: int
    visual_strength: int
    editorial_strength: int

    @property
    def total(self) -> int:
        return round(
            self.importance * WEIGHTS["importance"]
            + self.novelty * WEIGHTS["novelty"]
            + self.statistical_strength * WEIGHTS["statistical_strength"]
            + self.visual_strength * WEIGHTS["visual_strength"]
            + self.editorial_strength * WEIGHTS["editorial_strength"]
        )


def score_story(
    story: StoryObject, seen_story_types: Optional[Set[StoryType]] = None
) -> ScoreBreakdown:
    importance = TYPE_IMPORTANCE.get(story.story_type, 50)
    return ScoreBreakdown(
        importance=importance,
        novelty=_novelty(story, seen_story_types or set()),
        statistical_strength=_statistical_strength(story),
        visual_strength=_visual_strength(story),
        editorial_strength=_editorial_strength(story),
    )


# How many cards of the SAME story type one run may select. The novelty penalty
# only looks at what is already queued, so without this a round where several
# players happen to set a season high fills the whole batch with the same card —
# which is exactly the repetitive feed this account is not supposed to be.
MAX_PER_STORY_TYPE = 2

# How many cards one run may select about the SAME subject (a player, a team, a
# match). Measured on the live queue: round 26 gave FYNN SCHOTT three of its
# five cards — triple_double, player_of_round and season_high, all the same
# night by the same man. The per-type cap cannot see that, because each card
# was a different type. One remarkable player should get one card, not a
# takeover.
MAX_PER_SUBJECT = 1


def _subject_of(story: StoryObject) -> Optional[str]:
    """Who the card is ABOUT. A player story is about the player even though it
    also names his team, so the player wins; a round recap is about nobody and
    is never capped."""
    e = story.entities
    for scope, value in (
        ("player", e.player_external_id),
        ("team", e.team_external_id),
        ("match", e.match_external_id),
    ):
        if value:
            return f"{scope}:{value}"
    return None


def plan(
    stories: Iterable[StoryObject],
    top_n: int = 5,
    seen_story_types: Optional[Set[StoryType]] = None,
    max_per_type: int = MAX_PER_STORY_TYPE,
    max_per_subject: int = MAX_PER_SUBJECT,
) -> List[StoryObject]:
    """Score every story and select the top-N (marks selected/rejected).

    ``seen_story_types`` are story types already covered for this round (from
    the content queue); they get a novelty penalty so a re-run doesn't keep
    re-elevating content already produced. Within THIS batch, at most
    ``max_per_type`` stories of one type are selected, and at most
    ``max_per_subject`` about the same player/team/match, so a batch stays
    varied even when one detector fires repeatedly or one player has the kind
    of night that trips four detectors at once.
    """
    seen = seen_story_types or set()
    scored = [
        StoryObject(
            story_type=s.story_type,
            season_code=s.season_code,
            round_number=s.round_number,
            entities=s.entities,
            facts=s.facts,
            source_refs=s.source_refs,
            detected_at=s.detected_at,
            status=s.status,
            priority=score_story(s, seen).total,
        )
        for s in stories
    ]
    scored.sort(key=lambda s: (-s.priority, s.story_type.value))

    # Walk in priority order, taking the best of each type first and skipping a
    # type once it has filled its quota — so the batch keeps the strongest
    # stories without becoming three versions of the same card.
    selected_ids: Set[str] = set()
    per_type: Dict[StoryType, int] = {}
    per_subject: Dict[str, int] = {}
    for s in scored:
        if len(selected_ids) >= top_n:
            break
        if per_type.get(s.story_type, 0) >= max_per_type:
            continue
        subject = _subject_of(s)
        if subject and per_subject.get(subject, 0) >= max_per_subject:
            continue
        selected_ids.add(s.identity_key)
        per_type[s.story_type] = per_type.get(s.story_type, 0) + 1
        if subject:
            per_subject[subject] = per_subject.get(subject, 0) + 1
    return [
        StoryObject(
            story_type=s.story_type,
            season_code=s.season_code,
            round_number=s.round_number,
            entities=s.entities,
            facts=s.facts,
            source_refs=s.source_refs,
            detected_at=s.detected_at,
            status=StoryStatus.SELECTED if s.identity_key in selected_ids else StoryStatus.REJECTED,
            priority=s.priority,
        )
        for s in scored
    ]


# ---------------------------------------------------------------------------
# Dimension calculators
# ---------------------------------------------------------------------------


SEEN_NOVELTY_PENALTY = 40


def _novelty(story: StoryObject, seen_story_types: Set[StoryType]) -> int:
    """Rare/first-time story shapes are novel; recurring shapes less so.

    A story type already covered for this round (``seen_story_types``, from the
    content queue) is penalized: re-running a round should not keep boosting
    content that already exists."""
    if story.story_type in {
        StoryType.SEASON_HIGH,
        StoryType.TRIPLE_DOUBLE,
        StoryType.MILESTONE,
        StoryType.UPSET,
    }:
        base = 95
    elif story.story_type in {
        StoryType.BIGGEST_WIN,
        StoryType.BEST_PERFORMANCE,
        StoryType.PLAYER_OF_ROUND,
    }:
        base = 70
    else:
        base = 50

    if story.story_type in seen_story_types:
        return max(0, base - SEEN_NOVELTY_PENALTY)
    return base


def _statistical_strength(story: StoryObject) -> int:
    """How impressive are the raw numbers?"""
    f = story.facts

    if "impact_score" in f:
        # A player's impact score (~10-50 range) → 0..100
        return min(100, int(f["impact_score"] * 2))

    if "points" in f and isinstance(f["points"], (int, float)):
        return min(100, int(f["points"] * 2.5))

    if "margin" in f:
        return min(100, int(f["margin"] * 3))

    return 50


def _visual_strength(story: StoryObject) -> int:
    """Does the story lend itself to a strong visual?"""
    if story.story_type in {
        StoryType.PLAYER_OF_ROUND,
        StoryType.BEST_PERFORMANCE,
        StoryType.TRIPLE_DOUBLE,
        StoryType.SEASON_HIGH,
    }:
        return 90  # single-subject portraits work well
    if story.story_type == StoryType.ROUND_RECAP:
        return 75  # rich, but dense
    if story.story_type == StoryType.MATCH_FINAL:
        return 65
    return 60


def _editorial_strength(story: StoryObject) -> int:
    """Is there a narrative here?"""
    if story.story_type in {
        StoryType.COMEBACK,
        StoryType.UPSET,
        StoryType.WIN_STREAK,
        StoryType.MILESTONE,
    }:
        return 90
    if story.story_type == StoryType.ROUND_RECAP:
        return 80
    if story.story_type == StoryType.PLAYER_OF_ROUND:
        return 70
    return 50
