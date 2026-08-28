"""El quinteto de la jornada — the round's five best by FEB Rating.

A ranking, not a lineup: the note is the metric, so the five are ordered by it
(the top scorer does not automatically lead), and nobody is placed by position —
the position data is not clean enough to claim one.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from feb_score.domain.content.copy import generate_copy
from feb_score.domain.content.insights import PlayerLineInput, detect_best_five
from feb_score.domain.content.registry import DetectionContext, Scope, run_detectors
from feb_score.domain.content.story import STORY_TO_TEMPLATE, StoryType
from feb_score.domain.content.validation import validate_copy
from feb_score.infrastructure.rendering.component_templates import render_template


def _rated(pid, name, points):
    # A full shooting line so feb_rating produces a real note.
    return PlayerLineInput(
        pid, name, "t1", "Equipo", "m1", points=points, rebounds=5, assists=3,
        steals=1, blocks=0, turnovers=2, minutes=30.0,
        field_goals_made=8, field_goals_attempted=14, three_points_made=2,
        three_points_attempted=5, free_throws_made=4, free_throws_attempted=5,
        fouls=2, fouls_received=3,
    )


def _unrated(pid, points):
    # No minutes / no shooting → feb_rating is None.
    return PlayerLineInput(pid, pid.upper(), "t1", "Equipo", "m1",
                           points=points, rebounds=4, assists=2)


def _five():
    return [_rated(c, c.upper(), pts) for c, pts in
            [("a", 20), ("b", 24), ("c", 28), ("d", 18), ("e", 22)]]


class TestDetection:
    def test_needs_five_rateable_players(self):
        # four rated + one unrated → cannot field a five of real notes
        lines = _five()[:4] + [_unrated("x", 30)]
        assert detect_best_five("2024-2025", 24, lines) is None

    def test_fields_exactly_five_ranked_by_note(self):
        s = detect_best_five("2024-2025", 24, _five() + [_rated("f", "F", 10)])
        assert s.story_type is StoryType.BEST_FIVE
        lineup = s.facts["lineup"]
        assert len(lineup) == 5
        assert [r["rank"] for r in lineup] == [1, 2, 3, 4, 5]
        ratings = [r["rating"] for r in lineup]
        assert ratings == sorted(ratings, reverse=True)  # by note, descending
        assert all(r["rating"] is not None for r in lineup)

    def test_the_metric_is_the_note_not_points(self):
        # the top scorer need not lead when someone else rates higher
        lines = [
            _rated("scorer", "SCORER", 40),   # lots of points, ordinary efficiency
            _rated("eff1", "EFF1", 22), _rated("eff2", "EFF2", 20),
            _rated("eff3", "EFF3", 18), _rated("eff4", "EFF4", 16),
        ]
        # force the scorer's efficiency down: many missed shots
        lines[0] = PlayerLineInput(
            "scorer", "SCORER", "t1", "Equipo", "m1", points=40, rebounds=2,
            assists=1, steals=0, blocks=0, turnovers=6, minutes=34.0,
            field_goals_made=15, field_goals_attempted=40, three_points_made=2,
            three_points_attempted=15, free_throws_made=8, free_throws_attempted=12,
            fouls=4, fouls_received=2,
        )
        s = detect_best_five("2024-2025", 24, lines)
        top = s.facts["lineup"][0]
        assert top["player_external_id"] != "scorer"

    def test_registered_under_round_scope(self):
        ctx = DetectionContext("2024-2025", 24, player_lines=tuple(_five()))
        assert StoryType.BEST_FIVE in {s.story_type for s in run_detectors(ctx, {Scope.ROUND})}


class TestCopy:
    def test_names_only_no_untraceable_numbers(self):
        s = detect_best_five("2024-2025", 24, _five())
        c = generate_copy({"story_type": "best_five", "round_number": 24, "facts": s.facts})
        assert validate_copy(c.to_dict(), {**s.facts, "round_number": 24}).ok
        assert c.headline == "El quinteto de la jornada"
        assert " y " in c.caption          # the five joined naturally


class TestCard:
    def test_renders_a_ranked_grid(self):
        assert STORY_TO_TEMPLATE[StoryType.BEST_FIVE] == "best_five"
        s = detect_best_five("2024-2025", 24, _five())
        svg = render_template("best_five", {
            "story": {"facts": s.facts, "round_number": 24, "season_code": "2024-2025",
                      "story_type": "best_five"},
            "display": {}, "assets": {}, "copy": {}, "meta": {},
        })
        ET.fromstring(svg)
        assert "El quinteto de la jornada" in svg
        assert "NOTA FEB" in svg
        # all five rank numbers are drawn (a "5" also appears in the "Mejor 5"
        # badge, so check membership, not exact position)
        ranks = set(re.findall(r'>([1-5])<', svg))
        assert {"1", "2", "3", "4", "5"} <= ranks
