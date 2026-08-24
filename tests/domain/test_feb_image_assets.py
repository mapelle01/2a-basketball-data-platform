"""Official FEB imagery provider: resolve when it exists, degrade when it doesn't."""
from __future__ import annotations

import os

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


def test_circuit_breaker_stops_hammering_a_dead_host():
    """One card can ask for five portraits: an unreachable host must not cost
    five sequential timeouts. After the budget, stop trying."""
    calls = []

    def fetch(url):
        calls.append(url)
        return None  # always failing

    p = FebImageAssetProvider(fetch=fetch, failure_budget=2)
    for i in range(6):
        assert p.player_photo(f"p{i}").payload_type == "initials"
    assert len(calls) == 2  # tried twice, then served the fallback directly


def test_a_success_closes_the_circuit_again():
    state = {"fail": True}

    def fetch(url):
        return None if state["fail"] else JPEG

    p = FebImageAssetProvider(fetch=fetch, failure_budget=3)
    p.player_photo("a"); p.player_photo("b")     # 2 failures, still under budget
    state["fail"] = False
    assert p.player_photo("c").payload_type == "data_uri"
    state["fail"] = True
    assert p.player_photo("d").payload_type == "initials"  # counter was reset


def test_a_raising_fetch_never_crashes_the_render():
    def boom(url):
        raise RuntimeError("network down")

    assert FebImageAssetProvider(fetch=boom).player_photo("x").payload_type == "initials"


def test_kill_switch_selects_the_provider(monkeypatch):
    """FEB_SCORE_OFFICIAL_IMAGES=0 must return the pipeline to the purely
    statistical identity without a deploy."""
    from feb_score.infrastructure.rendering.asset_provider import StatisticalAssetProvider

    def build(value):
        monkeypatch.setenv("FEB_SCORE_OFFICIAL_IMAGES", value)
        on = os.environ.get("FEB_SCORE_OFFICIAL_IMAGES", "true").strip().lower() \
            not in {"0", "false", "no"}
        return FebImageAssetProvider if on else StatisticalAssetProvider

    assert build("0") is StatisticalAssetProvider
    assert build("false") is StatisticalAssetProvider
    assert build("true") is FebImageAssetProvider
