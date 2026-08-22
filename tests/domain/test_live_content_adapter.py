"""LiveContentAdapter — turns real repository reads into pipeline inputs.

Uses the in-memory repositories (same contract as the SQL backends) to verify
the adapter: FINALIZED-only filtering, name resolution from the catalog, and
correct DTO shaping. No invention when data is missing.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from feb_score.application.repositories.in_memory import (
    InMemoryMatchRepository,
    InMemoryMatchStatsRepository,
    InMemoryPlayerRepository,
    InMemoryTeamRepository,
)
from feb_score.application.use_cases.live_content_adapter import LiveContentAdapter
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    CompetitionId,
    ExternalId,
    MatchId,
    PeriodScore,
    PlayerId,
    ScoreSummary,
    SeasonCode,
    TeamId,
)


def _team(external_id, name):
    return Team(external_id=ExternalId(external_id), team_id=TeamId(str(uuid.uuid4())), name=name)


def _player(external_id, name):
    return Player(external_id=ExternalId(external_id), player_id=PlayerId(str(uuid.uuid4())), name=name)


SEASON = "2025-2026"
ROUND = 7


def _finalized_match(external_id, home_team, away_team, home_score, away_score, round_number=ROUND):
    match = Match.create(
        external_id=ExternalId(external_id),
        match_id=MatchId(str(uuid.uuid4())),
        competition_id=CompetitionId("2FEB"),
        season_code=SeasonCode(SEASON),
        round_number=round_number,
        home_team_id=ExternalId(home_team),
        away_team_id=ExternalId(away_team),
        scheduled_at=datetime(2026, 1, 10, 18, 0),
        source={"origin": "test"},
    )
    match.finalize(
        score_summary=ScoreSummary(
            home_score=home_score,
            away_score=away_score,
            periods=(
                PeriodScore(1, home_score // 2, away_score // 2),
                PeriodScore(2, home_score - home_score // 2, away_score - away_score // 2),
            ),
        ),
        home_team_stats=_team_stats(home_team, home_score, away_score),
        away_team_stats=_team_stats(away_team, away_score, home_score),
    )
    return match


def _scheduled_match(external_id, home_team, away_team, round_number=ROUND):
    return Match.create(
        external_id=ExternalId(external_id),
        match_id=MatchId(str(uuid.uuid4())),
        competition_id=CompetitionId("2FEB"),
        season_code=SeasonCode(SEASON),
        round_number=round_number,
        home_team_id=ExternalId(home_team),
        away_team_id=ExternalId(away_team),
        scheduled_at=datetime(2026, 1, 10, 18, 0),
        source={"origin": "test"},
    )


def _team_stats(team, pf, pa):
    return TeamStats(
        team_external_id=team, points_for=pf, points_against=pa,
        field_goals_made=30, field_goals_attempted=60, three_points_made=8,
        three_points_attempted=22, free_throws_made=12, free_throws_attempted=16,
        turnovers=11, rebounds=35,
    )


def _player_stat(pid, team, match, points, rebounds=5, assists=3):
    return PlayerStats(
        player_external_id=pid, team_external_id=team, points=points,
        rebounds=rebounds, assists=assists, steals=1, blocks=0, turnovers=2,
        minutes=28.0, played_at=datetime(2026, 1, 10, 18, 0),
    )


def _build_adapter():
    match_repo = InMemoryMatchRepository()
    stats_repo = InMemoryMatchStatsRepository()
    player_repo = InMemoryPlayerRepository()
    team_repo = InMemoryTeamRepository()
    return (
        LiveContentAdapter(match_repo, stats_repo, player_repo, team_repo),
        match_repo,
        stats_repo,
        player_repo,
        team_repo,
    )


class TestFinalizedFiltering:
    def test_only_finalized_matches_are_included(self):
        adapter, matches, stats, _, _ = _build_adapter()
        matches.save(_finalized_match("m1", "tA", "tB", 80, 70))
        matches.save(_scheduled_match("m2", "tC", "tD"))

        inputs = adapter.build_round_inputs(SEASON, ROUND)
        ids = {m.external_id for m in inputs.matches}
        assert ids == {"m1"}

    def test_empty_round_yields_no_inputs(self):
        adapter, *_ = _build_adapter()
        inputs = adapter.build_round_inputs(SEASON, 99)
        assert inputs.is_empty
        assert inputs.matches == ()
        assert inputs.player_lines == ()


class TestNameResolution:
    def test_team_names_resolved_from_catalog(self):
        adapter, matches, stats, players, teams = _build_adapter()
        matches.save(_finalized_match("m1", "979897", "983412", 88, 76))
        teams.save(_team("979897", "Basket Navarra"))
        teams.save(_team("983412", "CB Prat"))

        inputs = adapter.build_round_inputs(SEASON, ROUND)
        m = inputs.matches[0]
        assert m.home_team_name == "Basket Navarra"
        assert m.away_team_name == "CB Prat"

    def test_missing_team_name_is_none_not_invented(self):
        adapter, matches, stats, players, teams = _build_adapter()
        matches.save(_finalized_match("m1", "979897", "983412", 88, 76))
        # No catalog entries saved.

        inputs = adapter.build_round_inputs(SEASON, ROUND)
        m = inputs.matches[0]
        assert m.home_team_name is None
        assert m.away_team_name is None

    def test_player_names_resolved_from_catalog(self):
        adapter, matches, stats, players, teams = _build_adapter()
        matches.save(_finalized_match("m1", "979897", "983412", 88, 76))
        stats.save_player_stats("m1", SeasonCode(SEASON), [
            _player_stat("2772828", "979897", "m1", 27),
        ])
        teams.save(_team("979897", "Basket Navarra"))
        players.save(_player("2772828", "F. Andrade Amiel"))

        inputs = adapter.build_round_inputs(SEASON, ROUND)
        assert len(inputs.player_lines) == 1
        assert inputs.player_lines[0].player_name == "F. Andrade Amiel"
        assert inputs.player_lines[0].team_name == "Basket Navarra" or inputs.player_lines[0].team_name is None


class TestPlayerLineShaping:
    def test_player_stats_become_lines_with_correct_numbers(self):
        adapter, matches, stats, players, teams = _build_adapter()
        matches.save(_finalized_match("m1", "tA", "tB", 88, 76))
        stats.save_player_stats("m1", SeasonCode(SEASON), [
            _player_stat("p1", "tA", "m1", 27, rebounds=8, assists=6),
            _player_stat("p2", "tB", "m1", 15, rebounds=4, assists=2),
        ])

        inputs = adapter.build_round_inputs(SEASON, ROUND)
        lines = {l.player_external_id: l for l in inputs.player_lines}
        assert lines["p1"].points == 27
        assert lines["p1"].rebounds == 8
        assert lines["p1"].assists == 6
        assert lines["p2"].points == 15


class TestSeasonContext:
    def _seed_multi_round(self, adapter, matches, stats):
        # tA beats tB across rounds 9-12; p1 (on tA) scores 18,20,22,35.
        pts = {9: 18, 10: 20, 11: 22, 12: 35}
        season = SeasonCode(SEASON)
        for rnd in (9, 10, 11, 12):
            eid = f"R{rnd}"
            matches.save(_finalized_match(eid, "tA", "tB", 90, 70, round_number=rnd))
            stats.save_team_stats(
                eid, season,
                [_team_stats("tA", 90, 70), _team_stats("tB", 70, 90)],
                round_number=rnd,
            )
            stats.save_player_stats(eid, season, [_player_stat("p1", "tA", eid, pts[rnd])])

    def test_context_has_history_results_and_rank(self):
        adapter, matches, stats, players, teams = _build_adapter()
        self._seed_multi_round(adapter, matches, stats)

        inputs = adapter.build_round_inputs(SEASON, 12)
        ctx = adapter.build_season_context(SEASON, 12, inputs)

        # player_history: p1 scored 35 this round (>=20 threshold) → history fetched
        assert "p1" in ctx.player_history
        assert 35 in ctx.player_history["p1"]
        assert max(ctx.player_history["p1"]) == 35

        # team_results: tA won all 4 rounds
        assert ctx.team_results["tA"] == ((9, True), (10, True), (11, True), (12, True))
        assert ctx.team_results["tB"] == ((9, False), (10, False), (11, False), (12, False))

        # team_rank: tA ranks above tB (classification)
        assert ctx.team_rank["tA"] < ctx.team_rank["tB"]

    def test_low_scorers_excluded_from_history(self):
        adapter, matches, stats, players, teams = _build_adapter()
        matches.save(_finalized_match("m1", "tA", "tB", 88, 76, round_number=12))
        stats.save_team_stats("m1", SeasonCode(SEASON),
                              [_team_stats("tA", 88, 76), _team_stats("tB", 76, 88)], round_number=12)
        stats.save_player_stats("m1", SeasonCode(SEASON), [_player_stat("p1", "tA", "m1", 8)])

        inputs = adapter.build_round_inputs(SEASON, 12)
        ctx = adapter.build_season_context(SEASON, 12, inputs)
        # p1 scored only 8 → not a season-high candidate → no history query
        assert "p1" not in ctx.player_history


class TestSeasonAggregate:
    def test_build_season_aggregate_folds_and_resolves_names_and_team(self):
        adapter, _matches, stats, players, teams = _build_adapter()
        players.save(_player("p1", "C. Sáez"))
        teams.save(_team("tA", "Alicante Basket"))
        # p1 plays two games, p2 one — season totals fold across matches.
        stats.save_player_stats("m1", SeasonCode(SEASON), [
            PlayerStats("p1", "tA", points=28, rebounds=10, assists=5),
            PlayerStats("p2", "tB", points=12, rebounds=8, assists=2),
        ])
        stats.save_player_stats("m2", SeasonCode(SEASON), [
            PlayerStats("p1", "tA", points=22, rebounds=12, assists=4),
        ])
        agg = adapter.build_season_aggregate(SEASON)
        p1 = next(p for p in agg.players if p.player_external_id == "p1")
        assert p1.games == 2 and p1.points == 50 and p1.rebounds == 22
        assert p1.player_name == "C. Sáez"          # resolved from catalog
        assert p1.team_external_id == "tA"           # team resolved from stats
        assert p1.team_name == "Alicante Basket"     # team name from catalog
        p2 = next(p for p in agg.players if p.player_external_id == "p2")
        assert p2.player_name is None                # no catalog record → None, not invented
        assert p2.team_external_id == "tB"           # team id resolved
        assert p2.team_name is None                  # team not in catalog → None, not invented
