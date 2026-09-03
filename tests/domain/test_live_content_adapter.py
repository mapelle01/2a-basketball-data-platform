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

    def test_season_high_history_is_causal_not_whole_season(self):
        """Regression: the season-high history used to pull the WHOLE season,
        so generating round 1 crowned a game as the season max using games that
        had not been played yet. It must weigh only games up to the round\'s
        date. Found in production on jornada 1 (two spurious season highs)."""
        from datetime import datetime as _dt

        adapter, matches, stats, players, teams = _build_adapter()
        season = SeasonCode(SEASON)
        # p1 scores 22 (round 1), 30 (round 2), 18 (round 3), on separate dates.
        plan = {1: ("2026-01-04", 22), 2: ("2026-01-11", 30), 3: ("2026-01-18", 18)}
        for rnd, (day, pts) in plan.items():
            eid = f"D{rnd}"
            m = Match.create(
                external_id=ExternalId(eid), match_id=MatchId(str(uuid.uuid4())),
                competition_id=CompetitionId("2FEB"), season_code=season,
                round_number=rnd, home_team_id=ExternalId("tA"),
                away_team_id=ExternalId("tB"),
                scheduled_at=_dt.fromisoformat(day + "T18:00:00"), source={"origin": "t"},
            )
            m.finalize(score_summary=ScoreSummary(home_score=90, away_score=70,
                       periods=(PeriodScore(1, 45, 35), PeriodScore(2, 45, 35))),
                       home_team_stats=_team_stats("tA", 90, 70),
                       away_team_stats=_team_stats("tB", 70, 90))
            matches.save(m)
            stats.save_team_stats(eid, season,
                                  [_team_stats("tA", 90, 70), _team_stats("tB", 70, 90)],
                                  round_number=rnd)
            stats.save_player_stats(eid, season, [PlayerStats(
                player_external_id="p1", team_external_id="tA", points=pts,
                rebounds=5, assists=3, steals=1, blocks=0, turnovers=2, minutes=28.0,
                played_at=_dt.fromisoformat(day + "T18:00:00"))])

        # Round 1: history must be ONLY the round-1 game — no look-ahead.
        ctx1 = adapter.build_season_context(SEASON, 1, adapter.build_round_inputs(SEASON, 1))
        assert ctx1.player_history.get("p1") == (22,)

        # Round 2 (p1 scores 30, a candidate): history is causal up to round 2,
        # so it sees rounds 1 and 2 but NOT the later round-3 game.
        ctx2 = adapter.build_season_context(SEASON, 2, adapter.build_round_inputs(SEASON, 2))
        assert sorted(ctx2.player_history["p1"]) == [22, 30]

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

    def test_minutes_propagate_from_the_stats_view_to_the_season_line(self):
        """The season aggregate view already carried minutes; the adapter now
        forwards them so PlayerSeasonLine.minutes_per_game stops returning
        None. That is the one piece that unlocks the FEB Rating de temporada."""
        adapter, _matches, stats, players, teams = _build_adapter()
        players.save(_player("p1", "C. Sáez"))
        teams.save(_team("tA", "Alicante Basket"))
        stats.save_player_stats("m1", SeasonCode(SEASON), [
            PlayerStats("p1", "tA", points=28, rebounds=10, assists=5, minutes=32.0),
        ])
        stats.save_player_stats("m2", SeasonCode(SEASON), [
            PlayerStats("p1", "tA", points=22, rebounds=12, assists=4, minutes=30.0),
        ])
        agg = adapter.build_season_aggregate(SEASON)
        p1 = next(p for p in agg.players if p.player_external_id == "p1")
        assert p1.minutes == 62.0
        assert p1.minutes_per_game == 31.0


