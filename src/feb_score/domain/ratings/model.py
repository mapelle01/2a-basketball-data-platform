from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from ..common import AggregateRoot
from ..errors import InvalidRatingCalculation
from ..statistics.model import PlayerStats, SeasonTeamStats
from ..value_objects import ExternalId, RatingValue, RatingVersion, SeasonCode


@dataclass
class PlayerRating(AggregateRoot):
    player_external_id: ExternalId
    season_code: SeasonCode
    rating_value: RatingValue
    rating_version: RatingVersion
    calculated_at: datetime
    source_stats: List[Dict[str, object]] = field(default_factory=list)

    @classmethod
    def compute_from_stats(
        cls,
        player_external_id: ExternalId,
        season_code: SeasonCode,
        stats: Iterable[PlayerStats],
        rating_version: RatingVersion,
        calculated_at: datetime,
    ) -> PlayerRating:
        stats_list = list(stats)
        if not stats_list:
            raise InvalidRatingCalculation("Cannot compute rating without player stats")

        total_points = sum(entry.points for entry in stats_list)
        total_rebounds = sum(entry.rebounds for entry in stats_list)
        total_assists = sum(entry.assists for entry in stats_list)
        total_turnovers = sum(entry.turnovers for entry in stats_list)
        games = len(stats_list)
        rating_score = (
            total_points * 1.0
            + total_rebounds * 1.2
            + total_assists * 1.5
            - total_turnovers * 0.8
        ) / games

        if rating_score < 0:
            raise InvalidRatingCalculation("Computed rating must be non-negative")

        return PlayerRating(
            player_external_id=player_external_id,
            season_code=season_code,
            rating_value=RatingValue(round(rating_score, 2)),
            rating_version=rating_version,
            calculated_at=calculated_at,
            source_stats=[stat.to_dict() for stat in stats_list],
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "player_external_id": str(self.player_external_id),
            "season_code": str(self.season_code),
            "rating_value": self.rating_value.value,
            "rating_version": str(self.rating_version),
            "calculated_at": self.calculated_at.isoformat(),
            "source_stats": self.source_stats,
        }


# ---------------------------------------------------------------------------
# TeamRating v1.0
# ---------------------------------------------------------------------------

def _safe_div(n: float, d: float) -> float:
    return n / d if d > 0 else 0.0


@dataclass(frozen=True)
class TeamRating:
    """Composite team rating built from season aggregates.

    Algorithm v1.0 — four pillars, each 0-100, weighted into a final score:

      offensive_rating:  scoring volume + efficiency (eFG%, FT rate)
      defensive_rating:  opponent scoring suppression + forced turnovers
      net_rating:        point differential per game (scaled)
      win_factor:        win percentage (0-100)

    Final = 0.25 * offensive + 0.25 * defensive + 0.25 * net + 0.25 * win
    """

    team_external_id: str
    season_code: str
    rating_version: str
    calculated_at: datetime
    rating_value: float
    offensive_rating: float
    defensive_rating: float
    net_rating: float
    win_factor: float
    games_played: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "team_external_id": self.team_external_id,
            "season_code": self.season_code,
            "rating_version": self.rating_version,
            "calculated_at": self.calculated_at.isoformat(),
            "rating_value": round(self.rating_value, 2),
            "offensive_rating": round(self.offensive_rating, 2),
            "defensive_rating": round(self.defensive_rating, 2),
            "net_rating": round(self.net_rating, 2),
            "win_factor": round(self.win_factor, 2),
            "games_played": self.games_played,
        }

    @classmethod
    def compute(
        cls,
        stats: SeasonTeamStats,
        *,
        rating_version: str = "v1.0",
        calculated_at: Optional[datetime] = None,
        league_avg_ppg: float = 75.0,
    ) -> TeamRating:
        if stats.games_played == 0:
            raise InvalidRatingCalculation("Cannot compute team rating without games played")

        calculated_at = calculated_at or datetime.utcnow()
        gp = stats.games_played

        # Offensive rating (0-100): scoring output + shooting efficiency
        ppg = stats.points_for / gp
        efg = _safe_div(
            stats.field_goals_made + 0.5 * stats.three_points_made,
            stats.field_goals_attempted,
        )
        ft_rate = _safe_div(stats.free_throws_made, stats.free_throws_attempted)
        off_volume = min(ppg / league_avg_ppg * 50.0, 60.0)
        off_efficiency = efg * 30.0 + ft_rate * 10.0
        offensive = min(off_volume + off_efficiency, 100.0)

        # Defensive rating (0-100): points allowed suppression + forced turnovers
        papg = stats.points_against / gp
        def_suppression = max(0.0, (league_avg_ppg - papg) / league_avg_ppg * 50.0 + 50.0)
        opp_to_rate = _safe_div(stats.turnovers, gp) / 20.0 * 30.0
        defensive = min(def_suppression + opp_to_rate, 100.0)

        # Net rating (0-100): point differential scaled around 50
        diff_pg = (stats.points_for - stats.points_against) / gp
        net = max(0.0, min(100.0, 50.0 + diff_pg * 2.5))

        # Win factor (0-100)
        win_pct = stats.wins / gp * 100.0

        final = 0.25 * offensive + 0.25 * defensive + 0.25 * net + 0.25 * win_pct

        return TeamRating(
            team_external_id=stats.team_external_id,
            season_code=stats.season_code,
            rating_version=rating_version,
            calculated_at=calculated_at,
            rating_value=round(final, 2),
            offensive_rating=round(offensive, 2),
            defensive_rating=round(defensive, 2),
            net_rating=round(net, 2),
            win_factor=round(win_pct, 2),
            games_played=gp,
        )


