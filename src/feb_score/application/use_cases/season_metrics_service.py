"""FASE 23.4 — Season Metrics Service (Application Layer).

Thin application entry point for per-game season metrics. It delegates data
retrieval to ``MatchStatsRepository``; every backend resolves the per-game
derivation deterministically (PostgreSQL/SQLite in SQL, InMemory in pure
Python via ``domain.statistics.metrics``). No SQL lives in Application/Domain.
"""

from __future__ import annotations

from typing import List, Optional

from ..repositories.interfaces import MatchStatsRepository
from ...domain.statistics.model import SeasonPlayerMetrics, SeasonTeamMetrics
from ...domain.value_objects import SeasonCode


class SeasonMetricsService:
    """Build per-game season metrics from season aggregate data."""

    def __init__(self, stats_repo: MatchStatsRepository) -> None:
        self._repo = stats_repo

    def list_season_player_metrics(
        self, season_code: SeasonCode, limit: Optional[int] = None
    ) -> List[SeasonPlayerMetrics]:
        """Per-game metrics for every player of *season_code* (first *limit*)."""
        return list(self._repo.list_season_player_metrics(season_code, limit))

    def list_season_team_metrics(
        self, season_code: SeasonCode, limit: Optional[int] = None
    ) -> List[SeasonTeamMetrics]:
        """Per-game metrics for every team of *season_code* (first *limit*)."""
        return list(self._repo.list_season_team_metrics(season_code, limit))