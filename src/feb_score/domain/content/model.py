from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ContentType(str, Enum):
    MATCH_RESULT = "match_result"
    ROUND_RECAP = "round_recap"
    PLAYER_HIGHLIGHT = "player_highlight"
    POWER_RANKING = "power_ranking"
    CLASSIFICATION = "classification"


class ContentPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Channel(str, Enum):
    INSTAGRAM_POST = "instagram_post"
    INSTAGRAM_STORY = "instagram_story"
    WEB = "web"
    API = "api"


# ---------------------------------------------------------------------------
# "What happened" — raw facts extracted from the match
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchFacts:
    match_external_id: str
    season_code: str
    round_number: int
    scheduled_at: datetime
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int
    periods: Tuple[Tuple[int, int], ...] = ()
    venue: Optional[str] = None

    @property
    def margin(self) -> int:
        return abs(self.home_score - self.away_score)

    @property
    def winner_id(self) -> str:
        return self.home_team_id if self.home_score > self.away_score else self.away_team_id

    @property
    def loser_id(self) -> str:
        return self.away_team_id if self.home_score > self.away_score else self.home_team_id

    @property
    def is_home_win(self) -> bool:
        return self.home_score > self.away_score

    @property
    def total_points(self) -> int:
        return self.home_score + self.away_score


@dataclass(frozen=True)
class PlayerLine:
    player_external_id: str
    team_external_id: str
    points: int
    rebounds: int
    assists: int
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    minutes: float = 0.0

    @property
    def pra(self) -> int:
        return self.points + self.rebounds + self.assists

    @property
    def impact(self) -> float:
        return (
            self.points
            + self.rebounds * 1.2
            + self.assists * 1.5
            + self.steals * 2.0
            + self.blocks * 1.5
            - self.turnovers
        )


@dataclass(frozen=True)
class TeamLine:
    team_external_id: str
    points_for: int
    points_against: int
    field_goals_made: int
    field_goals_attempted: int
    three_points_made: int
    three_points_attempted: int
    free_throws_made: int
    free_throws_attempted: int
    turnovers: int
    rebounds: int

    @property
    def fg_pct(self) -> float:
        return self.field_goals_made / self.field_goals_attempted if self.field_goals_attempted > 0 else 0.0

    @property
    def three_pct(self) -> float:
        return self.three_points_made / self.three_points_attempted if self.three_points_attempted > 0 else 0.0

    @property
    def ft_pct(self) -> float:
        return self.free_throws_made / self.free_throws_attempted if self.free_throws_attempted > 0 else 0.0


# ---------------------------------------------------------------------------
# "What matters" — highlights and signals detected from the data
# ---------------------------------------------------------------------------


class HighlightType(str, Enum):
    TOP_SCORER = "top_scorer"
    DOUBLE_DOUBLE = "double_double"
    TRIPLE_DOUBLE = "triple_double"
    THIRTY_PLUS = "thirty_plus"
    TWENTY_PLUS = "twenty_plus"
    CLOSE_GAME = "close_game"
    BLOWOUT = "blowout"
    HIGH_SCORING = "high_scoring"
    LOW_SCORING = "low_scoring"
    OVERTIME = "overtime"
    SHOOTING_DISPLAY = "shooting_display"
    BLOCK_PARTY = "block_party"
    ASSIST_LEADER = "assist_leader"
    REBOUND_KING = "rebound_king"


@dataclass(frozen=True)
class Highlight:
    highlight_type: HighlightType
    subject_id: str
    subject_type: str  # "player" or "team"
    value: float
    label: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.highlight_type.value,
            "subject_id": self.subject_id,
            "subject_type": self.subject_type,
            "value": self.value,
            "label": self.label,
        }


# ---------------------------------------------------------------------------
# Content object — the unified output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchResultContent:
    content_id: str
    content_type: ContentType
    priority: ContentPriority
    generated_at: datetime

    facts: MatchFacts
    home_team: TeamLine
    away_team: TeamLine
    player_lines: Tuple[PlayerLine, ...]
    highlights: Tuple[Highlight, ...]

    headline: str
    subheadline: str

    channels: Tuple[Channel, ...] = (Channel.INSTAGRAM_POST, Channel.API)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content_id": self.content_id,
            "content_type": self.content_type.value,
            "priority": self.priority.value,
            "generated_at": self.generated_at.isoformat(),
            "headline": self.headline,
            "subheadline": self.subheadline,
            "facts": {
                "match_external_id": self.facts.match_external_id,
                "season_code": self.facts.season_code,
                "round_number": self.facts.round_number,
                "scheduled_at": self.facts.scheduled_at.isoformat(),
                "home_team_id": self.facts.home_team_id,
                "away_team_id": self.facts.away_team_id,
                "home_score": self.facts.home_score,
                "away_score": self.facts.away_score,
                "margin": self.facts.margin,
                "venue": self.facts.venue,
            },
            "highlights": [h.to_dict() for h in self.highlights],
            "top_performers": [
                {
                    "player_external_id": p.player_external_id,
                    "team_external_id": p.team_external_id,
                    "points": p.points,
                    "rebounds": p.rebounds,
                    "assists": p.assists,
                    "steals": p.steals,
                    "blocks": p.blocks,
                }
                for p in sorted(self.player_lines, key=lambda x: -x.impact)[:5]
            ],
            "channels": [c.value for c in self.channels],
        }