# ---------------------------------------------------------------------------
# PowerRanking v1.0
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PowerRankingEntry:
    """A single entry in the power ranking — a team rating with a rank."""

    rank: int
    team_external_id: str
    season_code: str
    rating_value: float
    offensive_rating: float
    defensive_rating: float
    net_rating: float
    win_factor: float
    games_played: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "rank": self.rank,
            "team_external_id": self.team_external_id,
            "season_code": self.season_code,
            "rating_value": round(self.rating_value, 2),
            "offensive_rating": round(self.offensive_rating, 2),
            "defensive_rating": round(self.defensive_rating, 2),
            "net_rating": round(self.net_rating, 2),
            "win_factor": round(self.win_factor, 2),
            "games_played": self.games_played,
        }


def compute_power_ranking(
    team_ratings: Iterable[TeamRating],
    limit: Optional[int] = None,
) -> List[PowerRankingEntry]:
    """Rank teams by rating_value DESC, team_external_id ASC as tiebreaker."""
    sorted_ratings = sorted(
        team_ratings,
        key=lambda r: (-r.rating_value, r.team_external_id),
    )
    if limit is not None:
        sorted_ratings = sorted_ratings[:limit]
    return [
        PowerRankingEntry(
            rank=i,
            team_external_id=r.team_external_id,
            season_code=r.season_code,
            rating_value=r.rating_value,
            offensive_rating=r.offensive_rating,
            defensive_rating=r.defensive_rating,
            net_rating=r.net_rating,
            win_factor=r.win_factor,
            games_played=r.games_played,
        )
        for i, r in enumerate(sorted_ratings, start=1)
    ]


# ---------------------------------------------------------------------------
# FormIndex v1.0
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FormIndex:
    """Recent-form indicator: compares last N games to the season average.

    form_rating:   the rating computed over the last N games
    season_rating: the rating computed over the full season
    form_index:    form_rating / season_rating (>1.0 = improving, <1.0 = declining)
    trend:         "rising" | "stable" | "falling"
    """

    entity_external_id: str
    entity_type: str  # "player" or "team"
    season_code: str
    window: int
    form_rating: float
    season_rating: float
    form_index: float
    trend: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "entity_external_id": self.entity_external_id,
            "entity_type": self.entity_type,
            "season_code": self.season_code,
            "window": self.window,
            "form_rating": round(self.form_rating, 2),
            "season_rating": round(self.season_rating, 2),
            "form_index": round(self.form_index, 2),
            "trend": self.trend,
        }

    @classmethod
    def compute_player(
        cls,
        player_external_id: str,
        season_code: str,
        all_stats: List[PlayerStats],
        window: int = 5,
    ) -> FormIndex:
        if len(all_stats) < 2:
            raise InvalidRatingCalculation(
                "FormIndex requires at least 2 games"
            )

        ordered = sorted(all_stats, key=lambda s: s.played_at or datetime.min)
        recent = ordered[-window:]

        season_avg = _player_impact(ordered)
        form_avg = _player_impact(recent)
        index = _safe_div(form_avg, season_avg) if season_avg > 0 else 1.0
        trend = "rising" if index > 1.05 else ("falling" if index < 0.95 else "stable")

        return FormIndex(
            entity_external_id=player_external_id,
            entity_type="player",
            season_code=season_code,
            window=len(recent),
            form_rating=round(form_avg, 2),
            season_rating=round(season_avg, 2),
            form_index=round(index, 2),
            trend=trend,
        )

    @classmethod
    def compute_team(
        cls,
        team_external_id: str,
        season_code: str,
        round_diffs: List[float],
        window: int = 5,
    ) -> FormIndex:
        """Compute team form from per-round point differentials.

        round_diffs: list of (points_for - points_against) for each round, in order.
        """
        if len(round_diffs) < 2:
            raise InvalidRatingCalculation(
                "FormIndex requires at least 2 rounds"
            )

        recent = round_diffs[-window:]
        season_avg = sum(round_diffs) / len(round_diffs)
        form_avg = sum(recent) / len(recent)
        # Shift to positive base for index calculation
        base = abs(season_avg) if season_avg != 0 else 1.0
        index = 1.0 + (form_avg - season_avg) / base if base > 0 else 1.0
        trend = "rising" if index > 1.05 else ("falling" if index < 0.95 else "stable")

        return FormIndex(
            entity_external_id=team_external_id,
            entity_type="team",
            season_code=season_code,
            window=len(recent),
            form_rating=round(form_avg, 2),
            season_rating=round(season_avg, 2),
            form_index=round(index, 2),
            trend=trend,
        )


def _player_impact(stats: List[PlayerStats]) -> float:
    """Simple per-game impact score for form comparison."""
    if not stats:
        return 0.0
    total = sum(
        s.points + s.rebounds * 1.2 + s.assists * 1.5
        + s.steals * 2.0 + s.blocks * 1.5
        - s.turnovers * 1.0
        for s in stats
    )
    return total / len(stats)
