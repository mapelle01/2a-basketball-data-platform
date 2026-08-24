"""Queue housekeeping: the queue must be able to shrink, but only safely.

Re-running a round DUPLICATES its cards rather than replacing them (identity
includes a facts hash), so stale items accumulate — and until now nothing could
ever be removed.
"""
from __future__ import annotations

import uuid

import pytest

from feb_score.domain.content.queue import (
    PURGEABLE_STATUSES,
    ContentItem,
    ContentStatus,
    InMemoryContentQueue,
)
from feb_score.domain.content.story import StoryEntities, StoryObject, StoryType


def _item(status: ContentStatus, pid: str) -> ContentItem:
    story = StoryObject(
        story_type=StoryType.PLAYER_OF_ROUND, season_code="2024-2025",
        round_number=25, entities=StoryEntities(player_external_id=pid),
        facts={"player_external_id": pid}, source_refs={"x": "y"},
    )
    item = ContentItem(content_id=str(uuid.uuid4()), story=story,
                       template_id="player_of_round", template_version="1.0",
                       design_system_version="1.0")
    item.status = status
    return item


def _queue(*pairs) -> InMemoryContentQueue:
    q = InMemoryContentQueue()
    for i, (status, pid) in enumerate(pairs):
        q.add(_item(status, f"{pid}{i}"))
    return q


def test_purges_only_the_discarded():
    q = _queue((ContentStatus.REJECTED, "r"), (ContentStatus.FAILED, "f"),
               (ContentStatus.PENDING_REVIEW, "p"), (ContentStatus.APPROVED, "a"),
               (ContentStatus.PUBLISHED, "pub"))
    assert q.purge() == 2
    left = {i.status for i in q.all()}
    assert left == {ContentStatus.PENDING_REVIEW, ContentStatus.APPROVED,
                    ContentStatus.PUBLISHED}


def test_never_touches_live_or_published_work():
    """Housekeeping must not be able to destroy work in progress or history."""
    for protected in (ContentStatus.PENDING_REVIEW, ContentStatus.APPROVED,
                      ContentStatus.SCHEDULED, ContentStatus.PUBLISHED):
        with pytest.raises(ValueError, match="refusing to purge"):
            _queue((protected, "x")).purge([protected])


def test_purge_is_idempotent():
    q = _queue((ContentStatus.REJECTED, "r"))
    assert q.purge() == 1
    assert q.purge() == 0


def test_purgeable_set_is_explicit():
    assert PURGEABLE_STATUSES == (ContentStatus.REJECTED, ContentStatus.FAILED)