class TestGameLogEnrichment:
    """The per-game log now carries minutes and shooting alongside the base
    counters, so GameLine.rating can grade each game and the "récord de
    valoración de la temporada" detector has real data to rank."""

    def test_game_lines_carry_minutes_and_shooting_when_the_source_has_them(self):
        from datetime import datetime as _dt

        adapter, matches, stats, players, teams = _build_adapter()
        season = SeasonCode(SEASON)
        # Build the two matches with matching scheduled_at / played_at so the
        # causal cut in build_season_context (max scheduled_at of the round's
        # matches) keeps both rounds inside the log.
        def _match(eid, rnd, day):
            m = Match.create(
                external_id=ExternalId(eid), match_id=MatchId(str(uuid.uuid4())),
                competition_id=CompetitionId("2FEB"), season_code=season,
                round_number=rnd, home_team_id=ExternalId("tA"),
                away_team_id=ExternalId("tB"),
                scheduled_at=_dt.fromisoformat(day + "T18:00:00"),
                source={"origin": "t"},
            )
            m.finalize(score_summary=ScoreSummary(home_score=90, away_score=70,
                       periods=(PeriodScore(1, 45, 35), PeriodScore(2, 45, 35))),
                       home_team_stats=_team_stats("tA", 90, 70),
                       away_team_stats=_team_stats("tB", 70, 90))
            return m
        matches.save(_match("R1", 1, "2026-01-04"))
        matches.save(_match("R2", 2, "2026-01-11"))
        stats.save_team_stats("R1", season, [_team_stats("tA", 90, 70),
                              _team_stats("tB", 70, 90)], round_number=1)
        stats.save_team_stats("R2", season, [_team_stats("tA", 90, 70),
                              _team_stats("tB", 70, 90)], round_number=2)
        stats.save_player_stats("R1", season, [PlayerStats(
            "p1", "tA", points=22, rebounds=6, assists=4, steals=1, blocks=1,
            turnovers=2, minutes=28.0, field_goals_made=8, field_goals_attempted=15,
            played_at=_dt.fromisoformat("2026-01-04T18:00:00"))])
        stats.save_player_stats("R2", season, [PlayerStats(
            "p1", "tA", points=30, rebounds=8, assists=3, steals=2, blocks=0,
            turnovers=1, minutes=32.0, field_goals_made=11, field_goals_attempted=18,
            played_at=_dt.fromisoformat("2026-01-11T18:00:00"))])

        inputs = adapter.build_round_inputs(SEASON, 2)
        ctx = adapter.build_season_context(SEASON, 2, inputs)
        log = ctx.player_game_log["p1"]
        assert len(log) == 2
        # Latest game is the ROUND 2 line (log is ordered by played_at asc).
        latest = log[-1]
        assert latest.minutes == 32.0
        assert latest.field_goals_made == 11
        assert latest.field_goals_attempted == 18
        # And the enrichment lets the game rate itself.
        assert latest.rating is not None
        assert 0.0 <= latest.rating <= 10.0


class TestShootingFlowsThrough:
    """Per-player shooting reaches the content lane end to end: PlayerStats →
    adapter → PlayerLineInput → the (previously dormant) sharpshooter detector."""

    def test_shooting_reaches_player_lines_and_lights_the_detector(self):
        from feb_score.domain.content.insights import detect_sharpshooter

        adapter, matches, stats, players, _ = _build_adapter()
        matches.save(_finalized_match("m1", "979897", "983412", 88, 76))
        players.save(_player("shooter", "C. Sáez"))
        stats.save_player_stats("m1", SeasonCode(SEASON), [
            PlayerStats(
                player_external_id="shooter", team_external_id="979897",
                points=27, rebounds=3, assists=2, steals=1, blocks=0, turnovers=2, minutes=30.0,
                field_goals_made=10, field_goals_attempted=15,
                three_points_made=8, three_points_attempted=12,
                free_throws_made=1, free_throws_attempted=2, fouls=3, plus_minus=-4,
            ),
        ])
        inputs = adapter.build_round_inputs(SEASON, ROUND)
        line = next(p for p in inputs.player_lines if p.player_external_id == "shooter")
        assert line.has_shooting is True
        assert line.three_points_made == 8 and line.three_points_attempted == 12
        assert line.three_point_pct == round(100 * 8 / 12, 1)

        story = detect_sharpshooter(SEASON, ROUND, inputs.player_lines)
        assert story is not None
        assert story.facts["three_points_made"] == 8  # the lane is live on real data

    def test_no_shooting_keeps_detector_dormant(self):
        from feb_score.domain.content.insights import detect_sharpshooter

        adapter, matches, stats, players, _ = _build_adapter()
        matches.save(_finalized_match("m1", "979897", "983412", 88, 76))
        stats.save_player_stats("m1", SeasonCode(SEASON), [
            _player_stat("p", "979897", "m1", 30),  # no shooting fields
        ])
        inputs = adapter.build_round_inputs(SEASON, ROUND)
        assert all(not p.has_shooting for p in inputs.player_lines)
        assert detect_sharpshooter(SEASON, ROUND, inputs.player_lines) is None
