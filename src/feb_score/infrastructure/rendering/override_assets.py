"""Override-first imagery.

Sits in front of the FEB provider: if an operator has uploaded a replacement
for a player photo or team crest, it wins; otherwise the request falls through
to whatever the wrapped provider resolves (official FEB image, then statistical
initials). This is what makes an uploaded image actually appear on a card.

The override store hands back raw bytes; the SVG must be self-contained, so
they are embedded as a data URI exactly as the FEB provider does.
"""

from __future__ import annotations

import base64
from typing import Any, Optional

from ...application.content.interfaces import (
    ASSET_LEVEL_OFFICIAL,
    Asset,
    AssetProvider,
)


class OverrideAssetProvider(AssetProvider):
    def __init__(self, repo: Any, fallback: AssetProvider) -> None:
        self._repo = repo
        self._fallback = fallback

    def _override_uri(self, kind: str, external_id: str) -> Optional[str]:
        try:
            ov = self._repo.get(kind, external_id)
        except Exception:  # noqa: BLE001 — a store hiccup must never fail a render
            return None
        if ov is None:
            return None
        return f"data:{ov.content_type};base64," + base64.b64encode(ov.image).decode("ascii")

    def player_photo(self, player_external_id: str) -> Asset:
        uri = self._override_uri("player", player_external_id)
        if uri is not None:
            return Asset(kind="player_photo", level=ASSET_LEVEL_OFFICIAL, payload=uri,
                         payload_type="data_uri", source="operator-override")
        return self._fallback.player_photo(player_external_id)

    def team_logo(self, team_external_id: str) -> Asset:
        uri = self._override_uri("team", team_external_id)
        if uri is not None:
            return Asset(kind="team_logo", level=ASSET_LEVEL_OFFICIAL, payload=uri,
                         payload_type="data_uri", source="operator-override")
        return self._fallback.team_logo(team_external_id)

    def team_color(self, team_external_id: str) -> str:
        return self._fallback.team_color(team_external_id)


class MediaAssetProvider(AssetProvider):
    """Media library on top of an override/FEB fallback.

    Picks the primary APPROVED photo out of the media library when one exists;
    otherwise falls through. This is what lets the operator promote/approve a
    new photo without touching the legacy override, and the renderer just
    honours it. Bytes → data URI, same as the other providers, so the SVG stays
    self-contained.
    """

    def __init__(self, repo: Any, fallback: AssetProvider) -> None:
        self._repo = repo
        self._fallback = fallback

    def _selected_uri(self, kind: str, external_id: str) -> Optional[str]:
        try:
            meta = self._repo.select(kind, external_id)
            if meta is None:
                return None
            img = self._repo.get_image(meta.asset_id)
            if img is None:
                return None
        except Exception:  # noqa: BLE001 — a store hiccup must never fail a render
            return None
        return f"data:{img.content_type};base64," + base64.b64encode(img.image).decode("ascii")

    def player_photo(self, player_external_id: str) -> Asset:
        uri = self._selected_uri("player", player_external_id)
        if uri is not None:
            return Asset(kind="player_photo", level=ASSET_LEVEL_OFFICIAL, payload=uri,
                         payload_type="data_uri", source="media-library")
        return self._fallback.player_photo(player_external_id)

    def team_logo(self, team_external_id: str) -> Asset:
        uri = self._selected_uri("team", team_external_id)
        if uri is not None:
            return Asset(kind="team_logo", level=ASSET_LEVEL_OFFICIAL, payload=uri,
                         payload_type="data_uri", source="media-library")
        return self._fallback.team_logo(team_external_id)

    def team_color(self, team_external_id: str) -> str:
        return self._fallback.team_color(team_external_id)
