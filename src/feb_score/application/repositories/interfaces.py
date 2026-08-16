from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Optional

from ...domain.competition.model import Competition
from ...domain.correction.model import CorrectionProposal
from ...domain.leaderboard.model import Leaderboard
from ...domain.match.model import Match
from ...domain.player.model import Player
from ...domain.publication.model import Publication
from ...domain.ratings.model import PlayerRating
from ...domain.standings.model import StandingSnapshot
from ...domain.statistics.model import PlayerStats, SeasonPlayerStats, SeasonTeamStats, TeamStats
from ...domain.team.model import Team
from ...domain.value_objects import CompetitionId, ExternalId, LeaderboardId, MatchId, PlayerId, PublicationId, SeasonCode


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


class PlayerRepository(ABC):
    @abstractmethod
    def get_by_external_id(self, external_id: ExternalId) -> Optional[Player]:
        pass

    @abstractmethod
    def save(self, player: Player) -> None:
        pass


class TeamRepository(ABC):
    @abstractmethod
    def get_by_external_id(self, external_id: ExternalId) -> Optional[Team]:
        pass

    @abstractmethod
    def save(self, team: Team) -> None:
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
        self, season_code: SeasonCode
    ) -> Iterable[SeasonPlayerStats]:
        pass

    @abstractmethod
    def list_season_team_aggregates(
        self, season_code: SeasonCode
    ) -> Iterable[SeasonTeamStats]:
        pass
