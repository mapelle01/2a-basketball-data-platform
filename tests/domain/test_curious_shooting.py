"""Curious & shooting detectors — the insight-first content lane.

Curious detectors (iron man, playmaker) fire on the fields we ingest today.
Shooting detectors (sharpshooter, perfect night) are dormant until per-player
shooting is plumbed through — here we feed synthetic shooting to prove they
fire, and prove they self-skip when that data is absent. Every generated copy
must pass fact validation (no invented numbers).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from feb_score.domain.content.copy import generate_copy
from feb_score.domain.content.insights import (
    PlayerLineInput,
    detect_iron_man,
    detect_perfect_night,
    detect_playmaker,
    detect_sharpshooter,
)
from feb_score.domain.content.story import STORY_TO_TEMPLATE, StoryType
from feb_score.domain.content.validation import validate_copy
from feb_score.infrastructure.rendering.component_templates import render_template


def _line(pid="p", name="A. Uno", pts=10, reb=4, ast=3, mins=20.0, **shooting):
    return PlayerLineInput(
        player_external_id=pid, player_name=name, team_external_id="t", team_name="Team",
        match_external_id="m", points=pts, rebounds=reb, assists=ast, minutes=mins, **shooting,
    )


def _story_dict(s):
    return {"story_type": s.story_type.value, "round_number": s.round_number, "facts": s.facts}


def _assert_copy_valid(s):
    copy = generate_copy(_story_dict(s))
    # The pipeline validates against facts merged with round_number.
    validation_facts = {**s.facts, "round_number": s.round_number}
    result = validate_copy(copy.to_dict(), validation_facts)
    assert result.ok, result.hallucinated_numbers


class TestCuriousLive:
    def test_iron_man_fires_on_heavy_minutes(self):
        lines = [_line("a", mins=39.0, pts=12), _line("b", mins=22.0)]
        s = detect_iron_man("2025-2026", 5, lines)
        assert s is not None and s.story_type is StoryType.IRON_MAN
        assert s.facts["hero_label"] == "MIN" and s.facts["minutes_played"] == 39
        _assert_copy_valid(s)

    def test_iron_man_skips_without_minutes(self):
        # No minutes recorded (all 0) → no invented workhorse.
        assert detect_iron_man("2025-2026", 5, [_line("a", mins=0.0)]) is None

    def test_playmaker_fires_on_assist_night(self):
        lines = [_line("a", ast=11, pts=9), _line("b", ast=4)]
        s = detect_playmaker("2025-2026", 5, lines)
        assert s is not None and s.story_type is StoryType.TOP_ASSIST_PROVIDER
        assert s.facts["hero_value"] == 11 and s.facts["hero_label"] == "AST"
        _assert_copy_valid(s)

    def test_playmaker_skips_below_threshold(self):
        assert detect_playmaker("2025-2026", 5, [_line("a", ast=6)]) is None


class TestShootingDormantUntilData:
    def test_sharpshooter_skips_without_shooting_data(self):
        # Current production shape: no shooting fields → dormant.
        assert detect_sharpshooter("2025-2026", 5, [_line("a", pts=30)]) is None

    def test_sharpshooter_fires_with_shooting(self):
        lines = [
            _line("a", name="C. Sáez", pts=24,
                  three_points_made=7, three_points_attempted=11,
                  field_goals_made=9, field_goals_attempted=14),
            _line("b", pts=18, three_points_made=2, three_points_attempted=5,
                  field_goals_made=7, field_goals_attempted=12),
        ]
        s = detect_sharpshooter("2025-2026", 5, lines)
        assert s is not None and s.story_type is StoryType.SHARPSHOOTER
        assert s.facts["three_points_made"] == 7 and s.facts["hero_label"] == "TRIPLES"
        _assert_copy_valid(s)

    def test_perfect_night_skips_without_shooting_data(self):
        assert detect_perfect_night("2025-2026", 5, [_line("a", pts=20)]) is None

    def test_perfect_night_fires_on_flawless_field(self):
        lines = [
            _line("a", name="J. Nuñez", pts=16,
                  field_goals_made=7, field_goals_attempted=7),
            _line("b", pts=20, field_goals_made=8, field_goals_attempted=13),
        ]
        s = detect_perfect_night("2025-2026", 5, lines)
        assert s is not None and s.story_type is StoryType.PERFECT_NIGHT
        assert s.facts["field_goals_made"] == 7 and s.facts["field_goal_pct"] == 100.0
        _assert_copy_valid(s)

    def test_perfect_night_needs_volume(self):
        # 2/2 is not a "perfect night" — below the attempts floor.
        lines = [_line("a", field_goals_made=2, field_goals_attempted=2)]
        assert detect_perfect_night("2025-2026", 5, lines) is None


class TestRendering:
    def test_shooting_story_renders_through_player_card(self):
        s = detect_sharpshooter("2025-2026", 5, [
            _line("a", name="C. Sáez", pts=24, three_points_made=7,
                  three_points_attempted=11, field_goals_made=9, field_goals_attempted=14),
        ])
        assert STORY_TO_TEMPLATE[s.story_type] == "player_of_round"
        data = {"story": {"facts": s.facts, "round_number": 5, "season_code": "2025-2026"},
                "display": {"player": "C. Sáez", "team": "Alicante"},
                "assets": {"player_initials": "CS"}, "copy": {}, "meta": {}}
        svg = render_template("player_of_round", data)
        ET.fromstring(svg)
        assert "TRIPLES" in svg  # the hero label the detector chose
