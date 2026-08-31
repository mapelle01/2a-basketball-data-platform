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
    SeasonPlayerMetrics,
    SeasonPlayerStats,
    SeasonTeamLeaderboardEntry,
    SeasonTeamMetrics,
    SeasonTeamRoundStats,
    SeasonTeamStats,
    TeamStats,
)
from ...domain.statistics.metrics import compute_player_metrics, compute_team_metrics
from ...domain.statistics.ranking import rank_player_entries, rank_team_entries
from ...domain.team.model import Team
from ...domain.value_objects import CompetitionId, ExternalId, LeaderboardId, PlayerId, SeasonCode, TeamId


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

    def list_seasons(self):
        counts: Dict[str, int] = {}
        for match in self._matches.values():
            counts[str(match.season_code)] = counts.get(str(match.season_code), 0) + 1
        return sorted(counts.items(), key=lambda kv: kv[0], reverse=True)

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
        if round_number is not None and (round_number < 1 or round_number != int(round_number)):
            raise ValueError(f"round_number must be a positive integer, got {round_number!r}")
        query = external_id_query.lower() if external_id_query is not None else None
        matches = [
            match
            for match in self._matches.values()
            if str(match.season_code) == str(season_code)
            and (competition_id is None or str(match.competition_id) == str(competition_id))
            and (round_number is None or match.round_number == round_number)
            and (
                team_external_id is None
                or str(match.home_team_id) == team_external_id
                or str(match.away_team_id) == team_external_id
            )
            and (query is None or query in str(match.external_id).lower())
        ]
        matches.sort(key=lambda m: str(m.external_id))
        if limit is not None:
            matches = matches[:limit]
        return matches


class InMemoryPlayerRepository(PlayerRepository):
    def __init__(self) -> None:
        self._players: Dict[str, Player] = {}

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Player]:
        return self._players.get(str(external_id))

    def save(self, player: Player) -> None:
        self._players[str(player.external_id)] = player

    def search_by_name(self, name_query: str, limit: Optional[int] = None) -> Iterable[Player]:
        query = name_query.lower()
        results = [
            player
            for player in self._players.values()
            if player.name is not None and query in player.name.lower()
        ]
        results.sort(key=lambda p: str(p.external_id))
        if limit is not None:
            results = results[:limit]
        return results

    def upsert_catalog(self, external_id: ExternalId, player_id: PlayerId,
                       name: Optional[str], data: str) -> None:
        from json import loads as _loads
        from ...application.persistence.serialization import player_from_dict

        existing = self._players.get(str(external_id))
        if existing is not None:
            kept_name = existing.name if existing.name not in (None, "") else name
            self._players[str(external_id)] = Player(
                external_id=existing.external_id,
                player_id=existing.player_id,
                name=kept_name,
                birth_date=existing.birth_date,
                nationality=existing.nationality,
                position=existing.position,
                registrations=existing.registrations,
            )
            return
        self._players[str(external_id)] = player_from_dict(_loads(data))

    def get_many_by_external_ids(self, external_ids):
        return {pid: self._players.get(pid) for pid in external_ids}

    def upsert_catalog_many(self, entities):
        for external_id, player_id, name, data in entities:
            from feb_score.domain.value_objects import ExternalId as _ExtId, PlayerId as _Pid
            self.upsert_catalog(_ExtId(external_id), _Pid(player_id), name, data)


