"""Story Object — the boundary between raw facts and editorial content.

A Story is what the Insight Engine detects. It carries only:
  - what kind of story it is (StoryType)
  - which entities it is about (player/team/round IDs)
  - the *facts* backing it (trace them to the data source)
  - a priority score assigned by the Content Planner
  - a template hint (which template can render this story type)

Stories carry NO copy, NO rendered image, NO channel. Those are downstream
concerns handled by the CopyGenerator, TemplateEngine and Publisher.

Rule: every field in ``facts`` MUST be traceable to a specific record in the
2aFEB_SCORE data platform. The Insight Engine never invents. The
CopyGenerator never invents. The FactValidator enforces the invariant.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class StoryType(str, Enum):
    # Match-level
    MATCH_FINAL = "match_final"
    BIGGEST_WIN = "biggest_win"
    CLOSEST_GAME = "closest_game"
    UPSET = "upset"
    COMEBACK = "comeback"

    # Player-level
    PLAYER_OF_ROUND = "player_of_round"
    TOP_SCORER = "top_scorer"
    TOP_REBOUNDER = "top_rebounder"
    TOP_ASSIST_PROVIDER = "top_assist_provider"
    BEST_PERFORMANCE = "best_performance"
    SEASON_HIGH = "season_high"
    DOUBLE_DOUBLE = "double_double"
    TRIPLE_DOUBLE = "triple_double"
    IRON_MAN = "iron_man"              # most minutes played (curious)
    SHARPSHOOTER = "sharpshooter"      # best 3-point game (shooting)
    PERFECT_NIGHT = "perfect_night"    # no misses from the field (shooting)

    # Team-level
    TEAM_OF_ROUND = "team_of_round"
    WIN_STREAK = "win_streak"
    LOSS_STREAK = "loss_streak"
    POSITION_CHANGE = "position_change"
    LEADERBOARD_CHANGE = "leaderboard_change"

    # Round-level
    ROUND_RECAP = "round_recap"
    STAT_LEADERBOARD = "stat_leaderboard"

    # Editorial
    MILESTONE = "milestone"
    DID_YOU_KNOW = "did_you_know"


class StoryStatus(str, Enum):
    DETECTED = "detected"
    SELECTED = "selected"      # picked by planner
    REJECTED = "rejected"      # planner declined
    SUPERSEDED = "superseded"  # a better story of the same identity replaced it


# Which template can render each story type. A story with no mapping cannot
# be rendered — the pipeline refuses to proceed rather than pick a template
# arbitrarily.
STORY_TO_TEMPLATE: Dict[StoryType, str] = {
    StoryType.MATCH_FINAL: "match_final",
    StoryType.PLAYER_OF_ROUND: "player_of_round",
    StoryType.ROUND_RECAP: "round_recap",
    StoryType.STAT_LEADERBOARD: "stat_leaderboard",
    # Reuse existing templates for related story shapes (visual work deferred):
    StoryType.BIGGEST_WIN: "match_final",       # a scoreboard, framed as the rout
    StoryType.DOUBLE_DOUBLE: "player_of_round",  # a player card with their line
    StoryType.TRIPLE_DOUBLE: "player_of_round",
    StoryType.SEASON_HIGH: "player_of_round",    # a player card, framed as the high
    StoryType.UPSET: "match_final",              # a scoreboard, framed as the upset
    # Curious / shooting player angles — a player card framed by the hero stat
    # each detector chooses (assists, minutes, threes…), not always points.
    StoryType.TOP_ASSIST_PROVIDER: "player_of_round",
    StoryType.IRON_MAN: "player_of_round",
    StoryType.SHARPSHOOTER: "player_of_round",
    StoryType.PERFECT_NIGHT: "player_of_round",
    # WIN_STREAK / LOSS_STREAK have no team-shaped template yet: they are
    # detected and scored, and surfaced in the pipeline summary, but not
    # rendered until a dedicated team template exists (deferred visual work).
}


@dataclass(frozen=True)
class StoryEntities:
    """The subjects a story is about. All optional — a round recap has none,
    a player story has player+team, a match story has home+away teams."""

    player_external_id: Optional[str] = None
    team_external_id: Optional[str] = None
    home_team_external_id: Optional[str] = None
    away_team_external_id: Optional[str] = None
    match_external_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class StoryObject:
    """A detected story ready to be scored and (maybe) turned into content.

    Identity (see ``identity_key``) is deterministic on story_type + season +
    round + entities + a hash of the facts. Two runs of the pipeline over the
    same round produce the same identity for the same story — so the queue
    can deduplicate: never publish the same story twice.
    """

    story_type: StoryType
    season_code: str
    round_number: Optional[int]
    entities: StoryEntities
    facts: Dict[str, Any]
    source_refs: Dict[str, str]
    detected_at: datetime = field(default_factory=datetime.utcnow)
    status: StoryStatus = StoryStatus.DETECTED
    priority: int = 0

    @property
    def template_id(self) -> Optional[str]:
        return STORY_TO_TEMPLATE.get(self.story_type)

    @property
    def identity_key(self) -> str:
        """Stable identity for dedup: same story detected twice = same key."""
        payload = {
            "story_type": self.story_type.value,
            "season_code": self.season_code,
            "round_number": self.round_number,
            "entities": self.entities.to_dict(),
            "facts_hash": self.facts_hash,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    @property
    def facts_hash(self) -> str:
        """Hash of the facts payload — for detecting content drift on the
        same identity (e.g. a stat correction post-publish)."""
        blob = json.dumps(self.facts, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "story_type": self.story_type.value,
            "season_code": self.season_code,
            "round_number": self.round_number,
            "entities": self.entities.to_dict(),
            "facts": self.facts,
            "source_refs": self.source_refs,
            "detected_at": self.detected_at.isoformat(),
            "status": self.status.value,
            "priority": self.priority,
            "template_id": self.template_id,
            "identity_key": self.identity_key,
            "facts_hash": self.facts_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoryObject":
        """Reconstruct a StoryObject from its ``to_dict`` form (persistence
        round-trip). Derived fields (template_id/identity_key/facts_hash) are
        recomputed, never read back."""
        return cls(
            story_type=StoryType(data["story_type"]),
            season_code=data["season_code"],
            round_number=data.get("round_number"),
            entities=StoryEntities(**data.get("entities", {})),
            facts=data.get("facts", {}),
            source_refs=data.get("source_refs", {}),
            detected_at=datetime.fromisoformat(data["detected_at"])
            if data.get("detected_at")
            else datetime.utcnow(),
            status=StoryStatus(data.get("status", StoryStatus.DETECTED.value)),
            priority=data.get("priority", 0),
        )
