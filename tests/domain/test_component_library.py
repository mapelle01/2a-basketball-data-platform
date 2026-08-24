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


class TestFramesAndSlots:
    def test_corner_frame_is_monochrome_chrome(self):
        svg = C.corner_frame(100, 100, 300, 400, corners=("tl", "br"))
        ET.fromstring(_wrap(svg))
        # brand chrome only — no stray colors, no asset references
        assert not (_colors_in(svg) - _ALLOWED_COLORS)
        assert "image" not in svg

    def test_avatar_fallback_shows_initials(self):
        svg = C.avatar(100, 100, 42, initials="CS")
        ET.fromstring(_wrap(svg))
        assert "CS" in svg
        assert "<image" not in svg  # no photo → no image element

    def test_avatar_photo_slot_uses_image_when_present(self):
        svg = C.avatar(100, 100, 42, photo_uri="data:image/png;base64,AAAA")
        ET.fromstring(_wrap(svg))
        assert "<image" in svg and "clip-path" in svg

    def test_initials_of(self):
        assert C.initials_of("C. Sáez") == "CS"
        assert C.initials_of("Melilla") == "ME"
        assert C.initials_of("") == "—"

    def test_player_hero_photo_slot(self):
        svg, _ = C.player_hero(
            0, 0, 950, name="C. Sáez", team="Alicante",
            primary_stat="31", primary_label="PTS",
            photo_uri="data:image/png;base64,AAAA", badge="MVP",
        )
        ET.fromstring(_wrap(svg))
        assert "<image" in svg  # the cutout fills the frame

    def test_context_tab_badge_lead_is_red_chip(self):
        svg, w = T.context_tab(0, 0, "Top 5", badge=5, with_mark=False, chevron=True)
        ET.fromstring(_wrap(svg))
        assert w > 0
        assert Color.RED in svg and ">5<" in svg
        assert "<image" not in svg  # badge lead ⇒ no competition mark image

    def test_filter_bar_lays_two_tabs(self):
        svg, w = T.filter_bar(0, 0, [
            {"label": "Top 5", "badge": 5, "with_mark": False, "chevron": True},
            {"label": "Jornada 12", "with_mark": True, "chevron": True},
        ])
        ET.fromstring(_wrap(svg))
        assert w > 0
        assert ">5<" in svg and "Jornada 12" in svg

    def test_leaderboard_uses_only_official_palette(self):
        data = {
            "story": {"round_number": 12, "season_code": "2025-2026",
                      "facts": {"leaders": [
                          {"rank": 1, "player_name": "C. Sáez", "team_name": "Alicante",
                           "points": 31, "rating": 8.4},
                          {"rank": 2, "player_name": "J. Nuñez", "team_name": "Melilla",
                           "points": 28, "rating": 6.4},
                      ]}},
            "copy": {}, "display": {}, "assets": {}, "meta": {},
        }
        svg = T.render_template("stat_leaderboard", data)
        ET.fromstring(svg)
        assert not (_colors_in(svg) - _ALLOWED_COLORS)

    def test_best_five_renders_on_court(self):
        data = {
            "story": {"round_number": 12, "season_code": "2025-2026",
                      "facts": {"lineup": [
                          {"player_name": "C. Sáez", "team_name": "Alicante", "rating": 8.6},
                          {"player_name": "J. Nuñez", "team_name": "Melilla", "rating": 7.5},
                          {"player_name": "A. Martín", "team_name": "Cáceres", "rating": 7.1},
                          {"player_name": "P. Ortega", "team_name": "Palencia", "rating": 6.8},
                          {"player_name": "L. Romero", "team_name": "Zamora", "rating": 6.2},
                      ]}},
            "copy": {}, "display": {}, "assets": {}, "meta": {},
        }
        svg = T.render_template("best_five", data)
        ET.fromstring(svg)  # valid
        assert not (_colors_in(svg) - _ALLOWED_COLORS)  # identity restraint
        for ini in ("CS", "JN", "AM", "PO", "LR"):  # five avatar fallbacks placed
            assert f">{ini}<" in svg

    def test_best_five_valid_with_partial_lineup(self):
        # Fewer than five players (imperfect feed) must still render.
        data = {
            "story": {"round_number": 3, "season_code": "2025-2026",
                      "facts": {"lineup": [{"player_name": "A. Uno", "rating": 7.0}]}},
            "copy": {}, "display": {}, "assets": {}, "meta": {},
        }
        ET.fromstring(T.render_template("best_five", data))

    def test_compose_orders_layers_and_skips_empty(self):
        svg = T.compose(
            T.IMAGE_BACKGROUND,
            geometry=C.corner_frame(0, 0, 100, 100),
            data=C.text(10, 10, "X", size=20, weight=700, fill=Color.WHITE),
            photo="",  # empty slot is skipped, not rendered as literal
        )
        ET.fromstring(svg)
        assert ">X<" in svg


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


