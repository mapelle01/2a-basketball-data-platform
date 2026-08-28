"""Content Engine v1 — essential tests only (no marathon).

Covers the invariants that make the pipeline trustworthy:
  - Story identity is stable (dedup works)
  - Planner scoring is deterministic and ordered
  - Fact Validator catches hallucinated numbers
  - Pipeline end-to-end approves valid content
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from feb_score.application.use_cases.round_pipeline import RoundPipeline
from feb_score.infrastructure.rendering.asset_provider import StatisticalAssetProvider
from feb_score.infrastructure.rendering.svg_renderer import ComponentSvgRenderer
from feb_score.domain.content.copy import generate_copy_match_final
from feb_score.domain.content.insights import (
    MatchFactsInput,
    PlayerLineInput,
    detect_all_for_round,
    detect_biggest_win,
    detect_match_final,
    detect_notable_performances,
    detect_player_of_round,
    detect_round_recap,
)
from feb_score.domain.content.planner import plan, score_story
from feb_score.domain.content.queue import InMemoryContentQueue
from feb_score.domain.content.queue import ContentStatus
from feb_score.domain.content.story import StoryStatus, StoryType
from feb_score.domain.content.validation import validate_copy


REPO_ROOT = Path(__file__).resolve().parents[2]

# Statuses meaning "content passed validation" (auto-approved OR queued for a
# human to sign off). Both are success; only REJECTED/FAILED are not.
_VALIDATED = {ContentStatus.APPROVED, ContentStatus.PENDING_REVIEW}


def _match(
    external_id="m1", home=88, away=76, home_team="teamA", away_team="teamB",
    home_name="auto", away_name="auto",
):
    return MatchFactsInput(
        external_id=external_id,
        season_code="2025-2026",
        round_number=12,
        home_team_external_id=home_team,
        away_team_external_id=away_team,
        home_team_name=(f"Team {home_team}" if home_name == "auto" else home_name),
        away_team_name=(f"Team {away_team}" if away_name == "auto" else away_name),
        home_score=home,
        away_score=away,
        scheduled_at=datetime(2026, 1, 24, 18, 0),
    )


def _player(pid="p1", team="teamA", match="m1", points=25, rebounds=6, assists=4, name="auto"):
    return PlayerLineInput(
        player_external_id=pid,
        player_name=(f"Player {pid}" if name == "auto" else name),
        team_external_id=team,
        team_name=f"Team {team}",
        match_external_id=match,
        points=points,
        rebounds=rebounds,
        assists=assists,
    )


def _pipeline():
    return RoundPipeline(
        renderer=ComponentSvgRenderer(),
        assets=StatisticalAssetProvider(),
    )


class TestStoryIdentity:
    def test_identity_is_stable(self):
        m = _match()
        s1 = detect_match_final(m)
        s2 = detect_match_final(m)
        assert s1.identity_key == s2.identity_key

    def test_different_matches_have_different_identity(self):
        s1 = detect_match_final(_match(external_id="m1"))
        s2 = detect_match_final(_match(external_id="m2"))
        assert s1.identity_key != s2.identity_key

    def test_facts_change_changes_hash_not_entity_identity_boundary(self):
        s1 = detect_match_final(_match(home=88, away=76))
        s2 = detect_match_final(_match(home=90, away=76))
        # Different facts → different identity (a corrected stat is a new story)
        assert s1.identity_key != s2.identity_key


class TestPlanner:
    def test_scoring_is_deterministic(self):
        s = detect_match_final(_match())
        assert score_story(s).total == score_story(s).total

    def test_plan_orders_by_priority_desc(self):
        stories = [
            detect_match_final(_match(external_id="close", home=76, away=74)),
            detect_match_final(_match(external_id="blowout", home=104, away=72)),
        ]
        selected = plan(stories, top_n=2)
        assert selected[0].priority >= selected[1].priority
        assert all(s.status is StoryStatus.SELECTED for s in selected)

    def test_top_n_rejects_the_rest(self):
        stories = [detect_match_final(_match(external_id=f"m{i}")) for i in range(5)]
        planned = plan(stories, top_n=2)
        selected = [s for s in planned if s.status is StoryStatus.SELECTED]
        rejected = [s for s in planned if s.status is StoryStatus.REJECTED]
        assert len(selected) == 2
        assert len(rejected) == 3


class TestFactValidator:
    def test_hallucinated_number_fails(self):
        copy = {"headline": "Team A 100-70 Team B", "subtitle": "", "caption": ""}
        facts = {"home_score": 88, "away_score": 76, "round_number": 12}
        result = validate_copy(copy, facts)
        assert not result.ok
        assert "100" in result.hallucinated_numbers or "70" in result.hallucinated_numbers

    def test_all_numbers_present_passes(self):
        copy = {"headline": "88-76", "subtitle": "Jornada 12", "caption": ""}
        facts = {"home_score": 88, "away_score": 76, "round_number": 12}
        assert validate_copy(copy, facts).ok

    def test_score_separator_not_treated_as_negative(self):
        copy = {"headline": "104-72", "subtitle": "", "caption": ""}
        facts = {"home_score": 104, "away_score": 72}
        assert validate_copy(copy, facts).ok


class TestCopyGenerator:
    def test_match_final_copy_uses_only_facts(self):
        story = detect_match_final(_match(home=88, away=76))
        copy = generate_copy_match_final(story.to_dict())
        # Every fact used is in the story.facts payload
        for key in copy.facts_used:
            assert key in {**story.facts, "round_number": story.round_number}, key


class TestPipelineEndToEnd:
    def test_pipeline_approves_valid_stories(self):
        matches = [_match(external_id="m1"), _match(external_id="m2", home=100, away=70)]
        players = [
            _player(pid="p1", match="m1", points=27),
            _player(pid="p2", match="m2", points=15),
        ]
        pipeline = RoundPipeline(
            renderer=ComponentSvgRenderer(),
            assets=StatisticalAssetProvider(),
        )
        items = pipeline.run("2025-2026", 12, matches, players, top_n=5).items

        approved = [i for i in items if i.status is ContentStatus.APPROVED]
        assert approved, "expected at least one approved content item"
        for item in approved:
            assert item.rendered_svg is not None
            assert item.fact_validation["ok"] is True
            assert item.visual_validation["ok"] is True

    def test_pipeline_deduplicates_by_story_identity(self):
        matches = [_match(external_id="m1")]
        players = [_player(match="m1")]
        pipeline = _pipeline()
        pipeline.run("2025-2026", 12, matches, players)
        # Second run over the same round should not duplicate anything already in queue.
        before = len(pipeline.queue.all())
        pipeline.run("2025-2026", 12, matches, players)
        after = len(pipeline.queue.all())
        assert before == after


class TestRunMetricsAndDedup:
    def test_metrics_reported(self):
        matches = [_match(external_id="m1"), _match(external_id="m2", home=100, away=70)]
        players = [_player(pid="p1", match="m1", points=27)]
        result = _pipeline().run("2025-2026", 12, matches, players, top_n=12)
        m = result.metrics
        assert m.stories_detected > 0
        assert m.content_generated == len(result.items)
        assert m.duplicates_skipped == 0

    def test_rerun_skips_without_regenerating(self):
        matches = [_match(external_id="m1")]
        players = [_player(match="m1", points=27)]
        pipeline = _pipeline()
        first = pipeline.run("2025-2026", 12, matches, players, top_n=12)
        second = pipeline.run("2025-2026", 12, matches, players, top_n=12)
        # Everything is a duplicate on the second run: nothing new generated.
        assert second.metrics.content_generated == 0
        assert second.metrics.duplicates_skipped == first.metrics.content_generated
        assert second.items == []

    def test_render_not_called_for_duplicates(self):
        # A counting renderer proves we don't re-render already-queued stories.
        class _CountingRenderer(ComponentSvgRenderer):
            def __init__(self):
                self.calls = 0

            def render(self, name, data):
                self.calls += 1
                return super().render(name, data)

        renderer = _CountingRenderer()
        pipeline = RoundPipeline(renderer=renderer, assets=StatisticalAssetProvider())
        matches = [_match(external_id="m1")]
        players = [_player(match="m1", points=27)]
        pipeline.run("2025-2026", 12, matches, players, top_n=12)
        after_first = renderer.calls
        pipeline.run("2025-2026", 12, matches, players, top_n=12)
        assert renderer.calls == after_first  # zero extra renders on the re-run


class TestNoveltyScoring:
    def test_seen_story_type_penalized(self):
        from feb_score.domain.content.planner import score_story

        story = detect_match_final(_match())
        base = score_story(story, seen_story_types=set()).novelty
        penalized = score_story(story, seen_story_types={story.story_type}).novelty
        assert penalized < base

    def test_queue_seen_helper(self):
        queue = InMemoryContentQueue()
        assert queue.seen_story_type_in_round("match_final", "2025-2026", 12) is False


class TestImperfectData:
    """The FEB feed is unstable: catalog names and boxscore rows can be
    missing. The engine must degrade gracefully — never reject a whole piece
    for a missing display name or a round without player stats."""

    def test_match_final_approved_without_team_names(self):
        # No catalog name → display falls back to the (numeric) external_id.
        matches = [_match(external_id="m1", home_team="979897", away_team="983412",
                          home_name=None, away_name=None)]
        items = _pipeline().run("2025-2026", 12, matches, []).items
        match_finals = [i for i in items if i.story.story_type is StoryType.MATCH_FINAL]
        assert match_finals
        for item in match_finals:
            assert item.status is ContentStatus.APPROVED, item.visual_validation
            # The external_id shows up as the display name; not a hallucination.
            assert item.fact_validation["ok"] is True

    def test_round_recap_is_not_emitted_by_the_pipeline(self):
        # round_recap was retired (see registry): it crammed four unrelated
        # numbers onto one card. The pipeline must no longer produce it.
        matches = [
            _match(external_id="m1", home=88, away=76),
            _match(external_id="m2", home=104, away=72),
        ]
        items = _pipeline().run("2025-2026", 12, matches, []).items
        assert not [i for i in items if i.story.story_type is StoryType.ROUND_RECAP]
        # the round still produces content — one story per match, plus the
        # biggest win — just not the grab-bag recap.
        assert [i for i in items if i.story.story_type is StoryType.MATCH_FINAL]

    def test_round_recap_detector_still_fabricates_no_zero_scorer(self):
        # The detector is dormant, not deleted; if it is ever revived it must
        # still never invent a "0 pts" top scorer when no boxscore rows exist.
        matches = [_match(external_id="m1", home=88, away=76)]
        story = detect_round_recap("2025-2026", 12, matches, [])
        assert story is not None
        assert "top_scorer_points" not in story.facts

    def test_player_of_round_approved_without_player_name(self):
        matches = [_match(external_id="m1")]
        players = [_player(pid="2772828", match="m1", points=27, name=None)]
        items = _pipeline().run("2025-2026", 12, matches, players).items
        por = [i for i in items if i.story.story_type is StoryType.PLAYER_OF_ROUND]
        assert por
        for item in por:
            assert item.status in _VALIDATED, item.visual_validation
            assert item.fact_validation["ok"] is True

    def test_numeric_external_id_is_not_a_hallucination(self):
        copy = {"headline": "2772828", "subtitle": "", "caption": ""}
        facts = {"player_external_id": "2772828", "points": 27}
        assert validate_copy(copy, facts).ok


class TestAdditionalDetectors:
    def test_biggest_win_only_on_blowout(self):
        close = detect_biggest_win("2025-2026", 12, [_match(home=80, away=76)])
        assert close is None  # 4-point margin is not a blowout
        blowout = detect_biggest_win("2025-2026", 12, [_match(home=100, away=72)])
        assert blowout is not None
        assert blowout.story_type is StoryType.BIGGEST_WIN
        assert blowout.facts["margin"] == 28

    def test_biggest_win_picks_largest_margin(self):
        matches = [
            _match(external_id="m1", home=80, away=76),
            _match(external_id="m2", home=104, away=72),
        ]
        story = detect_biggest_win("2025-2026", 12, matches)
        assert story.entities.match_external_id == "m2"

    def test_double_double_detected(self):
        players = [_player(pid="p1", points=18, rebounds=12, assists=3)]
        stories = detect_notable_performances("2025-2026", 12, players)
        assert len(stories) == 1
        assert stories[0].story_type is StoryType.DOUBLE_DOUBLE

    def test_triple_double_detected(self):
        players = [_player(pid="p1", points=15, rebounds=11, assists=10)]
        stories = detect_notable_performances("2025-2026", 12, players)
        assert stories[0].story_type is StoryType.TRIPLE_DOUBLE

    def test_no_notable_performance_below_threshold(self):
        players = [_player(pid="p1", points=25, rebounds=6, assists=4)]
        assert detect_notable_performances("2025-2026", 12, players) == []

    def test_new_detectors_render_via_reused_templates(self):
        matches = [_match(external_id="m2", home=104, away=72)]
        # Two players, not one: since the planner allows a single card per
        # subject, one player producing both the double-double and the player
        # of the round would (correctly) yield only one of them.
        players = [
            _player(pid="p1", match="m2", points=18, rebounds=12, assists=3),
            _player(pid="p2", match="m2", points=31, rebounds=4, assists=6),
        ]
        items = _pipeline().run("2025-2026", 12, matches, players, top_n=12).items
        types = {i.story.story_type for i in items}
        assert StoryType.BIGGEST_WIN in types
        assert StoryType.DOUBLE_DOUBLE in types
        for item in items:
            if item.story.story_type in (StoryType.BIGGEST_WIN, StoryType.DOUBLE_DOUBLE):
                assert item.status is ContentStatus.APPROVED, item.visual_validation
                assert item.rendered_svg is not None
