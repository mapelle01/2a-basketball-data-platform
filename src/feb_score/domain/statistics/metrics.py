"""FASE 23.4 — pure-Python derivation of per-game season metrics.

Reference implementation used by the InMemory backend; the SQLite and
PostgreSQL backends resolve the same semantics directly in SQL (per-game
values computed in the aggregate query, no rounding).

Only data that exists in ``SeasonPlayerStats`` / ``SeasonTeamStats`` is used.
A reliable player efficiency metric is deliberately NOT derived because
``match_player_stats`` lacks field-goal/free-throw attempts, fouls and fouls
drawn (see ``SeasonPlayerMetrics`` docstring).
"""

from __future__ import annotations

from typing import Iterable, List

from .model import (
    SeasonPlayerMetrics,
    SeasonPlayerStats,
    SeasonTeamMetrics,
    SeasonTeamStats,
)


def _safe_div(numerator: float, games_played: int) -> float:
    """numerator / games_played, or 0.0 when games_played <= 0."""
    return numerator / games_played if games_played > 0 else 0.0


def player_metrics(aggregate: SeasonPlayerStats) -> SeasonPlayerMetrics:
    """Build the per-game read model for a single player aggregate."""
    gp = aggregate.games_played
    return SeasonPlayerMetrics(
        player_external_id=aggregate.player_external_id,
        season_code=aggregate.season_code,
        games_played=gp,
        points=aggregate.points,
        points_per_game=_safe_div(aggregate.points, gp),
        rebounds=aggregate.rebounds,
        rebounds_per_game=_safe_div(aggregate.rebounds, gp),
        assists=aggregate.assists,
        assists_per_game=_safe_div(aggregate.assists, gp),
        steals=aggregate.steals,
        steals_per_game=_safe_div(aggregate.steals, gp),
        blocks=aggregate.blocks,
        blocks_per_game=_safe_div(aggregate.blocks, gp),
        turnovers=aggregate.turnovers,
        turnovers_per_game=_safe_div(aggregate.turnovers, gp),
        minutes=aggregate.minutes,
        minutes_per_game=_safe_div(aggregate.minutes, gp),
    )


def compute_player_metrics(
    aggregates: Iterable[SeasonPlayerStats],
) -> List[SeasonPlayerMetrics]:
    return [player_metrics(a) for a in aggregates]


def team_metrics(aggregate: SeasonTeamStats) -> SeasonTeamMetrics:
    """Build the per-game read model for a single team aggregate."""
    gp = aggregate.games_played
    pf = aggregate.points_for
    pa = aggregate.points_against
    return SeasonTeamMetrics(
        team_external_id=aggregate.team_external_id,
        season_code=aggregate.season_code,
        games_played=gp,
        wins=aggregate.wins,
        losses=aggregate.losses,
        points_for=pf,
        points_against=pa,
        points_per_game=_safe_div(pf, gp),
        points_against_per_game=_safe_div(pa, gp),
        point_difference_per_game=_safe_div(pf - pa, gp),
        win_percentage=(aggregate.wins / gp * 100.0) if gp > 0 else 0.0,
        field_goals_made_per_game=_safe_div(aggregate.field_goals_made, gp),
        field_goals_attempted_per_game=_safe_div(aggregate.field_goals_attempted, gp),
        three_points_made_per_game=_safe_div(aggregate.three_points_made, gp),
        three_points_attempted_per_game=_safe_div(aggregate.three_points_attempted, gp),
        free_throws_made_per_game=_safe_div(aggregate.free_throws_made, gp),
        free_throws_attempted_per_game=_safe_div(aggregate.free_throws_attempted, gp),
        turnovers_per_game=_safe_div(aggregate.turnovers, gp),
        rebounds_per_game=_safe_div(aggregate.rebounds, gp),
    )


def compute_team_metrics(
    aggregates: Iterable[SeasonTeamStats],
) -> List[SeasonTeamMetrics]:
    return [team_metrics(a) for a in aggregates]