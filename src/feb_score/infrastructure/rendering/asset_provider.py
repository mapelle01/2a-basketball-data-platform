"""Statistical asset provider — the no-photo fallback (FEB SCORE! identity).

Implements the ``AssetProvider`` interface using deterministic derivations from
entity ids. There are NO team colors in this identity: the palette is strictly
black / white / greys with red as an accent (never a per-team color). Teams and
players are distinguished by their initials in white/grey, and the renderer uses
red only to mark a winner or a key stat. ``team_color`` therefore returns a
neutral from the official palette, kept only to satisfy the interface.

Level A (official photos) and Level B (contextual imagery) plug in as
alternative implementations of the same interface without touching templates.
"""

from __future__ import annotations

from ...application.content.interfaces import (
    ASSET_LEVEL_STATISTICAL,
    Asset,
    AssetProvider,
)
from .design_system import Color


class StatisticalAssetProvider(AssetProvider):
    """No-photo fallback. Every asset is generated deterministically from ids."""

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
        # No per-team colors in this identity. Neutral by default; the renderer
        # applies red as an accent based on context (winner / key stat), not team.
        return Color.WHITE


def _initials_from_id(entity_id: str) -> str:
    digits = "".join(c for c in entity_id if c.isdigit())
    if len(digits) >= 4:
        return digits[-2:]
    if entity_id:
        return entity_id[:2].upper()
    return "--"
