"""Persistent content queue (SQLite) — essential tests.

Covers what persistence must guarantee: lossless round-trip (including the
rendered SVG and validation results), cross-run deduplication by story
identity, status filtering, and the novelty helper.
"""

from __future__ import annotations

from datetime import datetime

from feb_score.domain.content.queue import ContentItem, ContentStatus
from feb_score.domain.content.story import StoryEntities, StoryObject, StoryType
from feb_score.infrastructure.persistence.content_queue_repo import (
    SqliteContentQueueRepository,
)


def _story(season="2025-2026", rnd=12, home="tA", away="tB", hs=88, as_=76):
    return StoryObject(
        story_type=StoryType.MATCH_FINAL,
        season_code=season,
        round_number=rnd,
        entities=StoryEntities(
            match_external_id=f"{home}-{away}",
            home_team_external_id=home,
            away_team_external_id=away,
        ),
        facts={"home_score": hs, "away_score": as_, "margin": abs(hs - as_)},
        source_refs={"match": f"2afeb_score://matches/{home}-{away}"},
        priority=61,
    )


def _item(story=None, content_id="c1", status=ContentStatus.APPROVED, svg="<svg>x</svg>"):
    story = story or _story()
    return ContentItem(
        content_id=content_id,
        story=story,
        template_id="match_final",
        template_version="1.0",
        design_system_version="1.0",
        status=status,
        copy={"headline": "88-76", "caption": "..."},
        rendered_svg=svg,
        fact_validation={"ok": True},
        visual_validation={"ok": True},
    )


class TestRoundTrip:
    def test_add_and_get_preserves_everything(self, sqlite_db):
        repo = SqliteContentQueueRepository(sqlite_db)
        item = _item(svg="<svg>rendered</svg>")
        assert repo.add(item) is True

        loaded = repo.get("c1")
        assert loaded is not None
        assert loaded.content_id == "c1"
        assert loaded.story.story_type is StoryType.MATCH_FINAL
        assert loaded.story.facts["home_score"] == 88
        assert loaded.rendered_svg == "<svg>rendered</svg>"
        assert loaded.fact_validation == {"ok": True}
        assert loaded.status is ContentStatus.APPROVED

    def test_identity_key_survives_round_trip(self, sqlite_db):
        repo = SqliteContentQueueRepository(sqlite_db)
        item = _item()
        original_key = item.story.identity_key
        repo.add(item)
        loaded = repo.get("c1")
        assert loaded.story.identity_key == original_key


class TestDeduplication:
    def test_same_story_identity_rejected(self, sqlite_db):
        repo = SqliteContentQueueRepository(sqlite_db)
        assert repo.add(_item(content_id="c1")) is True
        # Same story (same facts) → same identity → rejected even with a new id.
        assert repo.add(_item(content_id="c2")) is False
        assert len(repo.all()) == 1

    def test_different_story_accepted(self, sqlite_db):
        repo = SqliteContentQueueRepository(sqlite_db)
        assert repo.add(_item(story=_story(hs=88), content_id="c1")) is True
        assert repo.add(_item(story=_story(hs=99), content_id="c2")) is True
        assert len(repo.all()) == 2

    def test_by_story_identity_lookup(self, sqlite_db):
        repo = SqliteContentQueueRepository(sqlite_db)
        item = _item()
        repo.add(item)
        found = repo.by_story_identity(item.story.identity_key)
        assert found is not None
        assert found.content_id == "c1"


class TestStatusFiltering:
    def test_list_by_status(self, sqlite_db):
        repo = SqliteContentQueueRepository(sqlite_db)
        repo.add(_item(story=_story(hs=88), content_id="a", status=ContentStatus.APPROVED))
        repo.add(_item(story=_story(hs=99), content_id="r", status=ContentStatus.REJECTED))

        approved = repo.list_by_status(ContentStatus.APPROVED)
        assert [i.content_id for i in approved] == ["a"]
        rejected = repo.list_by_status(ContentStatus.REJECTED)
        assert [i.content_id for i in rejected] == ["r"]

    def test_ordering_by_priority(self, sqlite_db):
        repo = SqliteContentQueueRepository(sqlite_db)
        low = _story(hs=88)
        high = _story(hs=99)
        repo.add(_item(story=low, content_id="low"))
        item_high = _item(story=high, content_id="high")
        item_high.story = StoryObject(
            story_type=high.story_type, season_code=high.season_code,
            round_number=high.round_number, entities=high.entities,
            facts=high.facts, source_refs=high.source_refs, priority=95,
        )
        repo.add(item_high)
        ordered = repo.all()
        assert ordered[0].content_id == "high"  # higher priority first


class TestNovelty:
    def test_seen_story_type_in_round(self, sqlite_db):
        repo = SqliteContentQueueRepository(sqlite_db)
        assert repo.seen_story_type_in_round("match_final", "2025-2026", 12) is False
        repo.add(_item())
        assert repo.seen_story_type_in_round("match_final", "2025-2026", 12) is True
        # Different round → not seen.
        assert repo.seen_story_type_in_round("match_final", "2025-2026", 13) is False
