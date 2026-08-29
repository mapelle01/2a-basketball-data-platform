"""ROUND RECAP, redefined — the round in up to five curated stories.

Not the old grab-bag of four numbers: one slot per role (hero stat, top
performance, team story, trend, fun fact), each drawn from a real detection,
and the rule — a slot with no story does not appear. Fewer than three real
stories is not a recap.
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
    matches = [_match("m1", "tA", "tB", 100, 60, "Alicante", "CB Prat"),
               _match("m2", "tC", "tD", 88, 84, "Fibwi", "Salou")]
    lines = [
        _line("scorer", "GARCIA, LUCAS", "tA", "Alicante", 40, reb=3, ast=1, fgm=15, fga=28),
        _line("star", "SCHOTT, FYNN", "tA", "Alicante", 28, reb=12, ast=10, fgm=10, fga=15),
        _line("kid", "MITEO, MERVEDI", "tC", "Fibwi", 18, fgm=7, fga=12),
        _line("c", "LOPEZ, ANA", "tB", "CB Prat", 15),
        _line("d", "RUIZ, PABLO", "tD", "Salou", 14),
    ]
    sc = SeasonContext(team_results={"tA": ((21, True), (22, True), (23, True), (24, True))})
    bio = LeagueBio(birth_by_player={"kid": "2008-09-01"},
                    nationality_by_player={"kid": "BENIN"})
    return matches, lines, sc, bio


class TestAssembly:
    def test_fills_the_five_roles_from_real_detections(self):
        matches, lines, sc, bio = _full_round()
        s = detect_round_recap("2024-2025", 24, matches, lines, sc, bio)
        roles = [sl["role"] for sl in s.facts["slots"]]
        assert roles == ["hero_stat", "top_performance", "team_story", "trend", "fun_fact"]
        assert len(s.facts["slots"]) <= 5

    def test_hero_stat_does_not_duplicate_top_performance(self):
        matches, lines, sc, bio = _full_round()
        s = detect_round_recap("2024-2025", 24, matches, lines, sc, bio)
        hero = next(sl for sl in s.facts["slots"] if sl["role"] == "hero_stat")
        top = next(sl for sl in s.facts["slots"] if sl["role"] == "top_performance")
        assert hero["subject"] != top["subject"]

    def test_a_slot_with_no_story_is_omitted(self):
        # no season context and no bio → no trend, no fun fact
        matches, lines, _, _ = _full_round()
        s = detect_round_recap("2024-2025", 24, matches, lines, None, None)
        roles = {sl["role"] for sl in s.facts["slots"]}
        assert "trend" not in roles and "fun_fact" not in roles
        assert "top_performance" in roles       # the ones that had a story remain

    def test_fewer_than_three_stories_is_not_a_recap(self):
        # a single low-scoring game: player-of-round only, no blowout/streak/curioso
        matches = [_match("m1", "tA", "tB", 70, 68, "Alicante", "CB Prat")]
        lines = [_line("a", "UNO", "tA", "Alicante", 11),
                 _line("b", "DOS", "tB", "CB Prat", 9)]
        assert detect_round_recap("2024-2025", 24, matches, lines, None, None) is None

    def test_no_matches_no_recap(self):
        assert detect_round_recap("2024-2025", 24, [], [], None, None) is None


class TestCopyAndCard:
    def test_caption_has_no_untraceable_numbers(self):
        matches, lines, sc, bio = _full_round()
        s = detect_round_recap("2024-2025", 24, matches, lines, sc, bio)
        c = generate_copy({"story_type": "round_recap", "round_number": 24, "facts": s.facts})
        assert validate_copy(c.to_dict(), {**s.facts, "round_number": 24}).ok
        assert c.headline == "Resumen de la jornada"

    def test_renders_one_block_per_role(self):
        assert STORY_TO_TEMPLATE[StoryType.ROUND_RECAP] == "round_recap"
        matches, lines, sc, bio = _full_round()
        s = detect_round_recap("2024-2025", 24, matches, lines, sc, bio)
        svg = render_template("round_recap", {
            "story": {"facts": s.facts, "round_number": 24, "season_code": "2024-2025",
                      "story_type": "round_recap"},
            "display": {}, "assets": {}, "copy": {}, "meta": {},
        })
        ET.fromstring(svg)
        assert "Resumen de la jornada" in svg
        for label in ("EL GRAN DATO", "MEJOR ACTUACIÓN", "HISTORIA DE EQUIPO",
                      "LA RACHA", "DATO CURIOSO"):
            assert label in svg
