"""ROUND RECAP, redefined — the round as a hierarchy of curated stories.

Not the old grab-bag of four random numbers: a dominant hero stat, the top
performance with its line, and a row of secondary tiles. Each piece is drawn
from a real detection and omitted when there is no story; fewer than three real
data points is not a recap.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from feb_score.domain.content.bio import LeagueBio
from feb_score.domain.content.copy import generate_copy
from feb_score.domain.content.insights import (
    MatchFactsInput,
    PlayerLineInput,
    detect_round_recap,
)
from feb_score.domain.content.season_insights import SeasonContext
from feb_score.domain.content.story import STORY_TO_TEMPLATE, StoryType
from feb_score.domain.content.validation import validate_copy
from feb_score.infrastructure.rendering.component_templates import render_template

D = datetime(2025, 3, 1, 18, 0)


def _match(eid, h, a, hs, as_, hn, an):
    return MatchFactsInput(eid, "2024-2025", 24, h, a, hn, an, hs, as_, D)


def _line(pid, name, team, tn, pts, reb=4, ast=2, fgm=8, fga=14):
    return PlayerLineInput(
        pid, name, team, tn, "m1", points=pts, rebounds=reb, assists=ast,
        steals=2, blocks=1, turnovers=2, minutes=32.0,
        field_goals_made=fgm, field_goals_attempted=fga, three_points_made=2,
        three_points_attempted=5, free_throws_made=4, free_throws_attempted=5,
        fouls=2, fouls_received=3,
    )


def _full_round():
    matches = [_match("m1", "tA", "tB", 100, 60, "Alicante", "Ourense"),
               _match("m2", "tC", "tD", 89, 84, "Zamora", "Salou")]
    lines = [
        _line("scorer", "GARCIA, LUCAS", "tA", "Alicante", 40, reb=3, ast=1, fgm=15, fga=28),
        _line("star", "SCHOTT, FYNN", "tC", "Zamora", 28, reb=12, ast=10, fgm=10, fga=15),
        _line("c", "LOPEZ, ANA", "tB", "Ourense", 15),
        _line("d", "RUIZ, PABLO", "tD", "Salou", 14),
    ]
    sc = SeasonContext(team_results={"tA": ((21, True), (22, True), (23, True), (24, True))})
    return matches, lines, sc


class TestAssembly:
    def test_builds_hero_top_and_tiles(self):
        matches, lines, sc = _full_round()
        s = detect_round_recap("2024-2025", 24, matches, lines, sc)
        assert s.facts["hero"]["value"] == "40" and s.facts["hero"]["unit"] == "PTS"
        assert s.facts["top"]["name"] == "FYNN SCHOTT"
        assert s.facts["top"]["rating"] is not None
        labels = [t["label"] for t in s.facts["tiles"]]
        assert "MAYOR DIFERENCIA" in labels and "RACHA" in labels and "MÁS ANOTADOR" in labels

    def test_hero_does_not_duplicate_top_performance(self):
        matches, lines, sc = _full_round()
        s = detect_round_recap("2024-2025", 24, matches, lines, sc)
        assert s.facts["hero"]["name"] != s.facts["top"]["name"]

    def test_hero_falls_back_to_margin_when_top_scorer_is_the_star(self):
        # one dominant all-rounder who is ALSO the top scorer → hero becomes the
        # biggest-win margin instead of repeating him
        matches = [_match("m1", "tA", "tB", 100, 60, "Alicante", "Ourense")]
        lines = [_line("star", "SCHOTT, FYNN", "tA", "Alicante", 40, reb=14, ast=11, fgm=15, fga=22),
                 _line("b", "OTRO", "tB", "Ourense", 12)]
        s = detect_round_recap("2024-2025", 24, matches, lines, None)
        assert s.facts["hero"]["value"].startswith("+")     # the margin, not a player

    def test_a_missing_story_is_omitted(self):
        matches, lines, _ = _full_round()
        s = detect_round_recap("2024-2025", 24, matches, lines, None)  # no streak
        assert "RACHA" not in [t["label"] for t in s.facts["tiles"]]

    def test_fewer_than_three_data_points_is_not_a_recap(self):
        matches = [_match("m1", "tA", "tB", 70, 68, "Alicante", "Ourense")]
        lines = [_line("a", "UNO", "tA", "Alicante", 11), _line("b", "DOS", "tB", "Ourense", 9)]
        assert detect_round_recap("2024-2025", 24, matches, lines, None) is None

    def test_no_matches_no_recap(self):
        assert detect_round_recap("2024-2025", 24, [], [], None) is None


class TestCopyAndCard:
    def test_caption_has_no_untraceable_numbers(self):
        matches, lines, sc = _full_round()
        s = detect_round_recap("2024-2025", 24, matches, lines, sc)
        c = generate_copy({"story_type": "round_recap", "round_number": 24, "facts": s.facts})
        assert validate_copy(c.to_dict(), {**s.facts, "round_number": 24}).ok
        assert c.headline == "La jornada en datos"

    def test_renders_the_hierarchy(self):
        assert STORY_TO_TEMPLATE[StoryType.ROUND_RECAP] == "round_recap"
        matches, lines, sc = _full_round()
        s = detect_round_recap("2024-2025", 24, matches, lines, sc)
        svg = render_template("round_recap", {
            "story": {"facts": s.facts, "round_number": 24, "season_code": "2024-2025",
                      "story_type": "round_recap"},
            "display": {}, "assets": {}, "copy": {}, "meta": {},
        })
        ET.fromstring(svg)
        assert "LA JORNADA" in svg and "EN DATOS" in svg
        for label in ("EL GRAN DATO", "MEJOR ACTUACIÓN", "MAYOR DIFERENCIA", "MÁS ANOTADOR"):
            assert label in svg
        assert "NOTA FEB" in svg
