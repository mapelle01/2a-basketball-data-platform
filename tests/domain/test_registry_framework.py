"""Detector registry framework — the pattern-detection engine.

Proves the framework contract: existing detectors are registered by scope, the
runner filters by scope and collects, a new detector is pluggable in one call,
the season aggregate folds correctly, and a season-scope detector flows all the
way to a rendered card.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from feb_score.domain.content import registry
from feb_score.domain.content.copy import generate_copy
from feb_score.domain.content.insights import PlayerLineInput
from feb_score.domain.content.registry import (
    DetectionContext,
    Scope,
    register,
    registered,
    run_detectors,
)
from feb_score.domain.content.season_aggregate import (
    build_season_aggregate,
    detect_season_scoring_leader,
)
from feb_score.domain.content.story import STORY_TO_TEMPLATE, StoryType
from feb_score.domain.content.validation import validate_copy
from feb_score.infrastructure.rendering.component_templates import render_template


def _line(pid, pts, reb=4, ast=3, name=None):
    return PlayerLineInput(pid, name or pid.upper(), "t", "Team", "m", pts, reb, ast)


class TestRegistry:
    def test_existing_detectors_registered_by_scope(self):
        round_names = {s.name for s in registered(Scope.ROUND)}
        assert {"match_final", "player_of_round", "stat_leaderboard", "iron_man"} <= round_names
        season_names = {s.name for s in registered(Scope.SEASON)}
        assert {"season_highs", "team_streaks", "upsets", "season_scoring_leader"} <= season_names

    def test_run_filters_by_scope(self):
        ctx = DetectionContext(
            "2025-2026", 5, player_lines=(_line("a", 20), _line("b", 15), _line("c", 10))
        )
        assert run_detectors(ctx, {Scope.ROUND})           # round detectors fire
        assert run_detectors(ctx, {Scope.SEASON}) == []     # no season data → nothing

    def test_register_is_pluggable(self):
        snapshot = list(registry._REGISTRY)
        try:
            @register("dummy_test_detector", Scope.ROUND)
            def _dummy(ctx):
                return []
            assert any(s.name == "dummy_test_detector" for s in registered(Scope.ROUND))
        finally:
            registry._REGISTRY[:] = snapshot  # never pollute the global registry
        assert not any(s.name == "dummy_test_detector" for s in registered())


class TestSeasonAggregate:
    def test_folds_rounds(self):
        r1 = [_line("a", 20, name="A. Uno"), _line("b", 10)]
        r2 = [_line("a", 30, name="A. Uno")]
        agg = build_season_aggregate("2025-2026", [r1, r2])
        a = next(p for p in agg.players if p.player_external_id == "a")
        assert a.games == 2 and a.points == 50 and a.player_name == "A. Uno"
        assert a.ppg == 25.0

    def test_scoring_leader_skips_without_aggregate(self):
        assert detect_season_scoring_leader("2025-2026", 5, None) == []

    def test_scoring_leader_fires_with_enough_games(self):
        agg = build_season_aggregate(
            "2025-2026", [[_line("a", 30, name="A. Uno"), _line("b", 10)]] * 3
        )
        stories = detect_season_scoring_leader("2025-2026", 5, agg)
        assert stories and stories[0].story_type is StoryType.TOP_SCORER
        assert stories[0].facts["points"] == 90 and stories[0].facts["games_played"] == 3


class TestEndToEnd:
    def test_season_leader_flows_to_render(self):
        agg = build_season_aggregate(
            "2025-2026", [[_line("a", 30, name="C. Sáez"), _line("b", 10)]] * 4
        )
        stories = run_detectors(DetectionContext("2025-2026", 5, season=agg), {Scope.SEASON})
        top = [s for s in stories if s.story_type is StoryType.TOP_SCORER]
        assert top
        s = top[0]
        # copy validates (no invented numbers)
        copy = generate_copy(
            {"story_type": s.story_type.value, "round_number": s.round_number, "facts": s.facts}
        )
        vf = {**s.facts, "round_number": s.round_number}
        assert validate_copy(copy.to_dict(), vf).ok
        # renders through the mapped template
        assert STORY_TO_TEMPLATE[s.story_type] == "player_of_round"
        data = {
            "story": {"facts": s.facts, "round_number": 5, "season_code": "2025-2026"},
            "display": {"player": "C. Sáez", "team": "Alicante"},
            "assets": {"player_initials": "CS"}, "copy": {}, "meta": {},
        }
        ET.fromstring(render_template("player_of_round", data))
