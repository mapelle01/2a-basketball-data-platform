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

from typing import Optional as _Optional

from .model import (
    PlayerStats,
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


def valoracion(stats: "PlayerStats") -> "_Optional[int]":
    """The FEB/FIBA official valuation of a single boxscore line.

    Unlike the season aggregate (which lacks shooting attempts), a per-game
    ``PlayerStats`` carries field-goal and free-throw attempts in its blob, so
    the standard valuation IS derivable here — deterministically, not invented:

        (PTS + REB + AST + STL + BLK + faltas recibidas)
      - (tiros de campo fallados + tiros libres fallados + pérdidas + faltas)

    Returns ``None`` when shooting attempts are absent (the valuation needs
    them). It omits ``tapones recibidos`` (blocks against), which the feed does
    not provide, so it can sit a point or two under the exact official figure;
    persisting the feed's own ``val`` would close that gap (a re-ingest task).
    """
    if stats.field_goals_attempted is None or stats.field_goals_made is None:
        return None
    missed_fg = max(0, stats.field_goals_attempted - stats.field_goals_made)
    missed_ft = max(0, (stats.free_throws_attempted or 0) - (stats.free_throws_made or 0))
    positive = (stats.points + stats.rebounds + stats.assists + stats.steals
                + stats.blocks + (stats.fouls_received or 0))
    negative = missed_fg + missed_ft + stats.turnovers + (stats.fouls or 0)
    return int(positive - negative)
