"""Content Lifecycle Service — drives an item past validation to publication.

Orchestrates the human/ops half of the state machine:

    PENDING_REVIEW ──approve──▶ APPROVED ──schedule──▶ SCHEDULED ──publish──▶ PUBLISHED
        └────────────reject──▶ REJECTED

Each action loads the item, applies the domain transition (which validates its
precondition and raises InvalidContentTransition on an illegal move), persists
via ``queue.update``, and returns the updated item. Publishing delegates to a
``Publisher`` (DryRunPublisher by default) and records the ``PublishResult``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..content.interfaces import ContentQueue, Publisher
from ...domain.content.queue import ContentItem, ContentStatus
from ...domain.errors import EntityNotFound, InvalidContentTransition


class ContentLifecycleService:
    def __init__(self, queue: ContentQueue, publisher: Publisher) -> None:
        self._queue = queue
        self._publisher = publisher

    def approve_review(self, content_id: str) -> ContentItem:
        item = self._require(content_id)
        item.approve()
        self._queue.update(item)
        return item

    def reject_review(self, content_id: str, reason: Optional[str] = None) -> ContentItem:
        item = self._require(content_id)
        item.reject(reason)
        self._queue.update(item)
        return item

    def schedule(self, content_id: str, publish_at: Optional[datetime] = None) -> ContentItem:
        item = self._require(content_id)
        item.schedule(publish_at)
        self._queue.update(item)
        return item

    def publish(self, content_id: str) -> ContentItem:
        item = self._require(content_id)
        # Validate the precondition BEFORE the external call, so a real channel
        # adapter never delivers something that then fails its state transition.
        if item.status is not ContentStatus.SCHEDULED:
            raise InvalidContentTransition(
                f"content {content_id} must be scheduled to publish, not {item.status.value}"
            )
        result = self._publisher.publish(item)
        item.mark_published(result.to_dict())
        self._queue.update(item)
        return item

    def _require(self, content_id: str) -> ContentItem:
        item = self._queue.get(content_id)
        if item is None:
            raise EntityNotFound(f"content item {content_id} not found")
        return item
