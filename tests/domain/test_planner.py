"""Planner selection — batch variety."""
from __future__ import annotations

from feb_score.domain.content.planner import plan
from feb_score.domain.content.story import (
    StoryEntities,
    StoryObject,
    StoryStatus,
    StoryType,
)


class TestBatchVariety:
    """A round where one detector fires repeatedly must not fill the batch with
    the same card — round 25 of 2024-25 produced 3 identical season_high cards
    out of 5 before this cap existed."""

    @staticmethod
    def _story(story_type, pid, points):
        return StoryObject(
            story_type=story_type, season_code="2024-2025", round_number=25,
            entities=StoryEntities(player_external_id=pid),
            facts={"player_external_id": pid, "points": points},
            source_refs={"x": "y"},
        )

    def test_caps_repeats_of_one_type(self):
        stories = [self._story(StoryType.SEASON_HIGH, f"p{i}", 40 - i) for i in range(5)]
        selected = [s for s in plan(stories, top_n=5) if s.status is StoryStatus.SELECTED]
        assert len(selected) == 2  # the cap, not the five available

    def test_prefers_variety_over_a_second_of_the_same_type(self):
        stories = ([self._story(StoryType.SEASON_HIGH, f"p{i}", 40 - i) for i in range(4)]
                   + [self._story(StoryType.TRIPLE_DOUBLE, "d1", 20)])
        selected = [s for s in plan(stories, top_n=3) if s.status is StoryStatus.SELECTED]
        types = {s.story_type for s in selected}
        assert StoryType.TRIPLE_DOUBLE in types, "a different type must make the cut"

    def test_cap_is_configurable(self):
        stories = [self._story(StoryType.SEASON_HIGH, f"p{i}", 40 - i) for i in range(5)]
        selected = [s for s in plan(stories, top_n=5, max_per_type=1)
                    if s.status is StoryStatus.SELECTED]
        assert len(selected) == 1
