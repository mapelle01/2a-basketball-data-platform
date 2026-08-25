"""The defensive lane — steals + blocks.

Defence barely registers in a boxscore, so without a card of its own it never
gets told: a five-block night on five points loses every ranking to the
scorers. These tests hold the threshold honest (it was measured, not guessed),
the arithmetic visible, and the Spanish grammatical.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from feb_score.domain.content.copy import generate_copy
from feb_score.domain.content.insights import (
    DEFENSIVE_MIN_ACTIONS,
    PlayerLineInput,
    detect_defensive_anchor,
)
from feb_score.domain.content.registry import DetectionContext, Scope, run_detectors
from feb_score.domain.content.story import STORY_TO_TEMPLATE, StoryType, labels_for
from feb_score.domain.content.validation import validate_copy
from feb_score.infrastructure.rendering.component_templates import render_template


def _line(pid, *, steals=0, blocks=0, points=10, name=None, minutes=25.0):
    return PlayerLineInput(
        pid, name or pid.upper(), "t1", "Equipo", "m1",
        points=points, rebounds=4, assists=2, steals=steals, blocks=blocks,
        turnovers=1, minutes=minutes,
        field_goals_made=4, field_goals_attempted=9, three_points_made=1,
        three_points_attempted=3, free_throws_made=1, free_throws_attempted=2,
        fouls=2, fouls_received=3,
    )


class TestDetection:
    def test_an_ordinary_defensive_night_is_not_a_story(self):
        """Measured over 2,607 real lines: the median is 1 and the 95th
        percentile is 3, so anything under the threshold is a normal Sunday."""
        assert DEFENSIVE_MIN_ACTIONS == 5
        lines = [_line("a", steals=2, blocks=1), _line("b", steals=1, blocks=2)]
        assert detect_defensive_anchor("2024-2025", 24, lines) is None

    def test_fires_on_a_real_defensive_night(self):
        lines = [_line("a", steals=1, blocks=5, points=5), _line("b", steals=2, blocks=0)]
        story = detect_defensive_anchor("2024-2025", 24, lines)
        assert story is not None
        assert story.story_type is StoryType.DEFENSIVE_ANCHOR
        assert story.facts["player_external_id"] == "a"

    def test_the_scorer_does_not_win_a_defensive_card(self):
        """The whole point of the lane: the best defensive line wins even when
        someone else scored three times as much."""
        story = detect_defensive_anchor("2024-2025", 24, [
            _line("stopper", steals=4, blocks=3, points=6),
            _line("scorer", steals=2, blocks=1, points=34),
        ])
        assert story.facts["player_external_id"] == "stopper"

    def test_shows_the_parts_of_the_sum(self):
        """The hero number is derived, so the components sit beside it — a
        reader can check the arithmetic instead of taking it on trust."""
        s = detect_defensive_anchor("2024-2025", 24, [_line("a", steals=3, blocks=3)])
        assert s.facts["defensive_actions"] == 6
        assert s.facts["hero_value"] == 6
        assert s.facts["secondary"] == [[3, "ROB"], [3, "TAP"]]
        assert s.facts["steals"] == 3 and s.facts["blocks"] == 3

    def test_carries_the_rating_like_every_player_card(self):
        s = detect_defensive_anchor("2024-2025", 24, [_line("a", steals=3, blocks=3)])
        assert s.facts["rating"] is not None

    def test_traces_to_the_boxscore(self):
        s = detect_defensive_anchor("2024-2025", 24, [_line("a", steals=5, blocks=1)])
        assert s.source_refs["player_stats"].startswith("2afeb_score://match_player_stats/")

    def test_runs_through_the_registry(self):
        ctx = DetectionContext(
            "2024-2025", 24, player_lines=(_line("a", steals=4, blocks=2),)
        )
        types = {s.story_type for s in run_detectors(ctx, {Scope.ROUND})}
        assert StoryType.DEFENSIVE_ANCHOR in types


class TestCopy:
    def _copy(self, **kw):
        s = detect_defensive_anchor("2024-2025", 24, [_line("a", name="SA, CANDIDO", **kw)])
        c = generate_copy(
            {"story_type": s.story_type.value, "round_number": 24, "facts": s.facts}
        )
        return s, c

    def test_every_number_traces(self):
        s, c = self._copy(steals=1, blocks=5, points=5)
        assert validate_copy(c.to_dict(), {**s.facts, "round_number": 24}).ok

    def test_agrees_in_number(self):
        """A defensive line can legitimately read 1, unlike the assist and
        three-point cards whose thresholds keep every count plural."""
        _, one = self._copy(steals=1, blocks=5)
        assert "1 robo " in one.caption and "1 robos" not in one.caption
        assert "5 tapones" in one.caption

        _, none = self._copy(steals=5, blocks=0)
        assert "0 tapones" in none.caption
        assert "5 robos" in none.caption

    def test_leads_with_defence_not_scoring(self):
        _, c = self._copy(steals=1, blocks=5, points=5)
        assert c.caption.index("robo") < c.caption.index("punto")

    def test_uses_the_display_name_standard(self):
        _, c = self._copy(steals=3, blocks=3)
        assert c.headline == "CANDIDO SA"


class TestCard:
    def test_says_what_it_is(self):
        assert STORY_TO_TEMPLATE[StoryType.DEFENSIVE_ANCHOR] == "player_of_round"
        labels = labels_for(StoryType.DEFENSIVE_ANCHOR)
        assert labels["section"] and labels["badge"]

    def test_renders(self):
        s = detect_defensive_anchor("2024-2025", 24, [
            _line("a", name="SA, CANDIDO", steals=1, blocks=5, points=5)
        ])
        svg = render_template("player_of_round", {
            "story": {"facts": s.facts, "round_number": 24, "season_code": "2024-2025",
                      "story_type": s.story_type.value},
            "display": {"player": s.facts["player_name"], "team": "Zunder Palencia"},
            "assets": {"player_initials": "CS"}, "copy": {}, "meta": {},
        })
        ET.fromstring(svg)                     # valid SVG
        assert "EL MURO DE LA JORNADA" in svg  # its own headline
        assert "ROB+TAP" in svg                # the hero unit
        # The parts are on the card, so the sum can be checked by eye.
        assert re.search(r">ROB<", svg) and re.search(r">TAP<", svg)
