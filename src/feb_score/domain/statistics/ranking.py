"""FASE 23.3 — Pure-Python ranking for season leaderboards.

Deterministic, positional (1-based) ranking shared by the InMemory backend.
The SQLite/PostgreSQL backends resolve the same semantics with ROW_NUMBER()
directly in SQL; this module is the reference implementation used wherever
ranking happens in Python.

Semantics
---------
*  Positional (1-based): entries are sorted, then rank numbers are assigned
   sequentially.  Two entries with the same primary metric value receive
   *consecutive* ranks, not the same rank (e.g. 1, 2, 3 — never 1, 1, 3).
   DENSE_RANK / shared-rank semantics are deferred to a future phase.

*  Every ranking finishes with a deterministic secondary sort on
   ``*_external_id`` ASC so results are identical across re-runs and backends.

Tiebreakers per metric
----------------------
Player metrics (primary DESC, tiebreaker player_external_id ASC):
    points, rebounds, assists, steals, blocks, games_played — higher is better.
    turnovers — lower is better; primary sort ASC (fewest turnovers = rank 1).

Team metrics:
    classification   – wins DESC, losses ASC, point_difference DESC, id ASC.
    points_for       – DESC, id ASC.
    point_difference – DESC, id ASC.
    win_percentage   – DESC, wins DESC, id ASC.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from .model import (
    PlayerLeaderboardMetric,
    SeasonPlayerLeaderboardEntry,
    SeasonPlayerStats,
    SeasonTeamLeaderboardEntry,
    SeasonTeamStats,
    TeamLeaderboardMetric,
)


def validate_player_metric(metric: str) -> None:
    if metric not in PlayerLeaderboardMetric.ALL:
        raise ValueError(
            f"Unknown player metric '{metric}'. "
            f"Valid values: {PlayerLeaderboardMetric.ALL}"
        )


def validate_team_metric(metric: str) -> None:
    if metric not in TeamLeaderboardMetric.ALL:
        raise ValueError(
            f"Unknown team metric '{metric}'. "
            f"Valid values: {TeamLeaderboardMetric.ALL}"
        )


def rank_player_entries(
    aggregates: Iterable[SeasonPlayerStats],
    metric: str,
    limit: Optional[int] = None,
) -> List[SeasonPlayerLeaderboardEntry]:
    """Rank season player aggregates by *metric* and build ranked entries."""
    validate_player_metric(metric)

    aggs = list(aggregates)
    if metric == PlayerLeaderboardMetric.TURNOVERS:
        # Fewer turnovers is better → ASC primary.
        aggs.sort(key=lambda a: (getattr(a, metric), a.player_external_id))
    else:
        aggs.sort(key=lambda a: (-getattr(a, metric), a.player_external_id))

    if limit is not None:
        aggs = aggs[:limit]

    return [
        SeasonPlayerLeaderboardEntry(
            rank=rank,
            player_external_id=a.player_external_id,
            season_code=a.season_code,
            games_played=a.games_played,
            points=a.points,
            rebounds=a.rebounds,
            assists=a.assists,
            steals=a.steals,
            blocks=a.blocks,
            turnovers=a.turnovers,
            minutes=a.minutes,
        )
        for rank, a in enumerate(aggs, start=1)
    ]


def _pt_diff(a: SeasonTeamStats) -> int:
    return a.points_for - a.points_against


def _win_pct(a: SeasonTeamStats) -> float:
    return a.wins / a.games_played if a.games_played > 0 else 0.0


def rank_team_entries(
    aggregates: Iterable[SeasonTeamStats],
    metric: str,
    limit: Optional[int] = None,
) -> List[SeasonTeamLeaderboardEntry]:
    """Rank season team aggregates by *metric* and build ranked entries."""
    validate_team_metric(metric)

    aggs = list(aggregates)
    if metric == TeamLeaderboardMetric.CLASSIFICATION:
        aggs.sort(key=lambda a: (-a.wins, a.losses, -_pt_diff(a), a.team_external_id))
    elif metric == TeamLeaderboardMetric.POINTS_FOR:
        aggs.sort(key=lambda a: (-a.points_for, a.team_external_id))
    elif metric == TeamLeaderboardMetric.POINT_DIFFERENCE:
        aggs.sort(key=lambda a: (-_pt_diff(a), a.team_external_id))
    else:  # WIN_PERCENTAGE — validated above
        aggs.sort(key=lambda a: (-_win_pct(a), -a.wins, a.team_external_id))

    if limit is not None:
        aggs = aggs[:limit]

    return [
        SeasonTeamLeaderboardEntry(
            rank=rank,
            team_external_id=a.team_external_id,
            season_code=a.season_code,
            games_played=a.games_played,
            wins=a.wins,
            losses=a.losses,
            points_for=a.points_for,
            points_against=a.points_against,
            point_difference=_pt_diff(a),
            win_percentage=_win_pct(a),
        )
        for rank, a in enumerate(aggs, start=1)
    ]