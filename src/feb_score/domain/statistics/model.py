from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional


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


@dataclass(frozen=True)
class SeasonPlayerStats:
    player_external_id: str
    season_code: str
    games_played: int
    points: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    minutes: float

    def __post_init__(self) -> None:
        if self.games_played < 0:
            raise ValueError("games_played must be non-negative")
        for field_name in ("points", "rebounds", "assists", "steals", "blocks", "turnovers"):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.minutes < 0:
            raise ValueError("minutes must be non-negative")


@dataclass(frozen=True)
class SeasonTeamStats:
    """Season-level read model aggregated from match_team_stats.

    Only fields that exist as physical columns in match_team_stats are included.
    assists, steals, blocks and minutes are NOT available in TeamStats and are
    therefore intentionally absent.

    wins/losses are derived by comparing points_for vs points_against per match:
        win  → points_for > points_against
        loss → points_for < points_against
    Basketball does not have draws in regulation (overtime always produces a
    winner), so the model does not model ties.
    """

    team_external_id: str
    season_code: str
    games_played: int
    wins: int
    losses: int
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
            "games_played", "wins", "losses",
            "points_for", "points_against",
            "field_goals_made", "field_goals_attempted",
            "three_points_made", "three_points_attempted",
            "free_throws_made", "free_throws_attempted",
            "turnovers", "rebounds",
        ):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.wins + self.losses != self.games_played:
            raise ValueError(
                f"wins ({self.wins}) + losses ({self.losses}) must equal games_played ({self.games_played})"
            )


# ---------------------------------------------------------------------------
# Leaderboard models (FASE 23.3)
# ---------------------------------------------------------------------------

class PlayerLeaderboardMetric:
    """Valid metric names for player leaderboard ranking."""
    POINTS = "points"
    REBOUNDS = "rebounds"
    ASSISTS = "assists"
    STEALS = "steals"
    BLOCKS = "blocks"
    TURNOVERS = "turnovers"
    GAMES_PLAYED = "games_played"
    ALL: tuple = (POINTS, REBOUNDS, ASSISTS, STEALS, BLOCKS, TURNOVERS, GAMES_PLAYED)


class TeamLeaderboardMetric:
    """Valid metric names for team leaderboard ranking.

    CLASSIFICATION orders by: wins DESC, losses ASC, point_difference DESC, team_external_id ASC.
    """
    CLASSIFICATION = "classification"
    POINTS_FOR = "points_for"
    POINT_DIFFERENCE = "point_difference"
    WIN_PERCENTAGE = "win_percentage"
    ALL: tuple = (CLASSIFICATION, POINTS_FOR, POINT_DIFFERENCE, WIN_PERCENTAGE)


@dataclass(frozen=True)
class SeasonPlayerLeaderboardEntry:
    """A single entry in a player season leaderboard.

    rank is positional (1-based), assigned after sorting by the requested metric
    (DESC) with player_external_id ASC as tiebreaker. Two players with the same
    metric value receive consecutive ranks (no DENSE_RANK / shared-rank semantics).
    That simplification is documented here and deferred to a later phase if a
    public API requires shared ranks.
    """
    rank: int
    player_external_id: str
    season_code: str
    games_played: int
    points: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    minutes: float


@dataclass(frozen=True)
class SeasonTeamLeaderboardEntry:
    """A single entry in a team season leaderboard.

    point_difference = points_for - points_against  (derived, not stored)
    win_percentage   = wins / games_played           (0.0 if games_played == 0)

    rank is positional (1-based) with metric-specific tiebreakers.
    """
    rank: int
    team_external_id: str
    season_code: str
    games_played: int
    wins: int
    losses: int
    points_for: int
    points_against: int
    point_difference: int
    win_percentage: float


# ---------------------------------------------------------------------------
# Round-by-round evolution (FASE 24.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeasonTeamRoundStats:
    """FASE 24.3 — per-round read model for a team's season evolution.

    Aggregated from ``match_team_stats`` rows joined with the owning match's
    ``round_number`` (stored in ``matches.data``, not as a physical column).
    A round contributes ``games_played`` per match row; wins/losses are derived
    from ``points_for`` vs ``points_against`` (basketball has no draws).
    ``point_difference = points_for - points_against``. Ordered by
    ``round_number`` ASC.
    """

    team_external_id: str
    season_code: str
    round_number: int
    games_played: int
    wins: int
    losses: int
    points_for: int
    points_against: int
    point_difference: int

    def __post_init__(self) -> None:
        for field_name in (
            "round_number", "games_played", "wins", "losses",
            "points_for", "points_against",
        ):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.wins + self.losses != self.games_played:
            raise ValueError(
                f"wins ({self.wins}) + losses ({self.losses}) must equal games_played ({self.games_played})"
            )


