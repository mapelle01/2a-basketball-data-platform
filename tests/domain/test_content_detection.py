from datetime import datetime

import pytest

from feb_score.domain.content.detection import (
    compute_priority,
    detect_match_highlights,
    generate_headline,
    generate_subheadline,
)
from feb_score.domain.content.model import (
    ContentPriority,
    HighlightType,
    MatchFacts,
    PlayerLine,
    TeamLine,
)


def _facts(**overrides):
    defaults = dict(
        match_external_id="match-001",
        season_code="2025-2026",
        round_number=10,
        scheduled_at=datetime(2026, 1, 15, 20, 0),
        home_team_id="team-a",
        away_team_id="team-b",
        home_score=82,
        away_score=75,
    )
    defaults.update(overrides)
    return MatchFacts(**defaults)


def _team_line(team_id="team-a", **overrides):
    defaults = dict(
        team_external_id=team_id,
        points_for=82,
        points_against=75,
        field_goals_made=30,
        field_goals_attempted=65,
        three_points_made=8,
        three_points_attempted=22,
        free_throws_made=14,
        free_throws_attempted=18,
        turnovers=12,
        rebounds=35,
    )
    defaults.update(overrides)
    return TeamLine(**defaults)


def _player(pid="player-1", team="team-a", **overrides):
    defaults = dict(
        player_external_id=pid,
        team_external_id=team,
        points=15,
        rebounds=4,
        assists=3,
        steals=1,
        blocks=0,
        turnovers=2,
        minutes=25.0,
    )
    defaults.update(overrides)
    return PlayerLine(**defaults)


class TestGameCharacterDetection:
    def test_close_game(self):
        facts = _facts(home_score=78, away_score=75)
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.CLOSE_GAME in types

    def test_blowout(self):
        facts = _facts(home_score=100, away_score=72)
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.BLOWOUT in types

    def test_high_scoring(self):
        facts = _facts(home_score=95, away_score=88)
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.HIGH_SCORING in types

    def test_low_scoring(self):
        facts = _facts(home_score=55, away_score=58)
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.LOW_SCORING in types

    def test_overtime(self):
        facts = _facts(
            home_score=95,
            away_score=90,
            periods=((20, 22), (25, 18), (18, 20), (17, 20), (15, 10)),
        )
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.OVERTIME in types

    def test_normal_game_no_special_character(self):
        facts = _facts(home_score=82, away_score=75)
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        game_types = {
            h.highlight_type
            for h in highlights
            if h.highlight_type
            in {
                HighlightType.CLOSE_GAME,
                HighlightType.BLOWOUT,
                HighlightType.HIGH_SCORING,
                HighlightType.LOW_SCORING,
                HighlightType.OVERTIME,
            }
        }
        assert len(game_types) == 0


