"""FEB SCORE! — Template compositions.

Templates are no longer static SVG files with placeholders: they are functions
that assemble Component Library pieces on an official background, in a vertical
flow with system spacing. Same data contract the pipeline already produces
(``{story, copy, assets, display, meta}``); the output is a full 1080x1350 SVG.

Template anatomy (template board): HEADER → MAIN CONTENT → SECONDARY DATA →
BRANDING. Each maps to a component.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from . import components as C
from .design_system import (
    Background,
    Brand,
    Canvases,
    Color,
    Font,
    FontSize,
    FontWeight,
    LetterSpacing,
    Line,
    Spacing,
)

CANVAS = Canvases.POST_PORTRAIT
MARGIN = CANVAS.safe_margin
CONTENT_X = MARGIN
CONTENT_W = CANVAS.width - 2 * MARGIN
FOOTER_Y = CANVAS.height - MARGIN - 40


# ---------------------------------------------------------------------------
# Backgrounds
# ---------------------------------------------------------------------------


def _background(name: str) -> str:
    base = Background.BASE.get(name, Color.BLACK)
    parts = [C.rect(0, 0, CANVAS.width, CANVAS.height, base)]
    if name == Background.BLACK_RED_ACCENT:
        # A single solid red diagonal accent in the top-right — no gradient.
        parts.append(
            f'<polygon points="{CANVAS.width - 220},0 {CANVAS.width},0 {CANVAS.width},220"'
            f' fill="{Color.RED}"/>'
        )
    if name == Background.BLACK_STRUCTURAL:
        # Faint structural rule near the top.
        parts.append(C.hline(MARGIN, 150, CONTENT_W, weight=Line.THIN, color=Color.INK))
    return "".join(parts)


def _svg_document(body: str, favicon_bg: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS.width} {CANVAS.height}"'
        f' width="{CANVAS.width}" height="{CANVAS.height}" font-family="{Font.FAMILY}">'
        f'{_background(favicon_bg)}{body}</svg>'
    )


# ---------------------------------------------------------------------------
# Template: MATCH FINAL
# ---------------------------------------------------------------------------


def render_match_final(data: Dict[str, Any]) -> str:
    facts = data["story"]["facts"]
    display = data.get("display", {})
    round_number = data["story"].get("round_number")
    home_score = facts.get("home_score", 0)
    away_score = facts.get("away_score", 0)
    home_win = home_score >= away_score

    body: List[str] = []
    y = MARGIN

    hdr, h = C.match_header(
        CONTENT_X, y, CONTENT_W,
        competition="Segunda FEB", round_label=f"Jornada {round_number}",
        status="FINAL",
    )
    body.append(hdr); y += h + Spacing.BLOCK

    sb, h = C.scoreboard(
        CONTENT_X, y, CONTENT_W,
        home=C.TeamSide(display.get("home_team", "Local"), home_score, is_winner=home_win),
        away=C.TeamSide(display.get("away_team", "Visitante"), away_score, is_winner=not home_win),
        variant="hero",
    )
    body.append(sb); y += h + Spacing.BLOCK

    # Secondary data: margin + season, as an inline stat row.
    margin = abs(home_score - away_score)
    sd, h = C.stat_block(
        CONTENT_X, y, CONTENT_W,
        primary=f"+{margin}", primary_label="Diferencia",
        secondary_stats=[(str(round_number), "Jornada"), (str(data["story"].get("season_code", "")), "Temporada")],
        variant="compact",
    )
    body.append(sd)

    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W,
                           competition="Segunda FEB", season=data["story"].get("season_code"))
    body.append(ft)
    return _svg_document("".join(body), Background.BLACK_RED_ACCENT)


# ---------------------------------------------------------------------------
# Template: PLAYER OF THE ROUND
# ---------------------------------------------------------------------------


def render_player_of_round(data: Dict[str, Any]) -> str:
    facts = data["story"]["facts"]
    display = data.get("display", {})
    assets = data.get("assets", {})
    round_number = data["story"].get("round_number")

    body: List[str] = []
    y = MARGIN
    hdr, h = C.match_header(
        CONTENT_X, y, CONTENT_W,
        competition="Jugador de la jornada", round_label=f"Jornada {round_number}",
    )
    body.append(hdr); y += h + Spacing.XL

    secondary = [
        (str(facts.get("rebounds", 0)), "REB"),
        (str(facts.get("assists", 0)), "AST"),
    ]
    ph, h = C.player_hero(
        CONTENT_X, y, CONTENT_W,
        name=display.get("player", "Jugador"),
        team=display.get("team", ""),
        primary_stat=str(facts.get("points", 0)), primary_label="PTS",
        secondary_stats=secondary,
        initials=assets.get("player_initials"),
        badge="MVP",
    )
    body.append(ph)

    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W,
                           competition="Segunda FEB", season=data["story"].get("season_code"))
    body.append(ft)
    return _svg_document("".join(body), Background.BLACK_CLEAN)


# ---------------------------------------------------------------------------
# Template: ROUND RECAP
# ---------------------------------------------------------------------------


def render_round_recap(data: Dict[str, Any]) -> str:
    facts = data["story"]["facts"]
    display = data.get("display", {})
    round_number = data["story"].get("round_number")

    body: List[str] = []
    y = MARGIN
    hdr, h = C.match_header(
        CONTENT_X, y, CONTENT_W,
        competition="Segunda FEB", round_label=f"Temporada {data['story'].get('season_code','')}",
    )
    body.append(hdr); y += h + Spacing.XL

    # Hero: giant round number
    body.append(C.text(CONTENT_X, y + 60, "JORNADA", size=FontSize.LABEL,
                       weight=FontWeight.LABEL, fill=Color.GREY, tracking=LetterSpacing.EYEBROW, upper=True))
    body.append(C.text(CONTENT_X, y + 230, str(round_number), size=FontSize.HERO + 60,
                       weight=FontWeight.HERO, fill=Color.WHITE, tracking=LetterSpacing.HERO))
    y += 290

    # Secondary data grid: 3 headline stats
    sd, h = C.stat_block(
        CONTENT_X, y, CONTENT_W,
        primary=str(facts.get("matches_played", 0)), primary_label="Partidos",
        secondary_stats=[
            (str(facts.get("top_scorer_points", "—")), "Top pts"),
            (f"+{facts.get('biggest_win_margin', 0)}", "Mayor dif."),
            (str(facts.get("closest_game_margin", "—")), "Más ajustado"),
        ],
        variant="standard",
    )
    body.append(sd); y += h + Spacing.XL

    # Top scorer line
    top = display.get("top_scorer", "—")
    if top and top != "—":
        body.append(C.hline(CONTENT_X, y, CONTENT_W, weight=Line.THIN, color=Color.INK))
        body.append(C.text(CONTENT_X, y + 40, "MÁXIMO ANOTADOR", size=FontSize.MICRO,
                           weight=FontWeight.LABEL, fill=Color.GREY, tracking=LetterSpacing.CAPS, upper=True))
        body.append(C.text(CONTENT_X, y + 80, top.upper(), size=FontSize.H3,
                           weight=FontWeight.TITLE, fill=Color.WHITE, upper=True))

    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W,
                           competition="Segunda FEB", season=data["story"].get("season_code"))
    body.append(ft)
    return _svg_document("".join(body), Background.STATISTICS_DARK)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_RENDERERS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "match_final": render_match_final,
    "player_of_round": render_player_of_round,
    "round_recap": render_round_recap,
}


def render_template(template_id: str, data: Dict[str, Any]) -> str:
    fn = _RENDERERS.get(template_id)
    if fn is None:
        raise KeyError(f"no component template for {template_id!r}")
    return fn(data)


def has_template(template_id: str) -> bool:
    return template_id in _RENDERERS
