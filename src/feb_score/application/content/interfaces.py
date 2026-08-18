"""Application-layer contracts for the Content Engine's infrastructure needs.

Templates and assets are infrastructure concerns (files, image sources,
external services). The Application layer depends only on these narrow
interfaces; concrete implementations live in ``feb_score.infrastructure``
and are wired at composition time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


class TemplateRenderer(ABC):
    @abstractmethod
    def render(self, template_name: str, data: Dict[str, Any]) -> str:
        """Return a rendered SVG string with placeholders substituted."""


# ---------------------------------------------------------------------------
# Assets — Level A/B/C fallback (see design system)
# ---------------------------------------------------------------------------


ASSET_LEVEL_OFFICIAL = "A"
ASSET_LEVEL_CONTEXTUAL = "B"
ASSET_LEVEL_STATISTICAL = "C"


@dataclass(frozen=True)
class Asset:
    """A resolved asset ready to embed in a template slot."""

    kind: str
    level: str
    payload: str
    payload_type: str
    source: Optional[str] = None


class AssetProvider(ABC):
    @abstractmethod
    def player_photo(self, player_external_id: str) -> Asset:
        """Return an asset representing a player. Always resolves (Level C fallback)."""

    @abstractmethod
    def team_logo(self, team_external_id: str) -> Asset:
        """Return an asset representing a team. Always resolves (Level C fallback)."""

    @abstractmethod
    def team_color(self, team_external_id: str) -> str:
        """Hex color assigned to a team (Level C uses this for accents)."""


# ---------------------------------------------------------------------------
# Content queue — storage for pipeline output (dedup by story identity)
# ---------------------------------------------------------------------------


@runtime_checkable
class ContentQueue(Protocol):
    """Structural contract for the pipeline's content queue.

    Defined as a Protocol so the in-memory queue (domain layer) satisfies it
    without importing this module — the domain never depends on application.
    A persistent (SQL) queue in the infrastructure layer implements the same
    surface. Items are the domain ``ContentItem``; the queue deduplicates by
    ``item.story.identity_key`` so the same story is never queued twice.
    """

    def add(self, item: Any) -> bool: ...

    def update(self, item: Any) -> None: ...

    def get(self, content_id: str) -> Optional[Any]: ...

    def by_story_identity(self, identity_key: str) -> Optional[Any]: ...

    def list_by_status(self, status: Any) -> List[Any]: ...

    def all(self) -> List[Any]: ...


# ---------------------------------------------------------------------------
# Publisher — channel-agnostic delivery of an approved content item
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PublishResult:
    """Outcome of a publish attempt. ``dry_run`` is True when nothing actually
    left the system (the default posture while the engine is young)."""

    channel: str
    external_ref: Optional[str]
    dry_run: bool
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "external_ref": self.external_ref,
            "dry_run": self.dry_run,
            "detail": self.detail,
        }


class Publisher(ABC):
    """Delivers a content item to a channel. The Content Engine never knows
    how Instagram/Web/etc. work — it hands an item to a Publisher and records
    the ``PublishResult``. Concrete channel adapters implement this later."""

    @property
    @abstractmethod
    def channel(self) -> str:
        """Channel identifier, e.g. 'dry_run', 'instagram', 'web'."""

    @abstractmethod
    def publish(self, item: Any) -> PublishResult:
        """Publish the item. Must not raise for an expected failure — return a
        PublishResult describing it. Raising is reserved for programmer error."""
