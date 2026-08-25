"""SVG → PNG, the step that makes a card publishable.

The behaviour worth pinning here is not "it produces a PNG" — it is that the
image does not depend on the machine it was produced on. Fonts come from the
vendored directory with system fonts off, so the card a reviewer approves is
the card that gets posted.
"""

from __future__ import annotations

import struct
import subprocess

import pytest

from feb_score.infrastructure.rendering import rasterizer
from feb_score.infrastructure.rendering.rasterizer import (
    FONTS_DIR,
    RasterizationFailed,
    RasterizerUnavailable,
    rasterize_png,
)

needs_resvg = pytest.mark.skipif(
    not rasterizer.available(), reason="resvg is not installed on this machine"
)

_TEXT_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
    '<rect width="200" height="100" fill="#0B0A0A"/>'
    '<text x="10" y="60" font-family="Inter" font-weight="900" font-size="40" '
    'fill="#fff">FEB</text></svg>'
)


def _dimensions(png: bytes):
    return struct.unpack(">II", png[16:24])


@needs_resvg
class TestRasterisation:
    def test_produces_a_png_at_the_requested_size(self):
        png = rasterize_png(_TEXT_SVG, width=400, height=200)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert _dimensions(png) == (400, 200)

    def test_is_deterministic(self):
        """Same input, same bytes — otherwise 'I checked the image' means
        nothing about what gets published."""
        assert rasterize_png(_TEXT_SVG) == rasterize_png(_TEXT_SVG)

    def test_the_vendored_weights_are_actually_distinct(self):
        """Why resvg and not cairosvg: cairosvg rendered all five weights
        identically, collapsing the hierarchy the design system is built on.
        Black on Regular must not be the same picture."""
        black = rasterize_png(_TEXT_SVG, width=400, height=200)
        regular = rasterize_png(
            _TEXT_SVG.replace('font-weight="900"', 'font-weight="400"'),
            width=400, height=200,
        )
        assert black != regular

    def test_refuses_input_that_is_not_svg(self):
        with pytest.raises(RasterizationFailed):
            rasterize_png("this is not an svg at all")


class TestIsolation:
    def test_every_vendored_weight_is_present(self):
        """The card names five weights; a missing file degrades silently to a
        substituted face rather than failing."""
        weights = {"Regular", "SemiBold", "Bold", "ExtraBold", "Black"}
        shipped = {p.stem.split("-")[-1] for p in FONTS_DIR.glob("Inter-*.ttf")}
        assert weights <= shipped

    @needs_resvg
    def test_system_fonts_are_switched_off_and_the_sandbox_is_empty(self, monkeypatch):
        """The two flags that make output machine-independent: the host's fonts
        cannot leak in, and no relative path in an SVG resolves to a real file."""
        from pathlib import Path

        seen = {}
        real_run = subprocess.run

        def spy(args, **kwargs):
            args = list(args)
            seen["args"] = args
            # The sandbox only exists for the duration of the call, so it has to
            # be inspected here rather than after.
            resources = args[args.index("--resources-dir") + 1]
            seen["sandbox_entries"] = list(Path(resources).iterdir())
            return real_run(args, **kwargs)

        monkeypatch.setattr(rasterizer.subprocess, "run", spy)
        rasterize_png(_TEXT_SVG)

        args = seen["args"]
        assert "--skip-system-fonts" in args
        assert args[args.index("--use-fonts-dir") + 1] == str(FONTS_DIR)
        assert seen["sandbox_entries"] == []

    def test_a_deployment_without_resvg_says_so_instead_of_crashing(self, monkeypatch):
        monkeypatch.setattr(rasterizer, "resvg_path", lambda: None)
        with pytest.raises(RasterizerUnavailable):
            rasterize_png(_TEXT_SVG)


@needs_resvg
def test_a_real_card_rasterises_with_its_artwork():
    """End to end through the real template: the shared assets must be inlined
    first, because the rasteriser resolves nothing off disk. Without inlining
    the card still yields a valid PNG — just one missing its background."""
    from feb_score.infrastructure.rendering.component_templates import (
        inline_shared_assets,
        render_template,
    )

    data = {
        "story": {
            "facts": {"player_name": "M. SAMAR", "points": 24, "rebounds": 9,
                      "assists": 5, "rating": 8.4},
            "round_number": 24, "season_code": "2025-2026",
            "story_type": "triple_double",
        },
        "display": {"player": "M. SAMAR", "team": "Alicante"},
        "assets": {"player_initials": "MS"}, "copy": {}, "meta": {},
    }
    svg = render_template("player_of_round", data)
    with_art = rasterize_png(inline_shared_assets(svg))
    without_art = rasterize_png(svg)

    assert _dimensions(with_art) == (1080, 1350)
    assert len(with_art) > 8 * len(without_art)