class InMemoryTeamRepository(TeamRepository):
    def __init__(self) -> None:
        self._teams: Dict[str, Team] = {}

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Team]:
        return self._teams.get(str(external_id))

    def save(self, team: Team) -> None:
        self._teams[str(team.external_id)] = team

    def search_by_name(self, name_query: str, limit: Optional[int] = None) -> Iterable[Team]:
        query = name_query.lower()
        results = [
            team
            for team in self._teams.values()
            if team.name is not None and query in team.name.lower()
        ]
        results.sort(key=lambda t: str(t.external_id))
        if limit is not None:
            results = results[:limit]
        return results

    def upsert_catalog(self, external_id: ExternalId, team_id: TeamId,
                       name: Optional[str], data: str) -> None:
        from json import loads as _loads
        from ...application.persistence.serialization import team_from_dict

        existing = self._teams.get(str(external_id))
        if existing is not None:
            kept_name = existing.name if existing.name not in (None, "") else name
            self._teams[str(external_id)] = Team(
                external_id=existing.external_id,
                team_id=existing.team_id,
                name=kept_name,
                registrations=existing.registrations,
            )
            return
        self._teams[str(external_id)] = team_from_dict(_loads(data))

    def get_many_by_external_ids(self, external_ids):
        return {tid: self._teams.get(tid) for tid in external_ids}

    def upsert_catalog_many(self, entities):
        for external_id, team_id, name, data in entities:
            from feb_score.domain.value_objects import ExternalId as _ExtId, TeamId as _Tid
            self.upsert_catalog(_ExtId(external_id), _Tid(team_id), name, data)


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
        # FASE 24.3 — round_number per match. Not part of the public projection
        # API: InMemory persists it when the caller provides it via
        # save_team_stats(..., round_number=...); SQL backends read it from the
        # owning match's data blob instead.
        self._round: Dict[str, int] = {}  # match -> round_number

    def save_player_stats(
        self, match_external_id: str, season_code: SeasonCode, player_stats: Iterable[PlayerStats]
    ) -> None:
        bucket = self._player.setdefault(match_external_id, {})
        self._player_season[match_external_id] = str(season_code)
        for ps in player_stats:
            bucket[ps.player_external_id] = ps

    def save_team_stats(
        self,
        match_external_id: str,
        season_code: SeasonCode,
        team_stats: Iterable[TeamStats],
        *,
        round_number: Optional[int] = None,
    ) -> None:
        bucket = self._team.setdefault(match_external_id, {})
        self._team_season[match_external_id] = str(season_code)
        if round_number is not None:
            self._round[match_external_id] = int(round_number)
        for ts in team_stats:
            bucket[ts.team_external_id] = ts

    def list_player_stats(self, match_external_id: str) -> Iterable[PlayerStats]:
        return list(self._player.get(match_external_id, {}).values())

    def list_team_stats(self, match_external_id: str) -> Iterable[TeamStats]:
        return list(self._team.get(match_external_id, {}).values())

    def list_season_player_teams(self, season_code: SeasonCode) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for match_id, bucket in self._player.items():
            if self._player_season.get(match_id) != str(season_code):
                continue
            for pid, ps in bucket.items():
                # first team wins, matching the SQL backends' ordering
                if pid not in out or ps.team_external_id < out[pid]:
                    out[pid] = ps.team_external_id
        return out

    def list_player_season_teams(
        self, player_external_id: str, season_code: SeasonCode
    ) -> Iterable[str]:
        team_ids = {
            ps.team_external_id
            for match_id, bucket in self._player.items()
            if self._player_season.get(match_id) == str(season_code)
            and player_external_id in bucket
            for ps in [bucket[player_external_id]]
        }
        return sorted(team_ids)

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

    def list_season_player_lines(self, season_code: SeasonCode) -> Iterable[PlayerStats]:
        out = []
        for match_id, bucket in self._player.items():
            if self._player_season.get(match_id) != str(season_code):
                continue
            out.extend(bucket.values())
        return out

    def list_season_player_aggregates(
        self, season_code: SeasonCode, limit: Optional[int] = None
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
        if limit is not None:
            result = result[:limit]
        return result

    def list_season_team_aggregates(
        self, season_code: SeasonCode, limit: Optional[int] = None
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
        if limit is not None:
            result = result[:limit]
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

    def list_season_player_metrics(
        self, season_code: SeasonCode, limit: Optional[int] = None
    ) -> List[SeasonPlayerMetrics]:
        return compute_player_metrics(self.list_season_player_aggregates(season_code, limit))

    def list_season_team_metrics(
        self, season_code: SeasonCode, limit: Optional[int] = None
    ) -> List[SeasonTeamMetrics]:
        return compute_team_metrics(self.list_season_team_aggregates(season_code, limit))

    def list_season_team_rounds(
        self, team_external_id: str, season_code: SeasonCode
    ) -> Iterable[SeasonTeamRoundStats]:
        """In-memory per-round aggregation for one team.

        Rounds are read from ``_round`` (populated when ``save_team_stats`` is
        called with ``round_number=...``); matches with no recorded round are
        excluded, mirroring the SQL backends' null-round filter.
        """
        from collections import defaultdict

        grouped: dict = defaultdict(lambda: {
            "games_played": 0, "wins": 0, "losses": 0,
            "points_for": 0, "points_against": 0,
        })

        for match_id, bucket in self._team.items():
            if self._team_season.get(match_id) != str(season_code):
                continue
            if team_external_id not in bucket:
                continue
            round_number = self._round.get(match_id)
            if round_number is None:
                continue
            ts = bucket[team_external_id]
            aggr = grouped[round_number]
            aggr["games_played"] += 1
            if ts.points_for > ts.points_against:
                aggr["wins"] += 1
            else:
                aggr["losses"] += 1
            aggr["points_for"] += ts.points_for
            aggr["points_against"] += ts.points_against

        result = []
        for rn in sorted(grouped.keys()):
            aggr = grouped[rn]
            result.append(SeasonTeamRoundStats(
                team_external_id=team_external_id,
                season_code=str(season_code),
                round_number=rn,
                games_played=aggr["games_played"],
                wins=aggr["wins"],
                losses=aggr["losses"],
                points_for=aggr["points_for"],
                points_against=aggr["points_against"],
                point_difference=aggr["points_for"] - aggr["points_against"],
            ))
        return result
