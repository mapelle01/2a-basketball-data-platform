"""Official FEB imagery (Level A) — player photos and team crests.

FEB serves both from URLs built out of the ids we already carry, with no token
and no scraping:

    player photo : https://imagenes.feb.es/Foto.aspx?c=<player_external_id>
    team crest   : https://imagenes.feb.es/Imagen.aspx?i=<team_external_id>&ti=1

A missing image answers 404, which is a clean "no asset" signal: this provider
then DELEGATES to the statistical fallback (initials) rather than inventing one.
Images are JPEG (no alpha), so they suit a framed portrait/crest slot; a
transparent cut-out would need a separate matting step.

Fetched images are embedded as data URIs because the rendered SVG must be
self-contained, and cached in-process so one round does not refetch the same
player. Every failure mode — timeout, 404, unexpected content type, oversized
payload — degrades to the fallback: rendering a card must never fail, and must
never block on the network longer than ``TIMEOUT_SECONDS``.
"""

from __future__ import annotations

import base64
import urllib.error
import urllib.request
from typing import Dict, Optional, Tuple

from ...application.content.interfaces import (
    ASSET_LEVEL_OFFICIAL,
    Asset,
    AssetProvider,
)
from .asset_provider import StatisticalAssetProvider

PLAYER_PHOTO_URL = "https://imagenes.feb.es/Foto.aspx?c={player_external_id}"
TEAM_CREST_URL = "https://imagenes.feb.es/Imagen.aspx?i={team_external_id}&ti=1"
USER_AGENT = "feb-score-assets/1.0"
TIMEOUT_SECONDS = 8
MAX_BYTES = 512 * 1024  # a portrait is ~10-25 KB; anything larger is not one
FAILURE_BUDGET = 3      # consecutive failures before the provider stops trying


def _data_uri(raw: bytes, content_type: str) -> str:
    return f"data:{content_type};base64," + base64.b64encode(raw).decode("ascii")


class FebImageAssetProvider(AssetProvider):
    """Official images with a graceful fall back to the statistical identity."""

    def __init__(self, *, fallback: Optional[AssetProvider] = None,
                 fetch=None, timeout: int = TIMEOUT_SECONDS,
                 failure_budget: int = FAILURE_BUDGET) -> None:
        self._fallback = fallback or StatisticalAssetProvider()
        self._timeout = timeout
        self._fetch = fetch or self._http_get
        self._cache: Dict[str, Optional[str]] = {}
        # Circuit breaker: one card can ask for five portraits, so an unreachable
        # image host would otherwise cost five sequential timeouts per card. After
        # this many CONSECUTIVE failures the provider stops trying and serves the
        # fallback; a single success closes it again.
        self._failure_budget = failure_budget
        self._consecutive_failures = 0

    @property
    def _open_circuit(self) -> bool:
        return self._consecutive_failures >= self._failure_budget

    # ------------------------------------------------------------------ http
    def _http_get(self, url: str) -> Optional[Tuple[bytes, str]]:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
                if resp.status != 200:
                    return None
                ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
                if not ctype.startswith("image/"):
                    return None
                raw = resp.read(MAX_BYTES + 1)
                if not raw or len(raw) > MAX_BYTES:
                    return None
                return raw, ctype
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            return None  # 404 = no official image; anything else = unavailable now

    def _uri(self, url: str) -> Optional[str]:
        if url in self._cache:
            return self._cache[url]
        if self._open_circuit:
            return None  # host is unhealthy: serve the fallback, don't wait on it
        try:
            got = self._fetch(url)
        except Exception:  # noqa: BLE001 — an injected fetch may raise; never crash a render
            got = None
        if got:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
        self._cache[url] = _data_uri(*got) if got else None
        return self._cache[url]

    # -------------------------------------------------------------- provider
    def player_photo(self, player_external_id: str) -> Asset:
        uri = self._uri(PLAYER_PHOTO_URL.format(player_external_id=player_external_id))
        if uri is None:
            return self._fallback.player_photo(player_external_id)
        return Asset(kind="player_photo", level=ASSET_LEVEL_OFFICIAL, payload=uri,
                     payload_type="data_uri", source="feb-official")

    def team_logo(self, team_external_id: str) -> Asset:
        uri = self._uri(TEAM_CREST_URL.format(team_external_id=team_external_id))
        if uri is None:
            return self._fallback.team_logo(team_external_id)
        return Asset(kind="team_logo", level=ASSET_LEVEL_OFFICIAL, payload=uri,
                     payload_type="data_uri", source="feb-official")

    def team_color(self, team_external_id: str) -> str:
        # Unchanged by design: this identity has no per-team colours.
        return self._fallback.team_color(team_external_id)
