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
from ...domain.statistics.model import (
    PlayerStats,
    SeasonPlayerLeaderboardEntry,
    SeasonPlayerStats,
    SeasonTeamLeaderboardEntry,
    SeasonTeamStats,
    TeamStats,
)
from ...domain.statistics.ranking import rank_player_entries, rank_team_entries
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
        self._player_season: Dict[str, str] = {}  # match -> season_code
        self._team_season: Dict[str, str] = {}  # match -> season_code

    def save_player_stats(
        self, match_external_id: str, season_code: SeasonCode, player_stats: Iterable[PlayerStats]
    ) -> None:
        bucket = self._player.setdefault(match_external_id, {})
        self._player_season[match_external_id] = str(season_code)
        for ps in player_stats:
            bucket[ps.player_external_id] = ps

    def save_team_stats(
        self, match_external_id: str, season_code: SeasonCode, team_stats: Iterable[TeamStats]
    ) -> None:
        bucket = self._team.setdefault(match_external_id, {})
        self._team_season[match_external_id] = str(season_code)
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
        for match_id, bucket in self._player.items():
            if self._player_season.get(match_id) != str(season_code):
                continue
            if player_external_id in bucket:
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

        # only buckets belonging to the requested season
        for match_id, bucket in self._player.items():
            if self._player_season.get(match_id) != str(season_code):
                continue
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

    def list_season_team_aggregates(
        self, season_code: SeasonCode
    ) -> Iterable[SeasonTeamStats]:
        """In-memory aggregation over the team stats projection.

        Each bucket entry is keyed (match_external_id, team_external_id).
        wins/losses are derived per-match by comparing points_for vs points_against
        within the same match bucket.
        """
        from collections import defaultdict

        # grouped[team_id] accumulates running totals
        grouped: dict = defaultdict(lambda: {
            "games_played": 0, "wins": 0, "losses": 0,
            "points_for": 0, "points_against": 0,
            "field_goals_made": 0, "field_goals_attempted": 0,
            "three_points_made": 0, "three_points_attempted": 0,
            "free_throws_made": 0, "free_throws_attempted": 0,
            "turnovers": 0, "rebounds": 0,
        })

        for match_id, bucket in self._team.items():  # bucket: {team_id -> TeamStats}
            if self._team_season.get(match_id) != str(season_code):
                continue
            for team_id, ts in bucket.items():
                aggr = grouped[team_id]
                aggr["games_played"] += 1
                # win/loss derived from points_for vs points_against for this match
                if ts.points_for > ts.points_against:
                    aggr["wins"] += 1
                else:
                    aggr["losses"] += 1
                aggr["points_for"] += ts.points_for
                aggr["points_against"] += ts.points_against
                aggr["field_goals_made"] += ts.field_goals_made
                aggr["field_goals_attempted"] += ts.field_goals_attempted
                aggr["three_points_made"] += ts.three_points_made
                aggr["three_points_attempted"] += ts.three_points_attempted
                aggr["free_throws_made"] += ts.free_throws_made
                aggr["free_throws_attempted"] += ts.free_throws_attempted
                aggr["turnovers"] += ts.turnovers
                aggr["rebounds"] += ts.rebounds

        result = []
        for tid in sorted(grouped.keys()):
            aggr = grouped[tid]
            result.append(SeasonTeamStats(
                team_external_id=tid,
                season_code=str(season_code),
                games_played=aggr["games_played"],
                wins=aggr["wins"],
                losses=aggr["losses"],
                points_for=aggr["points_for"],
                points_against=aggr["points_against"],
                field_goals_made=aggr["field_goals_made"],
                field_goals_attempted=aggr["field_goals_attempted"],
                three_points_made=aggr["three_points_made"],
                three_points_attempted=aggr["three_points_attempted"],
                free_throws_made=aggr["free_throws_made"],
                free_throws_attempted=aggr["free_throws_attempted"],
                turnovers=aggr["turnovers"],
                rebounds=aggr["rebounds"],
            ))
        return result

    def list_season_player_leaderboard(
        self,
        season_code: SeasonCode,
        metric: str,
        limit: Optional[int] = None,
    ) -> List[SeasonPlayerLeaderboardEntry]:
        return rank_player_entries(
            self.list_season_player_aggregates(season_code), metric, limit
        )

    def list_season_team_leaderboard(
        self,
        season_code: SeasonCode,
        metric: str,
        limit: Optional[int] = None,
    ) -> List[SeasonTeamLeaderboardEntry]:
        return rank_team_entries(
            self.list_season_team_aggregates(season_code), metric, limit
        )
