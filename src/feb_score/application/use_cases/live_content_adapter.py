"""Live Content Adapter — turns real platform reads into pipeline inputs.

Bridges the 2aFEB_SCORE data platform (repositories) and the Content Engine's
Insight inputs. Given a (season, round), it:

  1. finds the FINALIZED matches of that round (MatchRepository.search)
  2. reads each match's authoritative boxscore (MatchStatsRepository)
  3. resolves team + player display names from the catalog (batch reads)
  4. emits MatchFactsInput + PlayerLineInput sequences

Every value comes from a repository read. Nothing is invented: a match with
no score is skipped, a player/team with no catalog name gets ``None`` (the
templates fall back to the external_id, never a fabricated name).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from ..repositories.interfaces import (
    MatchRepository,
    MatchStatsRepository,
    PlayerRepository,
    TeamRepository,
)
from ...domain.content.bio import LeagueBio
from ...domain.content.insights import MatchFactsInput, PlayerLineInput
from ...domain.content.season_aggregate import PlayerSeasonLine, SeasonAggregate
from ...domain.content.season_insights import SEASON_HIGH_MIN_POINTS, SeasonContext
from ...domain.match.model import Match
from ...domain.statistics.model import TeamLeaderboardMetric
from ...domain.value_objects import MatchStatus, SeasonCode


@dataclass(frozen=True)
class RoundContentInputs:
    season_code: str
    round_number: int
    matches: Tuple[MatchFactsInput, ...]
    player_lines: Tuple[PlayerLineInput, ...]

    @property
    def is_empty(self) -> bool:
        return not self.matches


class LiveContentAdapter:
    def __init__(
        self,
        match_repo: MatchRepository,
        stats_repo: MatchStatsRepository,
        player_repo: PlayerRepository,
        team_repo: TeamRepository,
    ) -> None:
        self._matches = match_repo
        self._stats = stats_repo
        self._players = player_repo
        self._teams = team_repo

    def build_round_inputs(
        self, season_code: str, round_number: int
    ) -> RoundContentInputs:
        season = SeasonCode(season_code)
        raw_matches = list(
            self._matches.search(season, round_number=round_number)
        )
        finalized = [m for m in raw_matches if self._is_finalized(m)]

        team_names = self._resolve_team_names(finalized)
        match_inputs = tuple(
            self._to_match_input(m, team_names) for m in finalized
        )

        player_lines = self._build_player_lines(finalized, team_names)

        return RoundContentInputs(
            season_code=season_code,
            round_number=round_number,
            matches=match_inputs,
            player_lines=player_lines,
        )

    # ------------------------------------------------------------------
    # Season context (for the season detectors: highs, streaks, upsets)
    # ------------------------------------------------------------------

    def build_season_context(
        self, season_code: str, round_number: int, inputs: RoundContentInputs
    ) -> SeasonContext:
        season = SeasonCode(season_code)
        return SeasonContext(
            player_history=self._player_history(season, inputs.player_lines),
            team_results=self._team_results(season, inputs.matches),
            team_rank=self._team_rank(season),
        )

    # ------------------------------------------------------------------
    # Season aggregate (for the season-leader detectors)
    # ------------------------------------------------------------------

    def build_season_aggregate(self, season_code: str) -> SeasonAggregate:
        """Per-player season totals, read from the authoritative season
        aggregates projection. Player names, each player's season team, and the
        team names are all resolved from repositories; anything missing stays
        ``None`` (the card degrades gracefully — never an invented name).

        Team is resolved per player (a season is a weekly batch, so the per-player
        team lookup is acceptable; a batch player→team query is the optimization
        if it ever matters). A traded player is attributed to their first team.
        """
        season = SeasonCode(season_code)
        aggregates = list(self._stats.list_season_player_aggregates(season))
        names = self._resolve_player_names({a.player_external_id for a in aggregates})

        player_team: Dict[str, str] = {}
        for a in aggregates:
            teams = list(self._stats.list_player_season_teams(a.player_external_id, season))
            if teams:
                player_team[a.player_external_id] = teams[0]
        team_names = self._team_names_by_ids(set(player_team.values()))

        players = tuple(
            PlayerSeasonLine(
                player_external_id=a.player_external_id,
                games=a.games_played,
                points=a.points,
                rebounds=a.rebounds,
                assists=a.assists,
                steals=a.steals,
                blocks=a.blocks,
                turnovers=a.turnovers,
                player_name=names.get(a.player_external_id),
                team_external_id=player_team.get(a.player_external_id),
                team_name=team_names.get(player_team.get(a.player_external_id)),
            )
            for a in aggregates
        )
        return SeasonAggregate(season_code=season_code, players=players)

    # ------------------------------------------------------------------
    # Roster attributes (for the BIO detectors)
    # ------------------------------------------------------------------

    def build_league_bio(self, season_code: str) -> LeagueBio:
        """Nationality for every player with stats in the season.

        Season-wide by construction: "the only player from Benin" is a claim
        about the whole league, so a round-sized view would make it false.
        One catalog query, the same batch the name resolution already uses.

        The FEB writes a literal "-" where it has no value (measured: 21 of 120
        sampled players carry it as their POSITION), so placeholders are
        dropped rather than treated as a country of their own.
        """
        season = SeasonCode(season_code)
        ids = {
            a.player_external_id
            for a in self._stats.list_season_player_aggregates(season)
        }
        if not ids:
            return LeagueBio()
        catalog = self._players.get_many_by_external_ids(ids)
        return LeagueBio({
            pid: player.nationality.strip()
            for pid, player in catalog.items()
            if player is not None
            and player.nationality
            and player.nationality.strip() not in ("", "-")
        })

    def _team_names_by_ids(self, team_ids: set) -> Dict[str, Optional[str]]:
        if not team_ids:
            return {}
        catalog = self._teams.get_many_by_external_ids(team_ids)
        return {tid: (team.name if team is not None else None) for tid, team in catalog.items()}

    def _team_rank(self, season: SeasonCode) -> Dict[str, int]:
        try:
            entries = self._stats.list_season_team_leaderboard(
                season, TeamLeaderboardMetric.CLASSIFICATION
            )
        except ValueError:
            return {}
        return {e.team_external_id: e.rank for e in entries}

    def _team_results(
        self, season: SeasonCode, matches: Sequence[MatchFactsInput]
    ) -> Dict[str, Tuple[Tuple[int, bool], ...]]:
        team_ids = set()
        for m in matches:
            team_ids.add(m.home_team_external_id)
            team_ids.add(m.away_team_external_id)

        results: Dict[str, Tuple[Tuple[int, bool], ...]] = {}
        for tid in team_ids:
            rounds = sorted(
                self._stats.list_season_team_rounds(tid, season),
                key=lambda r: r.round_number,
            )
            seq = tuple(
                (r.round_number, r.wins > 0) for r in rounds if r.games_played > 0
            )
            if seq:
                results[tid] = seq
        return results

    def _player_history(
        self, season: SeasonCode, player_lines: Sequence[PlayerLineInput]
    ) -> Dict[str, Tuple[int, ...]]:
        # Only fetch history for players who scored enough this round to be a
        # season-high candidate — avoids a season query per benchwarmer.
        history: Dict[str, Tuple[int, ...]] = {}
        for p in player_lines:
            if p.points < SEASON_HIGH_MIN_POINTS or p.player_external_id in history:
                continue
            stats = self._stats.list_player_stats_by_season(
                p.player_external_id, season
            )
            points = tuple(s.points for s in stats)
            if points:
                history[p.player_external_id] = points
        return history

    # ------------------------------------------------------------------

    @staticmethod
    def _is_finalized(match: Match) -> bool:
        return match.status == MatchStatus("FINALIZED") and match.score_summary is not None

    def _resolve_team_names(self, matches: Sequence[Match]) -> Dict[str, Optional[str]]:
        team_ids = set()
        for m in matches:
            team_ids.add(str(m.home_team_id))
            team_ids.add(str(m.away_team_id))
        if not team_ids:
            return {}
        catalog = self._teams.get_many_by_external_ids(team_ids)
        return {
            tid: (team.name if team is not None else None)
            for tid, team in catalog.items()
        }

    def _to_match_input(
        self, match: Match, team_names: Dict[str, Optional[str]]
    ) -> MatchFactsInput:
        home_id = str(match.home_team_id)
        away_id = str(match.away_team_id)
        return MatchFactsInput(
            external_id=str(match.external_id),
            season_code=str(match.season_code),
            round_number=match.round_number,
            home_team_external_id=home_id,
            away_team_external_id=away_id,
            home_team_name=team_names.get(home_id),
            away_team_name=team_names.get(away_id),
            home_score=match.score_summary.home_score,
            away_score=match.score_summary.away_score,
            scheduled_at=match.scheduled_at,
        )

    def _build_player_lines(
        self, matches: Sequence[Match], team_names: Dict[str, Optional[str]]
    ) -> Tuple[PlayerLineInput, ...]:
        # Collect all player stats across the round, then resolve names in one
        # batch read (avoids one catalog lookup per player over a tunnel).
        raw: List[Tuple[str, object]] = []  # (match_external_id, PlayerStats)
        player_ids = set()
        for m in matches:
            mid = str(m.external_id)
            for ps in self._stats.list_player_stats(mid):
                raw.append((mid, ps))
                player_ids.add(ps.player_external_id)

        player_names = self._resolve_player_names(player_ids)

        lines = [
            PlayerLineInput(
                player_external_id=ps.player_external_id,
                player_name=player_names.get(ps.player_external_id),
                team_external_id=ps.team_external_id,
                team_name=team_names.get(ps.team_external_id),
                match_external_id=mid,
                points=ps.points,
                rebounds=ps.rebounds,
                assists=ps.assists,
                steals=ps.steals,
                blocks=ps.blocks,
                turnovers=ps.turnovers,
                minutes=ps.minutes,
                # Shooting/fouls flow through when present (public boxscore); the
                # shooting detectors self-skip while these are None.
                field_goals_made=ps.field_goals_made,
                field_goals_attempted=ps.field_goals_attempted,
                three_points_made=ps.three_points_made,
                three_points_attempted=ps.three_points_attempted,
                free_throws_made=ps.free_throws_made,
                free_throws_attempted=ps.free_throws_attempted,
                fouls=ps.fouls,
                fouls_received=ps.fouls_received,
            )
            for mid, ps in raw
        ]
        return tuple(lines)

    def _resolve_player_names(self, player_ids: set) -> Dict[str, Optional[str]]:
        if not player_ids:
            return {}
        catalog = self._players.get_many_by_external_ids(player_ids)
        return {
            pid: (player.name if player is not None else None)
            for pid, player in catalog.items()
        }
