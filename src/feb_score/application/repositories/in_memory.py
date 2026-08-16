from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .interfaces import (
    CompetitionRepository,
    CorrectionRepository,
    IdempotencyRepository,
    LeaderboardRepository,
    MatchRepository,
    MatchStatsRepository,
    PlayerRepository,
    PublicationRepository,
    RatingRepository,
    StandingRepository,
    TeamRepository,
)
from ...domain.competition.model import Competition
from ...domain.correction.model import CorrectionProposal
from ...domain.leaderboard.model import Leaderboard
from ...domain.match.model import Match
from ...domain.player.model import Player
from ...domain.publication.model import Publication
from ...domain.ratings.model import PlayerRating
from ...domain.standings.model import StandingSnapshot
from ...domain.statistics.model import PlayerStats, TeamStats
from ...domain.team.model import Team
from ...domain.value_objects import CompetitionId, ExternalId, LeaderboardId, SeasonCode


class InMemoryMatchRepository(MatchRepository):
    def __init__(self) -> None:
        self._matches: Dict[str, Match] = {}

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Match]:
        return self._matches.get(str(external_id))

    def save(self, match: Match) -> None:
        self._matches[str(match.external_id)] = match

    def list_by_season(self, competition_id: CompetitionId, season_code: SeasonCode) -> Iterable[Match]:
        return [
            match
            for match in self._matches.values()
            if str(match.season_code) == str(season_code)
            and str(match.competition_id) == str(competition_id)
        ]


class InMemoryPlayerRepository(PlayerRepository):
    def __init__(self) -> None:
        self._players: Dict[str, Player] = {}

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Player]:
        return self._players.get(str(external_id))

    def save(self, player: Player) -> None:
        self._players[str(player.external_id)] = player


class InMemoryTeamRepository(TeamRepository):
    def __init__(self) -> None:
        self._teams: Dict[str, Team] = {}

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Team]:
        return self._teams.get(str(external_id))

    def save(self, team: Team) -> None:
        self._teams[str(team.external_id)] = team


class InMemoryCompetitionRepository(CompetitionRepository):
    def __init__(self) -> None:
        self._competitions: Dict[str, Competition] = {}

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Competition]:
        return self._competitions.get(str(external_id))

    def save(self, competition: Competition) -> None:
        self._competitions[str(competition.external_id)] = competition


class InMemoryCorrectionRepository(CorrectionRepository):
    def __init__(self) -> None:
        self._proposals: Dict[str, CorrectionProposal] = {}

    def get_by_id(self, proposal_id: str) -> Optional[CorrectionProposal]:
        return self._proposals.get(proposal_id)

    def save(self, proposal: CorrectionProposal) -> None:
        self._proposals[proposal.proposal_id.value] = proposal


class InMemoryStandingRepository(StandingRepository):
    def __init__(self) -> None:
        self._standings: List[StandingSnapshot] = []

    def save(self, standing_snapshot: StandingSnapshot) -> None:
        self._standings.append(standing_snapshot)


class InMemoryLeaderboardRepository(LeaderboardRepository):
    def __init__(self) -> None:
        self._leaderboards: Dict[str, Leaderboard] = {}

    def get_by_id(self, leaderboard_id: LeaderboardId) -> Optional[Leaderboard]:
        return self._leaderboards.get(str(leaderboard_id))

    def save(self, leaderboard: Leaderboard) -> None:
        self._leaderboards[str(leaderboard.leaderboard_id)] = leaderboard


class InMemoryRatingRepository(RatingRepository):
    def __init__(self) -> None:
        self._ratings: List[PlayerRating] = []

    def save(self, player_rating: PlayerRating) -> None:
        self._ratings.append(player_rating)


class InMemoryPublicationRepository(PublicationRepository):
    def __init__(self) -> None:
        self._publications: List[Publication] = []

    def save(self, publication: Publication) -> None:
        self._publications.append(publication)


class InMemoryIdempotencyRepository(IdempotencyRepository):
    def __init__(self) -> None:
        self._processed: set[str] = set()

    def has_processed(self, command_id: str) -> bool:
        return command_id in self._processed

    def mark_processed(self, command_id: str) -> None:
        self._processed.add(command_id)


class InMemoryMatchStatsRepository(MatchStatsRepository):
    """FASE 21.B3 — dict-backed projection (tests / handlers)."""

    def __init__(self) -> None:
        self._player: Dict[str, Dict[str, PlayerStats]] = {}  # match -> player_id -> stats
        self._team: Dict[str, Dict[str, TeamStats]] = {}  # match -> team_id -> stats

    def save_player_stats(
        self, match_external_id: str, season_code: SeasonCode, player_stats: Iterable[PlayerStats]
    ) -> None:
        bucket = self._player.setdefault(match_external_id, {})
        for ps in player_stats:
            bucket[ps.player_external_id] = ps

    def save_team_stats(
        self, match_external_id: str, season_code: SeasonCode, team_stats: Iterable[TeamStats]
    ) -> None:
        bucket = self._team.setdefault(match_external_id, {})
        for ts in team_stats:
            bucket[ts.team_external_id] = ts

    def list_player_stats(self, match_external_id: str) -> Iterable[PlayerStats]:
        return list(self._player.get(match_external_id, {}).values())

    def list_team_stats(self, match_external_id: str) -> Iterable[TeamStats]:
        return list(self._team.get(match_external_id, {}).values())

    def list_player_stats_by_season(
        self, player_external_id: str, season_code: SeasonCode
    ) -> Iterable[PlayerStats]:
        result = []
        for bucket in self._player.values():
            if player_external_id in bucket:
                # InMemory mock: doesn't strictly filter by season_code, assumes test setup matches
                result.append(bucket[player_external_id])
        return result

    def list_season_player_aggregates(
        self, season_code: SeasonCode
    ) -> Iterable[SeasonPlayerStats]:
        from collections import defaultdict
        
        # grouping by player_external_id
        grouped = defaultdict(lambda: {
            "games_played": 0, "points": 0, "rebounds": 0, "assists": 0,
            "steals": 0, "blocks": 0, "turnovers": 0, "minutes": 0.0
        })
        
        # in memory doesn't track season_code per bucket natively, 
        # but player stats have it implicitly. We will just aggregate all.
        for bucket in self._player.values():
            for player_id, ps in bucket.items():
                aggr = grouped[player_id]
                aggr["games_played"] += 1
                aggr["points"] += ps.points
                aggr["rebounds"] += ps.rebounds
                aggr["assists"] += ps.assists
                aggr["steals"] += ps.steals
                aggr["blocks"] += ps.blocks
                aggr["turnovers"] += ps.turnovers
                aggr["minutes"] += ps.minutes
                
        result = []
        for pid in sorted(grouped.keys()):
            aggr = grouped[pid]
            result.append(SeasonPlayerStats(
                player_external_id=pid,
                season_code=str(season_code),
                games_played=aggr["games_played"],
                points=aggr["points"],
                rebounds=aggr["rebounds"],
                assists=aggr["assists"],
                steals=aggr["steals"],
                blocks=aggr["blocks"],
                turnovers=aggr["turnovers"],
                minutes=aggr["minutes"]
            ))
        return result
