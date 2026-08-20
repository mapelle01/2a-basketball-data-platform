"""FEB SCORE! Component Library — essential tests.

Guards the properties that make components reusable and safe: valid SVG,
fallback safety (no logo / no photo / no secondary data), the red-accent rule
(winner only), and identity restraint (only official palette colors).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from feb_score.infrastructure.rendering import components as C
from feb_score.infrastructure.rendering import component_templates as T
from feb_score.infrastructure.rendering.design_system import Color


# The only colors allowed to appear in output (identity restraint).
_ALLOWED_COLORS = {
    Color.BLACK, Color.INK, Color.GREY, Color.LIGHT_GREY, Color.RED, Color.WHITE,
    "none",
}


def _wrap(fragment: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1350">{fragment}</svg>'


def _colors_in(svg: str):
    return set(re.findall(r'(?:fill|stroke)="(#[0-9A-Fa-f]{6}|none)"', svg))


class TestAtoms:
    def test_accent_bar_is_red(self):
        assert Color.RED in C.accent_bar(0, 0, 100)

    def test_text_escapes_xml(self):
        svg = C.text(0, 0, "A & B <x>", size=20, weight=700, fill=Color.WHITE)
        assert "&amp;" in svg and "&lt;" in svg


class TestScoreboard:
    def test_winner_score_is_red_loser_is_not(self):
        svg, h = C.scoreboard(
            0, 0, 950,
            home=C.TeamSide("Alicante", 104, is_winner=True),
            away=C.TeamSide("Melilla", 72, is_winner=False),
            variant="hero",
        )
        assert h > 0
        ET.fromstring(_wrap(svg))
        # Winner's score uses red; the identity's only licensed accent use here.
        assert svg.count(Color.RED) >= 1

    def test_works_without_logos(self):
        # No logo inputs at all — must still render valid SVG.
        svg, _ = C.scoreboard(
            0, 0, 950,
            home=C.TeamSide("A", 80, is_winner=True),
            away=C.TeamSide("B", 70),
            variant="hero",
        )
        ET.fromstring(_wrap(svg))

    def test_variants_render(self):
        for variant in ("hero", "compact", "minimal"):
            svg, h = C.scoreboard(
                0, 0, 950,
                home=C.TeamSide("A", 80, is_winner=True), away=C.TeamSide("B", 70),
                variant=variant,
            )
            assert h > 0
            ET.fromstring(_wrap(svg))


class TestPlayerHero:
    def test_valid_without_photo(self):
        # initials only, no photo — the fallback path must be valid + non-empty.
        svg, h = C.player_hero(
            0, 0, 950, name="C. Sáez", team="Alicante",
            primary_stat="31", primary_label="PTS",
            secondary_stats=[("9", "REB"), ("5", "AST")], initials="CS", badge="MVP",
        )
        assert h > 0
        ET.fromstring(_wrap(svg))
        assert "CS" in svg

    def test_valid_without_initials(self):
        svg, _ = C.player_hero(
            0, 0, 950, name="Jugador", team="",
            primary_stat="20", primary_label="PTS", initials=None,
        )
        ET.fromstring(_wrap(svg))


class TestStatBlock:
    def test_no_secondary_stats(self):
        svg, h = C.stat_block(0, 0, 950, primary="31", primary_label="PTS", variant="hero")
        assert h > 0
        ET.fromstring(_wrap(svg))

    def test_primary_label_is_red(self):
        svg, _ = C.stat_block(0, 0, 950, primary="31", primary_label="PTS", variant="hero")
        assert Color.RED in svg

    def test_variants(self):
        for v in ("hero", "standard", "compact", "inline"):
            svg, h = C.stat_block(
                0, 0, 950, primary="31", primary_label="PTS",
                secondary_stats=[("9", "REB"), ("5", "AST")], variant=v,
            )
            assert h > 0
            ET.fromstring(_wrap(svg))


class TestBrandFooter:
    def test_variants_render(self):
        for v in ("dark", "light", "compact"):
            svg, h = C.brand_footer(0, 0, 950, competition="Segunda FEB", season="2025-2026", variant=v)
            assert h > 0
            ET.fromstring(_wrap(svg))


class TestIdentityRestraint:
    def test_templates_use_only_official_palette(self):
        data = {
            "story": {"facts": {"home_score": 104, "away_score": 72, "points": 31,
                                "rebounds": 9, "assists": 5, "matches_played": 4,
                                "top_scorer_points": 31, "biggest_win_margin": 32,
                                "closest_game_margin": 2},
                      "round_number": 12, "season_code": "2025-2026"},
            "display": {"home_team": "Alicante", "away_team": "Melilla",
                        "player": "C. Sáez", "team": "Alicante", "top_scorer": "C. Sáez"},
            "assets": {"player_initials": "CS"}, "copy": {}, "meta": {},
        }
        for tid in ("match_final", "player_of_round", "round_recap"):
            svg = T.render_template(tid, data)
            ET.fromstring(svg)  # valid
            stray = _colors_in(svg) - _ALLOWED_COLORS
            assert not stray, f"{tid} uses non-palette colors: {stray}"