# ---------------------------------------------------------------------------
# Season metrics models (FASE 23.4)
# ---------------------------------------------------------------------------

_PLAYER_PG_FIELDS = (
    "points_per_game", "rebounds_per_game", "assists_per_game",
    "steals_per_game", "blocks_per_game", "turnovers_per_game", "minutes_per_game",
)


@dataclass(frozen=True)
class SeasonPlayerMetrics:
    """FASE 23.4 — per-game season metrics for a player.

    Derived from ``SeasonPlayerStats`` totals by dividing each total by
    ``games_played`` (0.0 when ``games_played == 0`` — safe division). Per-game
    values are floats kept at full precision (not rounded). Totals are repeated
    here so the read model is self-contained for consumers and cross-validation.

    NOTE: a reliable efficiency metric (FIBA PIR / PER-like) is deliberately
    NOT derived: ``match_player_stats`` does not carry field-goal attempts,
    free-throw attempts, fouls or fouls drawn, which such a metric requires.
    Inventing approximations is out of scope for FASE 23.4.
    """

    player_external_id: str
    season_code: str
    games_played: int
    points: int
    points_per_game: float
    rebounds: int
    rebounds_per_game: float
    assists: int
    assists_per_game: float
    steals: int
    steals_per_game: float
    blocks: int
    blocks_per_game: float
    turnovers: int
    turnovers_per_game: float
    minutes: float
    minutes_per_game: float

    def __post_init__(self) -> None:
        if self.games_played < 0:
            raise ValueError("games_played must be non-negative")
        for field_name in ("points", "rebounds", "assists", "steals", "blocks", "turnovers", "minutes"):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be non-negative")
        for field_name in _PLAYER_PG_FIELDS:
            value = getattr(self, field_name)
            if not math.isfinite(value):
                raise ValueError(f"{field_name} must be finite")
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")


_TEAM_PG_FIELDS = (
    "points_per_game", "points_against_per_game", "point_difference_per_game",
    "win_percentage",
    "field_goals_made_per_game", "field_goals_attempted_per_game",
    "three_points_made_per_game", "three_points_attempted_per_game",
    "free_throws_made_per_game", "free_throws_attempted_per_game",
    "turnovers_per_game", "rebounds_per_game",
)

_TEAM_PG_NON_NEGATIVE = (
    "points_per_game", "points_against_per_game", "win_percentage",
    "field_goals_made_per_game", "field_goals_attempted_per_game",
    "three_points_made_per_game", "three_points_attempted_per_game",
    "free_throws_made_per_game", "free_throws_attempted_per_game",
    "turnovers_per_game", "rebounds_per_game",
)


@dataclass(frozen=True)
class SeasonTeamMetrics:
    """FASE 23.4 — per-game season metrics for a team.

    win_percentage is a PERCENTAGE: ``wins / games_played * 100`` (0..100).
    NOTE: this differs from ``SeasonTeamLeaderboardEntry.win_percentage``
    (FASE 23.3), which is the 0..1 fraction used for ranking.
    ``point_difference_per_game = (points_for - points_against) / games_played``
    and may be negative. Per-game values are 0.0 when ``games_played == 0``.
    """

    team_external_id: str
    season_code: str
    games_played: int
    wins: int
    losses: int
    points_for: int
    points_against: int
    points_per_game: float
    points_against_per_game: float
    point_difference_per_game: float
    win_percentage: float
    field_goals_made_per_game: float
    field_goals_attempted_per_game: float
    three_points_made_per_game: float
    three_points_attempted_per_game: float
    free_throws_made_per_game: float
    free_throws_attempted_per_game: float
    turnovers_per_game: float
    rebounds_per_game: float

    def __post_init__(self) -> None:
        for field_name in ("games_played", "wins", "losses", "points_for", "points_against"):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be non-negative")
        for field_name in _TEAM_PG_FIELDS:
            value = getattr(self, field_name)
            if not math.isfinite(value):
                raise ValueError(f"{field_name} must be finite")
        for field_name in _TEAM_PG_NON_NEGATIVE:
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be non-negative")