class TestPlayerPerformanceDetection:
    def test_top_scorer(self):
        players = (
            _player("p1", points=25),
            _player("p2", points=12),
        )
        facts = _facts()
        highlights = detect_match_highlights(
            facts, players, _team_line(), _team_line("team-b")
        )
        top = [h for h in highlights if h.highlight_type == HighlightType.TOP_SCORER]
        assert len(top) == 1
        assert top[0].subject_id == "p1"
        assert top[0].value == 25.0

    def test_thirty_plus(self):
        players = (_player("p1", points=35),)
        highlights = detect_match_highlights(
            _facts(), players, _team_line(), _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.THIRTY_PLUS in types

    def test_twenty_plus(self):
        players = (_player("p1", points=24),)
        highlights = detect_match_highlights(
            _facts(), players, _team_line(), _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.TWENTY_PLUS in types
        assert HighlightType.THIRTY_PLUS not in types

    def test_double_double(self):
        players = (_player("p1", points=18, rebounds=12),)
        highlights = detect_match_highlights(
            _facts(), players, _team_line(), _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.DOUBLE_DOUBLE in types

    def test_triple_double(self):
        players = (_player("p1", points=15, rebounds=11, assists=10),)
        highlights = detect_match_highlights(
            _facts(), players, _team_line(), _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.TRIPLE_DOUBLE in types
        assert HighlightType.DOUBLE_DOUBLE not in types

    def test_block_party(self):
        players = (_player("p1", blocks=5),)
        highlights = detect_match_highlights(
            _facts(), players, _team_line(), _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.BLOCK_PARTY in types

    def test_assist_leader(self):
        players = (_player("p1", assists=9),)
        highlights = detect_match_highlights(
            _facts(), players, _team_line(), _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.ASSIST_LEADER in types

    def test_rebound_king(self):
        players = (_player("p1", rebounds=14),)
        highlights = detect_match_highlights(
            _facts(), players, _team_line(), _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.REBOUND_KING in types


class TestTeamShootingDetection:
    def test_shooting_display(self):
        home = _team_line(field_goals_made=28, field_goals_attempted=45)
        highlights = detect_match_highlights(
            _facts(), (), home, _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.SHOOTING_DISPLAY in types

    def test_no_shooting_display_low_attempts(self):
        home = _team_line(field_goals_made=20, field_goals_attempted=30)
        highlights = detect_match_highlights(
            _facts(), (), home, _team_line("team-b")
        )
        types = {h.highlight_type for h in highlights}
        assert HighlightType.SHOOTING_DISPLAY not in types


class TestPriority:
    def test_triple_double_is_urgent(self):
        facts = _facts()
        players = (_player("p1", points=15, rebounds=11, assists=10),)
        highlights = detect_match_highlights(
            facts, players, _team_line(), _team_line("team-b")
        )
        assert compute_priority(facts, highlights) == ContentPriority.URGENT

    def test_overtime_is_urgent(self):
        facts = _facts(
            periods=((20, 22), (25, 18), (18, 20), (17, 20), (15, 10)),
            home_score=95,
            away_score=90,
        )
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        assert compute_priority(facts, highlights) == ContentPriority.URGENT

    def test_close_game_is_high(self):
        facts = _facts(home_score=78, away_score=76)
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        assert compute_priority(facts, highlights) == ContentPriority.HIGH

    def test_thirty_plus_is_high(self):
        facts = _facts()
        players = (_player("p1", points=32),)
        highlights = detect_match_highlights(
            facts, players, _team_line(), _team_line("team-b")
        )
        assert compute_priority(facts, highlights) == ContentPriority.HIGH

    def test_normal_game_is_low(self):
        facts = _facts()
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        assert compute_priority(facts, highlights) == ContentPriority.LOW


class TestHeadlineGeneration:
    def test_overtime_headline(self):
        facts = _facts(
            home_score=95,
            away_score=90,
            periods=((20, 22), (25, 18), (18, 20), (17, 20), (15, 10)),
        )
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        headline = generate_headline(facts, highlights)
        assert "95-90" in headline
        assert "vertime" in headline

    def test_close_game_headline(self):
        facts = _facts(home_score=78, away_score=76)
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        headline = generate_headline(facts, highlights)
        assert "78-76" in headline

    def test_blowout_headline(self):
        facts = _facts(home_score=100, away_score=70)
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        headline = generate_headline(facts, highlights)
        assert "100-70" in headline
        assert "ominant" in headline

    def test_normal_headline(self):
        facts = _facts(home_score=82, away_score=75)
        highlights = detect_match_highlights(
            facts, (), _team_line(), _team_line("team-b")
        )
        headline = generate_headline(facts, highlights)
        assert "82-75" in headline


class TestSubheadlineGeneration:
    def test_special_performance_leads(self):
        facts = _facts()
        players = (_player("p1", points=35),)
        highlights = detect_match_highlights(
            facts, players, _team_line(), _team_line("team-b")
        )
        sub = generate_subheadline(facts, highlights, players)
        assert "p1" in sub

    def test_top_scorer_fallback(self):
        facts = _facts()
        players = (_player("p1", points=18), _player("p2", points=12))
        highlights = detect_match_highlights(
            facts, players, _team_line(), _team_line("team-b")
        )
        sub = generate_subheadline(facts, highlights, players)
        assert "p1" in sub
        assert "18" in sub

    def test_no_players_fallback(self):
        facts = _facts(round_number=15)
        highlights = []
        sub = generate_subheadline(facts, highlights, ())
        assert "15" in sub
