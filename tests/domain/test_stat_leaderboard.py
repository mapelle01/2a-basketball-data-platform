"""Stat leaderboard — FEB Rating + top-scorers detector + template.

Covers the invariants: the rating is deterministic and bounded, the detector
ranks by points and needs a real field, and the template renders through the
pipeline as a valid, approved piece.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from feb_score.application.use_cases.round_pipeline import RoundPipeline
from feb_score.domain.content.insights import PlayerLineInput, detect_stat_leaderboard
from feb_score.domain.content.queue import ContentStatus
from feb_score.domain.content.rating import feb_rating
from feb_score.domain.content.story import StoryType
from feb_score.infrastructure.rendering.asset_provider import StatisticalAssetProvider
from feb_score.infrastructure.rendering.svg_renderer import ComponentSvgRenderer


def _line(pid, name, pts, reb=5, ast=3):
    return PlayerLineInput(
        player_external_id=pid, player_name=name, team_external_id="t",
        team_name="Team", match_external_id="m", points=pts, rebounds=reb, assists=ast,
    )


class TestFebRating:
    """v2 grades a LINE: it needs minutes and shooting, and refuses to grade
    what it cannot grade on the same basis as everything else."""

    # a full, ordinary line — the shape every test below varies
    BASE = dict(minutes=28.0, field_goals_made=5, field_goals_attempted=11,
                free_throws_made=2, free_throws_attempted=3,
                three_points_made=1, fouls=3)

    def _r(self, pts, reb, ast, stl=0, blk=0, to=0, **over):
        kw = {**self.BASE, **over}
        return feb_rating(pts, reb, ast, stl, blk, to, **kw)

    def test_bounded_0_10(self):
        assert 0.0 <= self._r(0, 0, 0) <= 10.0
        # v3.0: the extremes are reachable only at full minutes, where the
        # sample-confidence factor is 1.0 (a short sample regresses toward 6.5).
        assert self._r(100, 50, 30, 10, 10, minutes=40.0, field_goals_made=40,
                       field_goals_attempted=40) == 10.0
        assert self._r(0, 0, 0, 0, 0, 200, minutes=40.0) == 0.0

    def test_deterministic(self):
        assert self._r(31, 9, 5, 2, 1, 2) == self._r(31, 9, 5, 2, 1, 2)

    def test_monotonic_in_points(self):
        assert self._r(30, 5, 3) > self._r(10, 5, 3)

    def test_not_graded_without_minutes_or_shooting(self):
        # No fallback number: an ungradeable line has no note at all.
        assert feb_rating(20, 5, 3) is None                       # no minutes
        assert self._r(20, 5, 3, minutes=None) is None
        assert self._r(20, 5, 3, minutes=4.0) is None             # under MIN_MINUTES
        assert self._r(20, 5, 3, field_goals_attempted=None) is None

    def test_efficiency_matters(self):
        """v1's blind spot: the same 21 points on very different shooting."""
        efficient = self._r(21, 4, 2, field_goals_made=8, field_goals_attempted=12)
        wasteful = self._r(21, 4, 2, field_goals_made=8, field_goals_attempted=25)
        assert efficient > wasteful

    def test_fouls_and_turnovers_cost(self):
        assert self._r(14, 5, 2, fouls=1) > self._r(14, 5, 2, fouls=5)
        assert self._r(14, 5, 2, to=0) > self._r(14, 5, 2, to=5)

    def test_measures_level_not_accumulation(self):
        """The same production in fewer minutes is a better performance —
        this is what separates the mark from the official VAL."""
        assert self._r(18, 6, 3, minutes=20.0) > self._r(18, 6, 3, minutes=38.0)

    def test_short_samples_are_shrunk(self):
        """A brief hot cameo must not out-rate a sustained big game."""
        cameo = self._r(8, 1, 0, minutes=10.0, field_goals_made=3,
                        field_goals_attempted=3)
        full = self._r(24, 9, 5, minutes=33.0, field_goals_made=9,
                       field_goals_attempted=15)
        assert full > cameo

    def test_average_game_anchored_near_six_five(self):
        # Calibrated on the frozen 4-season pool (v3.0): the median sits at 6.5.
        assert 6.0 <= self._r(12, 4, 2, 1, 0, 2) <= 7.0

    def test_low_band_is_alive(self):
        assert self._r(2, 1, 0, 0, 0, 3, field_goals_made=1,
                       field_goals_attempted=8) < 5.0

    def test_elite_games_separate_below_ten(self):
        monster = self._r(35, 12, 8, 2, 1, 3, field_goals_made=13,
                          field_goals_attempted=20)
        historic = self._r(44, 15, 10, 3, 2, 3, field_goals_made=17,
                           field_goals_attempted=22)
        assert monster < 10.0
        assert monster < historic


class TestDetector:
    def test_ranks_by_points(self):
        lines = [_line("a", "A", 20), _line("b", "B", 31), _line("c", "C", 25)]
        story = detect_stat_leaderboard("2025-2026", 12, lines)
        assert story is not None
        leaders = story.facts["leaders"]
        assert [l["player_name"] for l in leaders] == ["B", "C", "A"]
        assert leaders[0]["rank"] == 1
        assert "rating" in leaders[0]

    def test_needs_at_least_three(self):
        assert detect_stat_leaderboard("2025-2026", 12, [_line("a", "A", 20)]) is None

    def test_top_n_limit(self):
        lines = [_line(str(i), f"P{i}", 30 - i) for i in range(8)]
        story = detect_stat_leaderboard("2025-2026", 12, lines, top_n=5)
        assert story.facts["count"] == 5


class TestTemplate:
    def test_renders_through_pipeline(self):
        lines = [_line("a", "A. Uno", 31), _line("b", "B. Dos", 27), _line("c", "C. Tres", 24)]
        pipeline = RoundPipeline(
            renderer=ComponentSvgRenderer(), assets=StatisticalAssetProvider()
        )
        items = pipeline.run("2025-2026", 12, [], lines, top_n=12).items
        boards = [i for i in items if i.story.story_type is StoryType.STAT_LEADERBOARD]
        assert boards
        item = boards[0]
        assert item.status in (ContentStatus.APPROVED, ContentStatus.PENDING_REVIEW)
        assert item.fact_validation["ok"] is True
        assert item.visual_validation["ok"] is True
        ET.fromstring(item.rendered_svg)  # valid SVG
