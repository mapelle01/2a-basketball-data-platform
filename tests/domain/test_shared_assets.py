"""Shared assets are referenced, not embedded, in the stored card.

The background alone was 96% of a 1.85 MB card and is byte-identical in every
row; storing it per card is what made the queue grow ~273 MB per season.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from feb_score.infrastructure.rendering.component_templates import (
    SHARED_ASSET_SCHEME,
    inline_shared_assets,
    render_template,
)

DATA = {
    "story": {"facts": {"player_name": "X", "points": 24, "rebounds": 9,
                        "assists": 5, "rating": 8.3},
              "round_number": 24, "season_code": "2024-2025",
              "story_type": "player_of_round"},
    "display": {"player": "J. JUANOLA", "team": "MATARÓ"},
    "assets": {"player_initials": "JM"}, "copy": {}, "meta": {},
}


def _card():
    return render_template("player_of_round", DATA)


def test_stored_card_carries_references_not_megabytes():
    svg = _card()
    assert SHARED_ASSET_SCHEME in svg
    assert "data:image/png;base64," not in svg   # the heavy shared PNGs are out
    assert len(svg) < 100_000, f"stored card should be tiny, got {len(svg)}"


def test_served_card_is_self_contained_again():
    svg = _card()
    served = inline_shared_assets(svg)
    assert SHARED_ASSET_SCHEME not in served
    assert "data:image/png;base64," in served
    assert len(served) > 10 * len(svg)          # the assets really came back
    ET.fromstring(served)                        # and it is still valid SVG


def test_inlining_is_idempotent_and_safe_on_plain_svg():
    served = inline_shared_assets(_card())
    assert inline_shared_assets(served) == served
    assert inline_shared_assets("<svg/>") == "<svg/>"


def test_saving_is_the_point():
    svg = _card()
    served = inline_shared_assets(svg)
    saved = 1 - len(svg) / len(served)
    assert saved > 0.95, f"expected >95% smaller when stored, got {saved:.1%}"
