"""Content lifecycle — state machine + review policy + lifecycle service.

Covers the invariants that keep publication safe: only legal transitions
succeed, high-impact stories route to review, and publishing goes through the
Publisher exactly once from SCHEDULED.
"""

from __future__ import annotations

import pytest

from feb_score.application.content.interfaces import Publisher, PublishResult
from feb_score.application.use_cases.content_lifecycle import ContentLifecycleService
from feb_score.domain.content.queue import (
    ContentItem,
    ContentStatus,
    InMemoryContentQueue,
)
from feb_score.domain.content.review import decide_review
from feb_score.domain.content.story import StoryEntities, StoryObject, StoryType
from feb_score.domain.errors import EntityNotFound, InvalidContentTransition


def _story(story_type=StoryType.MATCH_FINAL, priority=50):
    return StoryObject(
        story_type=story_type,
        season_code="2025-2026",
        round_number=12,
        entities=StoryEntities(match_external_id="m1"),
        facts={"home_score": 88, "away_score": 76},
        source_refs={},
        priority=priority,
    )


def _item(story=None, status=ContentStatus.VALIDATING, content_id="c1"):
    return ContentItem(
        content_id=content_id,
        story=story or _story(),
        template_id="match_final",
        template_version="1.0",
        design_system_version="1.0",
        status=status,
    )


class _SpyPublisher(Publisher):
    def __init__(self):
        self.calls = 0

    @property
    def channel(self):
        return "spy"

    def publish(self, item):
        self.calls += 1
        return PublishResult(channel="spy", external_ref="ref-1", dry_run=False)


class TestStateMachine:
    def test_approve_from_validating(self):
        item = _item(status=ContentStatus.VALIDATING)
        item.approve()
        assert item.status is ContentStatus.APPROVED

    def test_full_happy_path(self):
        item = _item(status=ContentStatus.VALIDATING)
        item.approve()
        item.schedule()
        assert item.status is ContentStatus.SCHEDULED
        item.mark_published({"channel": "dry_run", "dry_run": True})
        assert item.status is ContentStatus.PUBLISHED
        assert item.published_at is not None

    def test_cannot_schedule_before_approved(self):
        item = _item(status=ContentStatus.VALIDATING)
        with pytest.raises(InvalidContentTransition):
            item.schedule()

    def test_cannot_publish_before_scheduled(self):
        item = _item(status=ContentStatus.APPROVED)
        with pytest.raises(InvalidContentTransition):
            item.mark_published({})

    def test_cannot_transition_from_terminal(self):
        item = _item(status=ContentStatus.APPROVED)
        item.schedule()
        item.mark_published({"dry_run": True})
        with pytest.raises(InvalidContentTransition):
            item.fail("too late")

    def test_submit_for_review_then_reject(self):
        item = _item(status=ContentStatus.VALIDATING)
        item.submit_for_review("high impact")
        assert item.status is ContentStatus.PENDING_REVIEW
        assert item.review_reason == "high impact"
        item.reject("not good enough")
        assert item.status is ContentStatus.REJECTED
        assert item.error == "not good enough"


class TestReviewPolicy:
    def test_high_impact_type_needs_review(self):
        assert decide_review(_story(StoryType.PLAYER_OF_ROUND)).requires_review
        assert decide_review(_story(StoryType.ROUND_RECAP)).requires_review

    def test_high_priority_needs_review(self):
        assert decide_review(_story(StoryType.MATCH_FINAL, priority=85)).requires_review

    def test_routine_is_auto(self):
        d = decide_review(_story(StoryType.MATCH_FINAL, priority=50))
        assert not d.requires_review


class TestLifecycleService:
    def _service(self):
        queue = InMemoryContentQueue()
        publisher = _SpyPublisher()
        return ContentLifecycleService(queue, publisher), queue, publisher

    def test_review_approve_schedule_publish(self):
        service, queue, publisher = self._service()
        item = _item(status=ContentStatus.PENDING_REVIEW)
        queue.add(item)

        service.approve_review("c1")
        assert queue.get("c1").status is ContentStatus.APPROVED
        service.schedule("c1")
        assert queue.get("c1").status is ContentStatus.SCHEDULED
        service.publish("c1")
        assert queue.get("c1").status is ContentStatus.PUBLISHED
        assert publisher.calls == 1

    def test_publish_requires_scheduled(self):
        service, queue, _ = self._service()
        queue.add(_item(status=ContentStatus.APPROVED))
        with pytest.raises(InvalidContentTransition):
            service.publish("c1")

    def test_publisher_not_called_on_illegal_publish(self):
        service, queue, publisher = self._service()
        queue.add(_item(status=ContentStatus.APPROVED))
        with pytest.raises(InvalidContentTransition):
            service.publish("c1")
        assert publisher.calls == 0  # never delivered

    def test_unknown_item_raises(self):
        service, _, _ = self._service()
        with pytest.raises(EntityNotFound):
            service.approve_review("nope")

    def test_reject_from_review(self):
        service, queue, _ = self._service()
        queue.add(_item(status=ContentStatus.PENDING_REVIEW))
        service.reject_review("c1", "off-brand")
        assert queue.get("c1").status is ContentStatus.REJECTED
