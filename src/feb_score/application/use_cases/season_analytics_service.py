"""FASE 23.5 — Season Analytics Service (Application Layer).

Composed read entry point that exposes the whole season analytics surface to
the HTTP boundary while REUSING the FASE 23.3 (``SeasonLeaderboardService``)
and FASE 23.4 (``SeasonMetricsService``) services. Aggregates (23.1/23.2) are
read straight from ``MatchStatsRepository`` — they have no service of their
own because they carry no derivation beyond the repository's aggregation.

No SQL and no business rules live here; the only logic is parameter plumbing
and metric whitelisting delegated to the services. ``ValueError`` raised for an
unknown metric surfaces to the HTTP layer as a 400.
"""

from __future__ import annotations

from typing import List, Optional

from ..repositories.interfaces import MatchStatsRepository
from ...domain.statistics.model import (
    SeasonPlayerLeaderboardEntry,
    SeasonPlayerMetrics,
    SeasonPlayerStats,
    SeasonTeamLeaderboardEntry,
    SeasonTeamMetrics,
    SeasonTeamStats,
)
from ...domain.value_objects import SeasonCode
from .leaderboard_service import SeasonLeaderboardService
from .season_metrics_service import SeasonMetricsService


class SeasonAnalyticsService:
    """Read-only season analytics: aggregates, leaderboards and metrics."""

    def __init__(self, stats_repo: MatchStatsRepository) -> None:
        self._repo = stats_repo
        self._leaderboards = SeasonLeaderboardService(stats_repo)
        self._metrics = SeasonMetricsService(stats_repo)

    # ------------------------------------------------------------------
    # Aggregates (23.1 / 23.2)
    # ------------------------------------------------------------------

    def list_season_player_aggregates(
        self, season_code: SeasonCode, limit: Optional[int] = None
    ) -> List[SeasonPlayerStats]:
        return list(self._repo.list_season_player_aggregates(season_code, limit))

    def list_season_team_aggregates(
        self, season_code: SeasonCode, limit: Optional[int] = None
    ) -> List[SeasonTeamStats]:
        return list(self._repo.list_season_team_aggregates(season_code, limit))

    # ------------------------------------------------------------------
    # Leaderboards (23.3)
    # ------------------------------------------------------------------

    def list_season_player_leaderboard(
        self,
        season_code: SeasonCode,
        metric: str,
        limit: Optional[int] = None,
    ) -> List[SeasonPlayerLeaderboardEntry]:
        """Ranked players for *season_code* ordered by *metric*.

        Raises ValueError for an unknown player metric.
        """
        return self._leaderboards.list_season_player_leaderboard(season_code, metric, limit)

    def list_season_team_leaderboard(
        self,
        season_code: SeasonCode,
        metric: str,
        limit: Optional[int] = None,
    ) -> List[SeasonTeamLeaderboardEntry]:
        """Ranked teams for *season_code* ordered by *metric*.

        Raises ValueError for an unknown team metric.
        """
        return self._leaderboards.list_season_team_leaderboard(season_code, metric, limit)

    # ------------------------------------------------------------------
    # Metrics (23.4)
    # ------------------------------------------------------------------

    def list_season_player_metrics(
        self, season_code: SeasonCode, limit: Optional[int] = None
    ) -> List[SeasonPlayerMetrics]:
        return self._metrics.list_season_player_metrics(season_code, limit)

    def list_season_team_metrics(
        self, season_code: SeasonCode, limit: Optional[int] = None
    ) -> List[SeasonTeamMetrics]:
        return self._metrics.list_season_team_metrics(season_code, limit)