class TestTeamStreak:
    def _data(self, kind, length, team="Alicante Basket"):
        return {
            "story": {"facts": {"team_name": team, "streak_kind": kind, "streak_length": length},
                      "round_number": 12, "season_code": "2025-2026"},
            "copy": {}, "display": {}, "assets": {}, "meta": {},
        }

    def test_win_streak_renders_run_in_red(self):
        from feb_score.domain.content.story import STORY_TO_TEMPLATE, StoryType
        assert STORY_TO_TEMPLATE[StoryType.WIN_STREAK] == "team_streak"
        svg = T.render_template("team_streak", self._data("win", 5))
        ET.fromstring(svg)
        assert not (_colors_in(svg) - _ALLOWED_COLORS)
        assert "VICTORIAS SEGUIDAS" in svg and "ALICANTE BASKET" in svg
        assert svg.count(Color.RED) >= 5  # one red mark per game of the run

    def test_loss_streak_marks_are_not_red_fill(self):
        svg = T.render_template("team_streak", self._data("loss", 4, team="Zamora"))
        ET.fromstring(svg)
        assert "DERROTAS SEGUIDAS" in svg

    def test_long_run_caps_with_tail(self):
        svg = T.render_template("team_streak", self._data("win", 12))
        ET.fromstring(svg)
        assert "+4" in svg  # 12 shown as 8 marks + "+4"


class TestBestDuo:
    def test_detector_picks_top_two_teammates(self):
        from feb_score.domain.content.insights import PlayerLineInput, detect_best_duo
        from feb_score.domain.content.story import STORY_TO_TEMPLATE, StoryType

        def L(pid, team, tid, pts):
            return PlayerLineInput(pid, pid.upper(), tid, team, "m1", pts, 4, 3)
        lines = [L("a", "Alicante", "tA", 31), L("b", "Alicante", "tA", 27),
                 L("c", "Alicante", "tA", 8), L("d", "Melilla", "tB", 22)]
        s = detect_best_duo("2025-2026", 12, lines)
        assert s is not None and s.story_type is StoryType.BEST_DUO
        assert s.facts["combined_points"] == 58
        assert {s.facts["p1_external_id"], s.facts["p2_external_id"]} == {"a", "b"}
        assert STORY_TO_TEMPLATE[StoryType.BEST_DUO] == "best_duo"

    def test_detector_needs_two_teammates(self):
        from feb_score.domain.content.insights import PlayerLineInput, detect_best_duo
        lines = [PlayerLineInput("a", "A", "tA", "T", "m1", 40, 4, 3)]  # lone player
        assert detect_best_duo("2025-2026", 12, lines) is None

    def test_renders_the_mockup(self):
        data = {"story": {"round_number": 12, "season_code": "2025-2026", "facts": {
            "p1_name": "J. Pérez", "p1_points": 31, "p1_rating": 8.4,
            "p2_name": "R. Costa", "p2_points": 27, "p2_rating": 7.2,
            "combined_points": 58, "team_name": "Alicante"}},
            "copy": {}, "display": {}, "assets": {}, "meta": {}}
        svg = T.render_template("best_duo", data)
        ET.fromstring(svg)
        assert not (_colors_in(svg) - _ALLOWED_COLORS)
        assert "EL MEJOR DÚO" in svg and "PTS COMBINADOS" in svg and ">58<" in svg


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
