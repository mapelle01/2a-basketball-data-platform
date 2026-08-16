"""FASE 23.3 — Season Leaderboard Service (Application Layer).

This module is the application entry point for ranked season leaderboards.
It validates the requested metric and delegates the ranking to the
``MatchStatsRepository`` backend, so every backend resolves the ranking
deterministically:

*  InMemory   – pure-Python ranking (``domain.statistics.ranking``).
*  SQLite     – ranking resolved in SQL with ``ROW_NUMBER()``.
*  PostgreSQL – ranking resolved in SQL with ``ROW_NUMBER()``.

No SQL lives in the Application or Domain layers.

Ranking semantics
-----------------
*  Positional (1-based): entries are sorted, then rank numbers are assigned
   sequentially.  Two entries with the same primary metric value receive
   *consecutive* ranks, not the same rank.  (e.g. 1, 2, 3 – never 1, 1, 3.)
   This simple approach is documented here; DENSE_RANK / shared-rank semantics
   are deferred to a future phase if a public API requires it.

*  Every ranking specifies a deterministic secondary sort on ``*_external_id``
   ASC so results are identical across re-runs and across backends.

Tiebreakers per metric
----------------------
Player metrics (primary DESC, tiebreaker player_external_id ASC):
    points, rebounds, assists, steals, blocks, games_played – higher is better.
    turnovers – lower is better; primary sort ASC (fewest turnovers = rank 1).

Team metrics:
    classification  – wins DESC, losses ASC, point_difference DESC, id ASC.
    points_for      – DESC, id ASC.
    point_difference – DESC, id ASC.
    win_percentage  – DESC, wins DESC, id ASC.
"""

from __future__ import annotations

from typing import List, Optional

from ..repositories.interfaces import MatchStatsRepository
from ...domain.statistics.model import (
    PlayerLeaderboardMetric,
    SeasonPlayerLeaderboardEntry,
    SeasonTeamLeaderboardEntry,
    TeamLeaderboardMetric,
)
from ...domain.value_objects import SeasonCode


class SeasonLeaderboardService:
    """Build ranked leaderboards from season aggregate data."""

    def __init__(self, stats_repo: MatchStatsRepository) -> None:
        self._repo = stats_repo

    # ------------------------------------------------------------------
    # Player leaderboards
    # ------------------------------------------------------------------

    def list_season_player_leaderboard(
        self,
        season_code: SeasonCode,
        metric: str,
        limit: Optional[int] = None,
    ) -> List[SeasonPlayerLeaderboardEntry]:
        """Return a ranked list of players for *season_code* ordered by *metric*.

        Args:
            season_code: The season to query (e.g. ``"2025-2026"``).
            metric:      One of ``PlayerLeaderboardMetric.ALL``.
            limit:       Optional maximum number of entries to return.

        Raises:
            ValueError: if *metric* is not a recognised player metric.
        """
        if metric not in PlayerLeaderboardMetric.ALL:
            raise ValueError(
                f"Unknown player metric '{metric}'. "
                f"Valid values: {PlayerLeaderboardMetric.ALL}"
            )
        return list(self._repo.list_season_player_leaderboard(season_code, metric, limit))

    # ------------------------------------------------------------------
    # Team leaderboards
    # ------------------------------------------------------------------

    def list_season_team_leaderboard(
        self,
        season_code: SeasonCode,
        metric: str,
        limit: Optional[int] = None,
    ) -> List[SeasonTeamLeaderboardEntry]:
        """Return a ranked list of teams for *season_code* ordered by *metric*.

        Args:
            season_code: The season to query.
            metric:      One of ``TeamLeaderboardMetric.ALL``.
            limit:       Optional maximum number of entries to return.

        Raises:
            ValueError: if *metric* is not a recognised team metric.
        """
        if metric not in TeamLeaderboardMetric.ALL:
            raise ValueError(
                f"Unknown team metric '{metric}'. "
                f"Valid values: {TeamLeaderboardMetric.ALL}"
            )
        return list(self._repo.list_season_team_leaderboard(season_code, metric, limit))