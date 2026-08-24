"""Content Queue — state machine for content items.

A ContentItem is a StoryObject that has been through the pipeline:
   Story → Copy → Render → Validate → Queue.

State machine:

   DETECTED → GENERATING → GENERATED → VALIDATING ─┬→ APPROVED ──────┐
                                                   ├→ PENDING_REVIEW ┤ (human)
                                                   └→ REJECTED       │
                                        APPROVED → SCHEDULED → PUBLISHED
   (any) → FAILED

The pipeline drives DETECTED..VALIDATING and then hands off to one of:
  * APPROVED        — passed validation AND cleared for auto-publish
  * PENDING_REVIEW  — passed validation but a human must decide (high impact)
  * REJECTED        — failed fact/visual validation
Human/ops actions move PENDING_REVIEW → APPROVED/REJECTED and
APPROVED → SCHEDULED → PUBLISHED. Transitions are validated: an illegal move
raises InvalidContentTransition rather than silently corrupting state.

Identity comes from the underlying Story's identity_key: publishing the
same story twice is prevented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from ..errors import InvalidContentTransition
from .story import StoryObject


class ContentStatus(str, Enum):
    DETECTED = "detected"
    GENERATING = "generating"
    GENERATED = "generated"
    VALIDATING = "validating"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"


# Allowed transitions. FAILED is reachable from any non-terminal state (handled
# separately in ``fail``). Terminal states (REJECTED, PUBLISHED, FAILED) have no
# outgoing edges.
_ALLOWED: Dict[ContentStatus, set] = {
    ContentStatus.DETECTED: {ContentStatus.GENERATING},
    ContentStatus.GENERATING: {ContentStatus.GENERATED},
    ContentStatus.GENERATED: {ContentStatus.VALIDATING},
    ContentStatus.VALIDATING: {
        ContentStatus.APPROVED,
        ContentStatus.PENDING_REVIEW,
        ContentStatus.REJECTED,
    },
    ContentStatus.PENDING_REVIEW: {ContentStatus.APPROVED, ContentStatus.REJECTED},
    ContentStatus.APPROVED: {ContentStatus.SCHEDULED},
    ContentStatus.SCHEDULED: {ContentStatus.PUBLISHED, ContentStatus.APPROVED},
    ContentStatus.REJECTED: set(),
    ContentStatus.PUBLISHED: set(),
    ContentStatus.FAILED: set(),
}


@dataclass
class ContentItem:
    content_id: str
    story: StoryObject
    template_id: str
    template_version: str
    design_system_version: str
    status: ContentStatus = ContentStatus.DETECTED
    copy: Optional[Dict[str, Any]] = None
    rendered_svg: Optional[str] = None
    fact_validation: Optional[Dict[str, Any]] = None
    visual_validation: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    review_reason: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    publish_result: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    published_at: Optional[datetime] = None

    def transition(self, new_status: ContentStatus) -> None:
        """Low-level transition used by the pipeline for the DETECTED..VALIDATING
        run. Validated against the allowed-transition map."""
        if new_status not in _ALLOWED.get(self.status, set()):
            raise InvalidContentTransition(
                f"cannot move content {self.content_id} from {self.status.value} "
                f"to {new_status.value}"
            )
        self.status = new_status
        self.updated_at = datetime.utcnow()

    # ------------------------------------------------------------------
    # Semantic lifecycle transitions (validate their own precondition)
    # ------------------------------------------------------------------

    def submit_for_review(self, reason: str) -> None:
        self._require(ContentStatus.VALIDATING)
        self.review_reason = reason
        self.transition(ContentStatus.PENDING_REVIEW)

    def approve(self) -> None:
        if self.status not in (ContentStatus.VALIDATING, ContentStatus.PENDING_REVIEW):
            raise InvalidContentTransition(
                f"content {self.content_id} can only be approved from validating or "
                f"pending_review, not {self.status.value}"
            )
        self.status = ContentStatus.APPROVED
        self.updated_at = datetime.utcnow()

    def reject(self, reason: Optional[str] = None) -> None:
        if self.status not in (ContentStatus.VALIDATING, ContentStatus.PENDING_REVIEW):
            raise InvalidContentTransition(
                f"content {self.content_id} can only be rejected from validating or "
                f"pending_review, not {self.status.value}"
            )
        if reason:
            self.error = reason
        self.status = ContentStatus.REJECTED
        self.updated_at = datetime.utcnow()

    def schedule(self, publish_at: Optional[datetime] = None) -> None:
        self._require(ContentStatus.APPROVED)
        self.scheduled_for = publish_at or datetime.utcnow()
        self.transition(ContentStatus.SCHEDULED)

    def mark_published(self, result: Dict[str, Any]) -> None:
        self._require(ContentStatus.SCHEDULED)
        self.publish_result = result
        self.published_at = datetime.utcnow()
        self.transition(ContentStatus.PUBLISHED)

    def fail(self, error: str) -> None:
        """FAILED is reachable from any non-terminal state."""
        if self.status in (ContentStatus.PUBLISHED, ContentStatus.FAILED):
            raise InvalidContentTransition(
                f"content {self.content_id} is terminal ({self.status.value}); cannot fail"
            )
        self.error = error
        self.status = ContentStatus.FAILED
        self.updated_at = datetime.utcnow()

    def _require(self, expected: ContentStatus) -> None:
        if self.status is not expected:
            raise InvalidContentTransition(
                f"content {self.content_id} must be {expected.value} for this action, "
                f"not {self.status.value}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content_id": self.content_id,
            "story": self.story.to_dict(),
            "template_id": self.template_id,
            "template_version": self.template_version,
            "design_system_version": self.design_system_version,
            "status": self.status.value,
            "copy": self.copy,
            "fact_validation": self.fact_validation,
            "visual_validation": self.visual_validation,
            "error": self.error,
            "review_reason": self.review_reason,
            "scheduled_for": self.scheduled_for.isoformat() if self.scheduled_for else None,
            "publish_result": self.publish_result,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "published_at": self.published_at.isoformat() if self.published_at else None,
            # rendered_svg is deliberately omitted from to_dict — it's bulky;
            # consumers fetch it explicitly if needed.
        }

    def to_full_dict(self) -> Dict[str, Any]:
        """Complete persistence form: everything in ``to_dict`` plus the
        rendered SVG. Used by the persistent queue for a lossless round-trip."""
        return {**self.to_dict(), "rendered_svg": self.rendered_svg}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContentItem":
        """Reconstruct a ContentItem from ``to_full_dict`` (persistence)."""
        item = cls(
            content_id=data["content_id"],
            story=StoryObject.from_dict(data["story"]),
            template_id=data["template_id"],
            template_version=data["template_version"],
            design_system_version=data["design_system_version"],
            status=ContentStatus(data["status"]),
            copy=data.get("copy"),
            rendered_svg=data.get("rendered_svg"),
            fact_validation=data.get("fact_validation"),
            visual_validation=data.get("visual_validation"),
            error=data.get("error"),
            review_reason=data.get("review_reason"),
            publish_result=data.get("publish_result"),
        )
        if data.get("scheduled_for"):
            item.scheduled_for = datetime.fromisoformat(data["scheduled_for"])
        if data.get("created_at"):
            item.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("updated_at"):
            item.updated_at = datetime.fromisoformat(data["updated_at"])
        if data.get("published_at"):
            item.published_at = datetime.fromisoformat(data["published_at"])
        return item


class InMemoryContentQueue:
    """v1 storage — replace with a persistent repository when needed."""

    def __init__(self) -> None:
        self._by_id: Dict[str, ContentItem] = {}
        self._by_identity: Dict[str, str] = {}  # story identity_key -> content_id

    def add(self, item: ContentItem) -> bool:
        """Add an item. Returns False if a content item with the same story
        identity is already queued (duplicate rejected)."""
        story_key = item.story.identity_key
        if story_key in self._by_identity:
            return False
        self._by_id[item.content_id] = item
        self._by_identity[story_key] = item.content_id
        return True

    def update(self, item: ContentItem) -> None:
        """Persist a state transition on an already-queued item."""
        self._by_id[item.content_id] = item
        self._by_identity[item.story.identity_key] = item.content_id

    def get(self, content_id: str) -> Optional[ContentItem]:
        return self._by_id.get(content_id)

    def by_story_identity(self, identity_key: str) -> Optional[ContentItem]:
        cid = self._by_identity.get(identity_key)
        return self._by_id.get(cid) if cid else None

    def list_by_status(self, status: ContentStatus) -> List[ContentItem]:
        return sorted(
            (i for i in self._by_id.values() if i.status == status),
            key=lambda i: (-i.story.priority, i.created_at),
        )

    def all(self) -> List[ContentItem]:
        return list(self._by_id.values())

    def seen_story_type_in_round(
        self, story_type: str, season_code: str, round_number: Optional[int]
    ) -> bool:
        for item in self._by_id.values():
            s = item.story
            if (
                s.story_type.value == story_type
                and s.season_code == season_code
                and s.round_number == round_number
            ):
                return True
        return False
