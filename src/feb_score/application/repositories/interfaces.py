from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Iterable, Optional

from ...domain.competition.model import Competition
from ...domain.correction.model import CorrectionProposal
from ...domain.leaderboard.model import Leaderboard
from ...domain.match.model import Match
from ...domain.player.model import Player
from ...domain.publication.model import Publication
from ...domain.ratings.model import PlayerRating
from ...domain.standings.model import StandingSnapshot
from ...domain.statistics.model import (
    PlayerStats,
    SeasonPlayerLeaderboardEntry,
    SeasonPlayerMetrics,
    SeasonPlayerStats,
    SeasonTeamLeaderboardEntry,
    SeasonTeamMetrics,
    SeasonTeamRoundStats,
    SeasonTeamStats,
    TeamStats,
)
from ...domain.team.model import Team
from ...domain.value_objects import CompetitionId, ExternalId, LeaderboardId, MatchId, PlayerId, PublicationId, SeasonCode, TeamId


class MatchRepository(ABC):
    @abstractmethod
    def get_by_external_id(self, external_id: ExternalId) -> Optional[Match]:
        pass

    @abstractmethod
    def save(self, match: Match) -> None:
        pass

    @abstractmethod
    def list_by_season(self, competition_id: CompetitionId, season_code: SeasonCode) -> Iterable[Match]:
        pass

    @abstractmethod
    def search(
        self,
        season_code: SeasonCode,
        *,
        competition_id: Optional[CompetitionId] = None,
        round_number: Optional[int] = None,
        team_external_id: Optional[str] = None,
        external_id_query: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterable[Match]:
        """FASE 24.4 — deterministic match search.

        *season_code* is required (season isolation); every other filter is
        optional and AND-ed. ``round_number`` is read from the match's stored
        data blob, ``team_external_id`` matches home OR away. ``external_id_query``
        is a case-insensitive substring of the match external_id. Ordering is
        deterministic (external_id ASC); raises ValueError for an invalid
        ``round_number``.
        """
        pass


class PlayerRepository(ABC):
    @abstractmethod
    def get_by_external_id(self, external_id: ExternalId) -> Optional[Player]:
        pass

    @abstractmethod
    def save(self, player: Player) -> None:
        pass

    @abstractmethod
    def search_by_name(self, name_query: str, limit: Optional[int] = None) -> Iterable[Player]:
        """FASE 24.4 — case-insensitive substring search over player names.

        Ordering is deterministic (external_id ASC). The query is treated as a
        literal: wildcards in *name_query* are escaped, never interpreted.
        """
        pass

    @abstractmethod
    def upsert_catalog(self, external_id: ExternalId, player_id: PlayerId,
                       name: Optional[str], data: str) -> None:
        """FASE 24.1 — conservative catalog upsert keyed on external_id.

        Identity is canonical on ``external_id``. Existing ``player_id`` and a
        non-null existing name are preserved; the name column (and data blob)
        are only filled when the current name is NULL/empty. Creates the row
        when the external_id is not present.
        """
        pass

    @abstractmethod
    def get_many_by_external_ids(self, external_ids: Iterable[str]) -> Dict[str, Optional[Player]]:
        """FASE 24.2 — single-shot catalog read keyed on external_id.

        Returns ``{external_id: Player | None}`` for every requested id in a
        single query (avoids one-connection-per-lookup over a tunnel).
        """
        pass

    @abstractmethod
    def upsert_catalog_many(self, entities: Iterable["tuple"]) -> None:
        """FASE 24.2 — batch conservative catalog upsert (one statement).

        ``entities`` is an iterable of ``(external_id, player_id, name, data)``
        tuples. Identity is canonical on external_id; the same no-overwrite /
        null-fill policy as ``upsert_catalog`` applies, evaluated against the row
        current at write time. Used to avoid one round-trip per player.
        """
        pass


class TeamRepository(ABC):
    @abstractmethod
    def get_by_external_id(self, external_id: ExternalId) -> Optional[Team]:
        pass

    @abstractmethod
    def save(self, team: Team) -> None:
        pass

    @abstractmethod
    def search_by_name(self, name_query: str, limit: Optional[int] = None) -> Iterable[Team]:
        """FASE 24.4 — case-insensitive substring search over team names.

        Ordering is deterministic (external_id ASC). The query is treated as a
        literal: wildcards in *name_query* are escaped, never interpreted.
        """
        pass

    @abstractmethod
    def upsert_catalog(self, external_id: ExternalId, team_id: TeamId,
                       name: Optional[str], data: str) -> None:
        """FASE 24.1 — conservative catalog upsert keyed on external_id.

        Identity is canonical on ``external_id``. Existing ``team_id`` and a
        non-null existing name are preserved; the name column (and data blob)
        are only filled when the current name is NULL/empty. Creates the row
        when the external_id is not present.
        """
        pass

    @abstractmethod
    def get_many_by_external_ids(self, external_ids: Iterable[str]) -> Dict[str, Optional[Team]]:
        """FASE 24.2 — single-shot catalog read keyed on external_id."""
        pass

    @abstractmethod
    def upsert_catalog_many(self, entities: Iterable["tuple"]) -> None:
        """FASE 24.2 — batch conservative catalog upsert (one statement).

        ``entities`` is an iterable of ``(external_id, team_id, name, data)``.
        """
        pass


class CompetitionRepository(ABC):
    @abstractmethod
    def get_by_external_id(self, external_id: ExternalId) -> Optional[Competition]:
        pass

    @abstractmethod
    def save(self, competition: Competition) -> None:
        pass


class CorrectionRepository(ABC):
    @abstractmethod
    def get_by_id(self, proposal_id: str) -> Optional[CorrectionProposal]:
        pass

    @abstractmethod
    def save(self, proposal: CorrectionProposal) -> None:
        pass


class StandingRepository(ABC):
    @abstractmethod
    def save(self, standing_snapshot: StandingSnapshot) -> None:
        pass


class LeaderboardRepository(ABC):
    @abstractmethod
    def get_by_id(self, leaderboard_id: LeaderboardId) -> Optional[Leaderboard]:
        pass

    @abstractmethod
    def save(self, leaderboard: Leaderboard) -> None:
        pass


class RatingRepository(ABC):
    @abstractmethod
    def save(self, player_rating: PlayerRating) -> None:
        pass


class PublicationRepository(ABC):
    @abstractmethod
    def save(self, publication: Publication) -> None:
        pass


class IdempotencyRepository(ABC):
    @abstractmethod
    def has_processed(self, command_id: str) -> bool:
        pass

    @abstractmethod
    def mark_processed(self, command_id: str) -> None:
        pass


class MatchStatsRepository(ABC):
    """FASE 21.B3 — queryable projection of BoxScore team/player stats.

    The Match aggregate owns the stats (source of truth lives in matches.data);
    this repository exposes an indexed, UNIQUE-guaranteed read model so queries
    like "player stats in a match", "all players of a match" or "player stats
    across a season" are efficient and re-ingestion cannot duplicate rows
    (match_external_id + player_external_id).
    """

    @abstractmethod
    def save_player_stats(
        self, match_external_id: str, season_code: SeasonCode, player_stats: Iterable[PlayerStats]
    ) -> None:
        pass

    @abstractmethod
    def save_team_stats(
        self, match_external_id: str, season_code: SeasonCode, team_stats: Iterable[TeamStats]
    ) -> None:
        pass

    @abstractmethod
    def list_player_stats(self, match_external_id: str) -> Iterable[PlayerStats]:
        pass

    @abstractmethod
    def list_team_stats(self, match_external_id: str) -> Iterable[TeamStats]:
        pass

    @abstractmethod
    def list_player_stats_by_season(
        self, player_external_id: str, season_code: SeasonCode
    ) -> Iterable[PlayerStats]:
        pass

    @abstractmethod
    def list_season_player_aggregates(
        self, season_code: SeasonCode, limit: Optional[int] = None
    ) -> Iterable[SeasonPlayerStats]:
        pass

    @abstractmethod
    def list_season_team_aggregates(
        self, season_code: SeasonCode, limit: Optional[int] = None
    ) -> Iterable[SeasonTeamStats]:
        pass

    # ------------------------------------------------------------------ 23.3
    @abstractmethod
    def list_season_player_leaderboard(
        self,
        season_code: SeasonCode,
        metric: str,
        limit: Optional[int] = None,
    ) -> Iterable[SeasonPlayerLeaderboardEntry]:
        """Ranked season player leaderboard (positional rank 1..N).

        *metric* is one of ``PlayerLeaderboardMetric.ALL``; ranking is
        deterministic (metric DESC — ASC for turnovers — then
        player_external_id ASC).  Raises ValueError for an unknown metric.
        """
        pass

    @abstractmethod
    def list_season_team_leaderboard(
        self,
        season_code: SeasonCode,
        metric: str,
        limit: Optional[int] = None,
    ) -> Iterable[SeasonTeamLeaderboardEntry]:
        """Ranked season team leaderboard (positional rank 1..N).

        *metric* is one of ``TeamLeaderboardMetric.ALL``; ranking is
        deterministic with metric-specific tiebreakers.  Raises ValueError
        for an unknown metric.
        """
        pass

    # ------------------------------------------------------------------ 23.4
    @abstractmethod
    def list_season_player_metrics(
        self, season_code: SeasonCode, limit: Optional[int] = None
    ) -> Iterable[SeasonPlayerMetrics]:
        """Per-game season metrics for every player in *season_code*.

        Per-game values are derived from the season totals
        (``total / games_played``, 0.0 when ``games_played == 0``), kept at
        full float precision, ordered deterministically by player_external_id.
        """
        pass

    @abstractmethod
    def list_season_team_metrics(
        self, season_code: SeasonCode, limit: Optional[int] = None
    ) -> Iterable[SeasonTeamMetrics]:
        """Per-game season metrics for every team in *season_code*.

        Includes ``win_percentage = wins / games_played * 100`` (percentage,
        NOT the 0..1 fraction of ``SeasonTeamLeaderboardEntry``) and
        ``point_difference_per_game = (points_for - points_against) /
        games_played``. Ordered deterministically by team_external_id.
        """
        pass

    # ------------------------------------------------------------------ 24.3
    @abstractmethod
    def list_season_team_rounds(
        self, team_external_id: str, season_code: SeasonCode
    ) -> Iterable[SeasonTeamRoundStats]:
        """FASE 24.3 — per-round aggregates for one team in *season_code*.

        Rounds are read from the owning match's stored data blob (the match
        does not carry ``round_number`` as a physical column), so the
        implementation joins ``match_team_stats`` with the matches table.
        Matches without a stored round_number are excluded. Ordered by
        round_number ASC.
        """
        pass

    # ------------------------------------------------------------------ 24.2
    @abstractmethod
    def list_player_season_teams(
        self, player_external_id: str, season_code: SeasonCode
    ) -> Iterable[str]:
        """FASE 24.2 — distinct team external ids a player appeared for in a
        season, derived from their BoxScore stats rows.

        Used to build a player profile when the ``players`` catalog has no
        record for the player (identity derived from the authoritative stats
        projection). Ordered deterministically by team_external_id.
        """
        pass
