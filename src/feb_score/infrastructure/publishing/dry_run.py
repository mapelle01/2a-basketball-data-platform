"""DryRunPublisher — the default, side-effect-free publisher.

Marks a content item as "published" without contacting any external service.
It lets the full lifecycle (APPROVED → SCHEDULED → PUBLISHED) run end-to-end
and be observed/tested while no real Instagram/Web integration exists. Real
channel adapters implement the same ``Publisher`` interface and slot in without
touching the lifecycle service.
"""

from __future__ import annotations

from typing import Any

from ...application.content.interfaces import Publisher, PublishResult


class DryRunPublisher(Publisher):
    @property
    def channel(self) -> str:
        return "dry_run"

    def publish(self, item: Any) -> PublishResult:
        return PublishResult(
            channel="dry_run",
            external_ref=None,
            dry_run=True,
            detail=f"dry-run publish of {item.content_id} ({item.story.story_type.value})",
        )
