"""Official FEB/FIBA valuation, derived per game from the boxscore blob.

Derivable (not invented) because a per-game line carries shooting attempts.
The formula: (PTS+REB+AST+STL+BLK+faltas recibidas) − (TC fallados + TL
fallados + pérdidas + faltas). Blocks-against is omitted (not in the feed).
"""
from __future__ import annotations

from feb_score.domain.statistics.metrics import valoracion
from feb_score.domain.statistics.model import PlayerStats


def line(**kw):
    base = dict(player_external_id="p", team_external_id="t",
                points=0, rebounds=0, assists=0)
    base.update(kw)
    return PlayerStats(**base)


def test_standard_formula():
    # pos = 20+5+3+1+0+2 = 31 ; missed_fg = 15-8 = 7 ; missed_ft = 5-4 = 1
    # neg = 7+1+2+3 = 13 ; val = 18
    v = valoracion(line(points=20, rebounds=5, assists=3, steals=1, blocks=0,
                        turnovers=2, fouls=3, fouls_received=2,
                        field_goals_made=8, field_goals_attempted=15,
                        free_throws_made=4, free_throws_attempted=5))
    assert v == 18


def test_none_without_shooting_attempts():
    assert valoracion(line(points=20, rebounds=5, assists=3)) is None


def test_missing_free_throws_and_fouls_default_to_zero():
    # pos = 10 ; missed_fg = 2 ; val = 8
    assert valoracion(line(points=10, field_goals_made=4,
                           field_goals_attempted=6)) == 8


def test_a_bad_line_can_be_negative():
    v = valoracion(line(points=2, turnovers=5, fouls=4,
                        field_goals_made=1, field_goals_attempted=9))
    assert v < 0
