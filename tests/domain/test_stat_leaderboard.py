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
    def test_bounded_0_10(self):
        assert 0.0 <= feb_rating(0, 0, 0) <= 10.0
        assert feb_rating(100, 50, 30, 10, 10) == 10.0  # saturates at 10, never over
        assert feb_rating(0, 0, 0, 0, 0, 200) == 0.0    # clamps at 0, never below

    def test_deterministic(self):
        assert feb_rating(31, 9, 5, 2, 1, 2) == feb_rating(31, 9, 5, 2, 1, 2)

    def test_monotonic_in_points(self):
        assert feb_rating(30, 5, 3) > feb_rating(10, 5, 3)


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
