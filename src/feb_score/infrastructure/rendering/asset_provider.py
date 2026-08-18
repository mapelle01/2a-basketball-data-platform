"""Statistical asset provider — Level C fallback (no external images).

Implements the ``AssetProvider`` interface from the application layer using
deterministic derivations from entity ids. A template asks for an asset; this
provider always resolves it with a Level C placeholder (initials + a stable
team color from a curated palette). No network, no filesystem, no external
services.

Level A (official photos) and Level B (contextual imagery) plug in as
alternative implementations of the same interface without touching templates.
"""

from __future__ import annotations

from ...application.content.interfaces import (
    ASSET_LEVEL_STATISTICAL,
    Asset,
    AssetProvider,
)


# Deterministic team color from external_id. Palette curated to be visually
# distinct on the dark background of the design system.
_PALETTE = [
    "#3b82f6",  # blue
    "#ef4444",  # red
    "#10b981",  # green
    "#f59e0b",  # amber
    "#8b5cf6",  # violet
    "#ec4899",  # pink
    "#06b6d4",  # cyan
    "#84cc16",  # lime
    "#f97316",  # orange
    "#a855f7",  # purple
]


class StatisticalAssetProvider(AssetProvider):
    """Level C only. Every asset is generated deterministically from ids."""

    def player_photo(self, player_external_id: str) -> Asset:
        return Asset(
            kind="player_photo",
            level=ASSET_LEVEL_STATISTICAL,
            payload=_initials_from_id(player_external_id),
            payload_type="initials",
            source="statistical",
        )

    def team_logo(self, team_external_id: str) -> Asset:
        return Asset(
            kind="team_logo",
            level=ASSET_LEVEL_STATISTICAL,
            payload=_initials_from_id(team_external_id),
            payload_type="initials",
            source="statistical",
        )

    def team_color(self, team_external_id: str) -> str:
        return _color_from_id(team_external_id)


def _initials_from_id(entity_id: str) -> str:
    digits = "".join(c for c in entity_id if c.isdigit())
    if len(digits) >= 4:
        return digits[-2:]
    if entity_id:
        return entity_id[:2].upper()
    return "--"


def _color_from_id(entity_id: str) -> str:
    if not entity_id:
        return _PALETTE[0]
    seed = sum(ord(c) for c in entity_id)
    return _PALETTE[seed % len(_PALETTE)]
