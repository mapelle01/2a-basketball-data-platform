from datetime import datetime

import pytest

from feb_score.domain.content.model import (
    Channel,
    ContentPriority,
    ContentType,
    Highlight,
    HighlightType,
    MatchFacts,
    MatchResultContent,
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


def _player_line(**overrides):
    defaults = dict(
        player_external_id="player-1",
        team_external_id="team-a",
        points=20,
        rebounds=5,
        assists=3,
        steals=1,
        blocks=0,
        turnovers=2,
        minutes=25.0,
    )
    defaults.update(overrides)
    return PlayerLine(**defaults)


def _team_line(**overrides):
    defaults = dict(
        team_external_id="team-a",
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


class TestMatchFacts:
    def test_margin(self):
        f = _facts(home_score=85, away_score=72)
        assert f.margin == 13

    def test_winner_is_home(self):
        f = _facts(home_score=90, away_score=80)
        assert f.winner_id == "team-a"
        assert f.loser_id == "team-b"
        assert f.is_home_win is True

    def test_winner_is_away(self):
        f = _facts(home_score=70, away_score=80)
        assert f.winner_id == "team-b"
        assert f.loser_id == "team-a"
        assert f.is_home_win is False

    def test_total_points(self):
        f = _facts(home_score=90, away_score=85)
        assert f.total_points == 175


class TestPlayerLine:
    def test_pra(self):
        p = _player_line(points=25, rebounds=10, assists=7)
        assert p.pra == 42

    def test_impact(self):
        p = _player_line(
            points=20, rebounds=5, assists=3, steals=1, blocks=0, turnovers=2
        )
        expected = 20 + 5 * 1.2 + 3 * 1.5 + 1 * 2.0 + 0 * 1.5 - 2
        assert p.impact == expected


class TestTeamLine:
    def test_fg_pct(self):
        t = _team_line(field_goals_made=30, field_goals_attempted=60)
        assert t.fg_pct == pytest.approx(0.5)

    def test_fg_pct_zero_attempts(self):
        t = _team_line(field_goals_made=0, field_goals_attempted=0)
        assert t.fg_pct == 0.0

    def test_three_pct(self):
        t = _team_line(three_points_made=5, three_points_attempted=20)
        assert t.three_pct == pytest.approx(0.25)

    def test_ft_pct(self):
        t = _team_line(free_throws_made=15, free_throws_attempted=20)
        assert t.ft_pct == pytest.approx(0.75)


class TestMatchResultContent:
    def test_to_dict_structure(self):
        facts = _facts()
        home = _team_line(team_external_id="team-a")
        away = _team_line(team_external_id="team-b", points_for=75, points_against=82)
        players = (_player_line(),)
        highlights = (
            Highlight(
                highlight_type=HighlightType.TOP_SCORER,
                subject_id="player-1",
                subject_type="player",
                value=20.0,
                label="20 pts",
            ),
        )

        content = MatchResultContent(
            content_id="content-001",
            content_type=ContentType.MATCH_RESULT,
            priority=ContentPriority.NORMAL,
            generated_at=datetime(2026, 1, 16),
            facts=facts,
            home_team=home,
            away_team=away,
            player_lines=players,
            highlights=highlights,
            headline="Final: 82-75",
            subheadline="Top scorer: player-1 (20 pts)",
        )

        dto = content.to_dict()
        assert dto["content_id"] == "content-001"
        assert dto["content_type"] == "match_result"
        assert dto["priority"] == "normal"
        assert dto["headline"] == "Final: 82-75"
        assert dto["facts"]["home_score"] == 82
        assert dto["facts"]["away_score"] == 75
        assert dto["facts"]["margin"] == 7
        assert len(dto["highlights"]) == 1
        assert dto["highlights"][0]["type"] == "top_scorer"
        assert len(dto["top_performers"]) == 1
        assert "instagram_post" in dto["channels"]


class TestHighlight:
    def test_to_dict(self):
        h = Highlight(
            highlight_type=HighlightType.THIRTY_PLUS,
            subject_id="player-x",
            subject_type="player",
            value=35.0,
            label="35-point explosion",
        )
        d = h.to_dict()
        assert d["type"] == "thirty_plus"
        assert d["subject_id"] == "player-x"
        assert d["value"] == 35.0
