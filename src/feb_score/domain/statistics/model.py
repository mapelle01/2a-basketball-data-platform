from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class PlayerStats:
    player_external_id: str
    team_external_id: str
    points: int
    rebounds: int
    assists: int
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    minutes: float = 0.0
    played_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        for field_name in ("points", "rebounds", "assists", "steals", "blocks", "turnovers"):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.minutes < 0:
            raise ValueError("minutes must be non-negative")

    def to_dict(self) -> Dict[str, object]:
        return {
            "player_external_id": self.player_external_id,
            "team_external_id": self.team_external_id,
            "points": self.points,
            "rebounds": self.rebounds,
            "assists": self.assists,
            "steals": self.steals,
            "blocks": self.blocks,
            "turnovers": self.turnovers,
            "minutes": self.minutes,
            "played_at": self.played_at.isoformat() if self.played_at else None,
        }


@dataclass(frozen=True)
class TeamStats:
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

    def __post_init__(self) -> None:
        for field_name in (
            "points_for",
            "points_against",
            "field_goals_made",
            "field_goals_attempted",
            "three_points_made",
            "three_points_attempted",
            "free_throws_made",
            "free_throws_attempted",
            "turnovers",
            "rebounds",
        ):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.field_goals_attempted < self.field_goals_made:
            raise ValueError("field_goals_attempted must be >= field_goals_made")
        if self.three_points_attempted < self.three_points_made:
            raise ValueError("three_points_attempted must be >= three_points_made")
        if self.free_throws_attempted < self.free_throws_made:
            raise ValueError("free_throws_attempted must be >= free_throws_made")

    def to_dict(self) -> Dict[str, object]:
        return {
            "team_external_id": self.team_external_id,
            "points_for": self.points_for,
            "points_against": self.points_against,
            "field_goals_made": self.field_goals_made,
            "field_goals_attempted": self.field_goals_attempted,
            "three_points_made": self.three_points_made,
            "three_points_attempted": self.three_points_attempted,
            "free_throws_made": self.free_throws_made,
            "free_throws_attempted": self.free_throws_attempted,
            "turnovers": self.turnovers,
            "rebounds": self.rebounds,
        }
