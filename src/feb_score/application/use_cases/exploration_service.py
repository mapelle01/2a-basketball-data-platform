"""FASE 24 — Match & Player Exploration Service (Application Layer).

Read-only composition entry point for the exploration surface exposed to the
HTTP boundary:

* ``get_match_detail``        — a match plus its team/player boxscore projection;
* ``get_player_profile``      — a player with their season teams, totals, metrics;
* ``get_team_profile``        — a team with season totals, metrics and round
                                evolution;
* ``search_players``/``search_teams``/``search_matches`` — deterministic
                                name/external_id/substring searches.

Every method delegates exclusively to the repository interfaces (no SQL, no
business rules): ordering is applied here only where a repository contract
does not guarantee it (match boxscore), and the boxscore is read from the
``MatchStatsRepository`` projection — never from the aggregate's embedded
stats — because the stats tables are the authoritative BoxScore read model
(FASE 21.B3).

Profiles return ``None`` when the referenced entity does not exist (the HTTP
layer maps that to 404). A season filter is a *filter*, not a resource: a
player/team that exists but has no data in a season yields ``None`` totals
and metrics (nothing is invented).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..repositories.interfaces import MatchRepository, MatchStatsRepository, PlayerRepository, TeamRepository
from ...domain.match.model import Match
from ...domain.player.model import Player, PlayerRegistration
from ...domain.statistics.model import (
    PlayerStats,
    SeasonPlayerMetrics,
    SeasonPlayerStats,
    SeasonTeamMetrics,
    SeasonTeamRoundStats,
    SeasonTeamStats,
    TeamStats,
)
from ...domain.team.model import Team
from ...domain.value_objects import CompetitionId, ExternalId, SeasonCode


@dataclass(frozen=True)
class MatchDetail:
    """A match together with its boxscore projection (authoritative stats)."""

    match: Match
    team_stats: Tuple[TeamStats, ...]  # ordered by team_external_id
    player_stats: Tuple[PlayerStats, ...]  # ordered by player_external_id


@dataclass(frozen=True)
class PlayerProfile:
    """A player with their season teams, totals and metrics.

    ``player`` is the catalog aggregate when a ``players`` record exists,
    ``None`` when the identity is derived from the BoxScore stats projection
    (name/position/nationality/birth_date are then unknown). ``teams`` are the
    registrations of the season (catalog) or the teams the player appeared for
    in the season (derived); ``totals``/``metrics`` are None when the player
    has no stats rows in that season.
    """

    player: Optional[Player]
    season_code: str
    teams: Tuple[PlayerRegistration, ...]
    totals: Optional[SeasonPlayerStats]
    metrics: Optional[SeasonPlayerMetrics]


@dataclass(frozen=True)
class TeamProfile:
    """A team with its season read models.

    ``team`` is the catalog aggregate when a ``teams`` record exists, ``None``
    when the identity is derived from the BoxScore stats projection (name is
    then unknown). ``totals``/``metrics`` are None when the team has no stats
    rows in that season; ``rounds`` is the per-round evolution (empty when
    none, ordered by round_number ASC).
    """

    team: Optional[Team]
    season_code: str
    totals: Optional[SeasonTeamStats]
    metrics: Optional[SeasonTeamMetrics]
    rounds: Tuple[SeasonTeamRoundStats, ...]


class ExplorationService:
    """Read-only match/player/team exploration (FASE 24)."""

    def __init__(
        self,
        match_repo: MatchRepository,
        player_repo: PlayerRepository,
        team_repo: TeamRepository,
        stats_repo: MatchStatsRepository,
    ) -> None:
        self._matches = match_repo
        self._players = player_repo
        self._teams = team_repo
        self._stats = stats_repo

    # ------------------------------------------------------------------
    # Match detail (24.1)
    # ------------------------------------------------------------------

    def get_match_detail(self, external_id: ExternalId) -> Optional[MatchDetail]:
        match = self._matches.get_by_external_id(external_id)
        if match is None:
            return None
        team_stats = sorted(
            self._stats.list_team_stats(str(external_id)),
            key=lambda ts: ts.team_external_id,
        )
        player_stats = sorted(
            self._stats.list_player_stats(str(external_id)),
            key=lambda ps: ps.player_external_id,
        )
        return MatchDetail(
            match=match,
            team_stats=tuple(team_stats),
            player_stats=tuple(player_stats),
        )

    # ------------------------------------------------------------------
    # Player / team profiles (24.2 / 24.3)
    # ------------------------------------------------------------------

    def get_player_profile(self, season_code: SeasonCode, player_external_id: str) -> Optional[PlayerProfile]:
        player = self._players.get_by_external_id(ExternalId(player_external_id))
        totals = self._find_player_aggregate(season_code, player_external_id)
        metrics = self._find_player_metrics(season_code, player_external_id)
        has_stats = totals is not None or metrics is not None

        if player is None:
            # Identity derived from the authoritative stats projection: the
            # player exists (they have stats this season) but has no catalog
            # record. 404 stays for entities with no data at all.
            if not has_stats:
                return None
            team_ids = self._stats.list_player_season_teams(player_external_id, season_code)
            teams = tuple(
                PlayerRegistration(team_external_id=tid, season_code=season_code)
                for tid in sorted(team_ids)
            )
        else:
            teams = tuple(sorted(
                (reg for reg in player.registrations if str(reg.season_code) == str(season_code)),
                key=lambda reg: reg.team_external_id,
            ))
        return PlayerProfile(
            player=player,
            season_code=str(season_code),
            teams=teams,
            totals=totals,
            metrics=metrics,
        )

    def get_team_profile(self, season_code: SeasonCode, team_external_id: str) -> Optional[TeamProfile]:
        team = self._teams.get_by_external_id(ExternalId(team_external_id))
        totals = self._find_team_aggregate(season_code, team_external_id)
        metrics = self._find_team_metrics(season_code, team_external_id)
        rounds = tuple(self._stats.list_season_team_rounds(team_external_id, season_code))
        if team is None and totals is None and metrics is None and not rounds:
            return None
        return TeamProfile(
            team=team,
            season_code=str(season_code),
            totals=totals,
            metrics=metrics,
            rounds=rounds,
        )

    # ------------------------------------------------------------------
    # Search (24.4)
    # ------------------------------------------------------------------

    def search_players(self, name_query: str, limit: Optional[int] = None) -> List[Player]:
        return list(self._players.search_by_name(name_query, limit))

    def search_teams(self, name_query: str, limit: Optional[int] = None) -> List[Team]:
        return list(self._teams.search_by_name(name_query, limit))

    def search_matches(
        self,
        season_code: SeasonCode,
        *,
        competition_id: Optional[CompetitionId] = None,
        round_number: Optional[int] = None,
        team_external_id: Optional[str] = None,
        external_id_query: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Match]:
        return list(self._matches.search(
            season_code,
            competition_id=competition_id,
            round_number=round_number,
            team_external_id=team_external_id,
            external_id_query=external_id_query,
            limit=limit,
        ))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_player_aggregate(self, season_code: SeasonCode, player_external_id: str) -> Optional[SeasonPlayerStats]:
        for aggregate in self._stats.list_season_player_aggregates(season_code):
            if aggregate.player_external_id == player_external_id:
                return aggregate
        return None

    def _find_player_metrics(self, season_code: SeasonCode, player_external_id: str) -> Optional[SeasonPlayerMetrics]:
        for metrics in self._stats.list_season_player_metrics(season_code):
            if metrics.player_external_id == player_external_id:
                return metrics
        return None

    def _find_team_aggregate(self, season_code: SeasonCode, team_external_id: str) -> Optional[SeasonTeamStats]:
        for aggregate in self._stats.list_season_team_aggregates(season_code):
            if aggregate.team_external_id == team_external_id:
                return aggregate
        return None

    def _find_team_metrics(self, season_code: SeasonCode, team_external_id: str) -> Optional[SeasonTeamMetrics]:
        for metrics in self._stats.list_season_team_metrics(season_code):
            if metrics.team_external_id == team_external_id:
                return metrics
        return None