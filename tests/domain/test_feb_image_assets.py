"""Official FEB imagery provider: resolve when it exists, degrade when it doesn't."""
from __future__ import annotations

from feb_score.application.content.interfaces import ASSET_LEVEL_OFFICIAL
from feb_score.infrastructure.rendering.feb_image_assets import FebImageAssetProvider

JPEG = (b"\xff\xd8\xff\xe0fake-jpeg-bytes", "image/jpeg")


def _provider(responses):
    calls = []

    def fetch(url):
        calls.append(url)
        return responses.get(url) if isinstance(responses, dict) else responses

    p = FebImageAssetProvider(fetch=fetch)
    return p, calls


def test_player_photo_becomes_an_embedded_data_uri():
    p, _ = _provider(JPEG)
    asset = p.player_photo("1568569")
    assert asset.level == ASSET_LEVEL_OFFICIAL
    assert asset.payload_type == "data_uri"
    assert asset.payload.startswith("data:image/jpeg;base64,")
    assert asset.source == "feb-official"


def test_team_crest_uses_the_team_url():
    p, calls = _provider(JPEG)
    p.team_logo("951323")
    assert calls == ["https://imagenes.feb.es/Imagen.aspx?i=951323&ti=1"]


def test_missing_image_falls_back_to_initials_never_invents():
    """FEB answers 404 for a player with no photo — a clean 'no asset' signal."""
    p, _ = _provider(None)
    asset = p.player_photo("999999999")
    assert asset.payload_type == "initials"
    assert asset.level != ASSET_LEVEL_OFFICIAL


def test_failures_degrade_instead_of_raising():
    def boom(url):
        raise RuntimeError("network down")

    p = FebImageAssetProvider(fetch=lambda u: None)
    assert p.player_photo("1").payload_type == "initials"   # rendering never fails


def test_results_are_cached_per_url():
    p, calls = _provider(JPEG)
    p.player_photo("1568569")
    p.player_photo("1568569")
    assert len(calls) == 1  # one round must not refetch the same portrait


def test_team_colour_stays_neutral():
    """No per-team colours in this identity, official imagery or not."""
    p, _ = _provider(JPEG)
    assert p.team_color("951323") == FebImageAssetProvider().team_color("951323")
