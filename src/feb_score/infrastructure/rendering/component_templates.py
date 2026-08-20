"""FEB SCORE! — Template compositions.

Templates are no longer static SVG files with placeholders: they are functions
that assemble Component Library pieces on an official background, in a vertical
flow with system spacing. Same data contract the pipeline already produces
(``{story, copy, assets, display, meta}``); the output is a full 1080x1350 SVG.

Template anatomy (template board): HEADER → MAIN CONTENT → SECONDARY DATA →
BRANDING. Each maps to a component.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
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


# The official brand background image (tactical blueprint). Provisional: it's
# embedded as a data URI so the SVG is self-contained and renders anywhere.
# TODO(perf): when a PNG rasterizer lands, compose the background there and keep
# the persisted SVG light instead of embedding ~1.3MB per item.
IMAGE_BACKGROUND = "tactical_blueprint"
_ASSET_DIR = Path(__file__).with_name("assets")


@lru_cache(maxsize=8)
def _asset_data_uri(name: str) -> str:
    raw = (_ASSET_DIR / f"{name}.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


# alias kept for the background call site
def _background_data_uri(name: str) -> str:
    return _asset_data_uri(name)


# The Segunda FEB competition mark (symbol only, no wordmark). RGBA, so it sits
# on the dark background cleanly. Cropped to its alpha bounding box via a nested
# viewBox so it's tight and centered wherever placed.
COMPETITION_MARK = "segunda_feb_mark"
_MARK_BBOX = (74, 16, 161, 209)  # x, y, w, h in the 316x316 source


def competition_mark(x: float, y: float, height: float) -> str:
    """Place the Segunda FEB symbol as a small competition seal."""
    bx, by, bw, bh = _MARK_BBOX
    width = height * (bw / bh)
    uri = _asset_data_uri(COMPETITION_MARK)
    return (
        f'<svg x="{x}" y="{y}" width="{width:.1f}" height="{height:.1f}"'
        f' viewBox="{bx} {by} {bw} {bh}" overflow="visible">'
        f'<image href="{uri}" x="0" y="0" width="316" height="316"/></svg>'
    )


def context_tab(x: float, y: float, label: str, *, with_mark: bool = True,
                chevron: bool = False, height: float = 60):
    """A subtle filter/context tab: [competition mark] label [▾], boxed with a
    hairline border. The editorial way to carry the league mark inside a
    ranking/criteria header (vs. the loose seal used on result posts).
    Returns (svg, width)."""
    pad = C.Spacing.MD
    mark_h = height - 24
    mark_w = mark_h * (_MARK_BBOX[2] / _MARK_BBOX[3]) if with_mark else 0
    gap = 14 if with_mark else 0
    text_w = len(label) * (C.FontSize.LABEL * 0.54)
    chev_w = 30 if chevron else 0
    w = pad * 2 + mark_w + gap + text_w + chev_w

    parts = [
        C.rect(x, y, w, height, C.Color.INK, radius=C.Radius.MD),
        f'<rect x="{x}" y="{y}" width="{w:.1f}" height="{height}" fill="none"'
        f' stroke="{C.Color.GREY}" stroke-opacity="0.4" stroke-width="{C.Line.THIN}"'
        f' rx="{C.Radius.MD}"/>',
    ]
    cx = x + pad
    if with_mark:
        parts.append(competition_mark(cx, y + 12, mark_h))
        cx += mark_w + gap
    parts.append(C.text(cx, y + height / 2 + 8, label, size=C.FontSize.LABEL,
                        weight=C.FontWeight.LABEL, fill=C.Color.WHITE))
    if chevron:
        chx, chy = x + w - pad - 6, y + height / 2
        parts.append(
            f'<path d="M{chx-8},{chy-4} L{chx},{chy+5} L{chx+8},{chy-4}" fill="none"'
            f' stroke="{C.Color.GREY}" stroke-width="{C.Line.MEDIUM}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )
    return "".join(parts), w


def _background(name: str) -> str:
    """Compose a background. The brand image background (tactical blueprint) is
    embedded and already carries the court lines, technical marks and red
    accents — so no geometric treatment is drawn over it."""
    if name == IMAGE_BACKGROUND:
        uri = _background_data_uri(name)
        return (
            f'<image href="{uri}" x="0" y="0" width="{CANVAS.width}"'
            f' height="{CANVAS.height}" preserveAspectRatio="xMidYMid slice"/>'
        )

    # Fallback: procedural backgrounds (palette colors at low opacity).
    base = Background.BASE.get(name, Color.BLACK)
    parts = [C.rect(0, 0, CANVAS.width, CANVAS.height, base)]
    if name == Background.BLACK_RED_ACCENT:
        parts.append(_court_watermark(opacity=0.05))
        parts.append(_red_diagonal())
    elif name == Background.BLACK_COURT:
        parts.append(_court_watermark(opacity=0.09))
    elif name == Background.STATISTICS_DARK:
        parts.append(_statistics_grid())
    elif name == Background.BLACK_STRUCTURAL:
        parts.append(_structural_grid())
    return "".join(parts)


def _red_diagonal() -> str:
    """A single solid red diagonal wedge, top-right. The licensed accent shape."""
    w = CANVAS.width
    return f'<polygon points="{w - 240},0 {w},0 {w},240" fill="{Color.RED}"/>'


def _court_watermark(opacity: float = 0.08) -> str:
    """A stylized half-court, drawn faint (grey at low opacity) for depth — the
    'black + court' treatment. Basket at top-center, half-court arc below."""
    cx = CANVAS.width / 2
    top = 120                      # baseline / backboard height
    paint_w, paint_h = 300, 380    # the key
    ft_r = 150                     # free-throw circle radius
    three_r = 470                  # 3-point arc radius
    stroke = (f'stroke="{Color.GREY}" stroke-opacity="{opacity}" fill="none"'
              f' stroke-width="{Line.MEDIUM}" stroke-linecap="round"')
    p = [
        f'<g {stroke}>',
        f'<line x1="{MARGIN}" y1="{top}" x2="{CANVAS.width - MARGIN}" y2="{top}"/>',  # baseline
        f'<rect x="{cx - paint_w/2}" y="{top}" width="{paint_w}" height="{paint_h}"/>',  # key
        f'<circle cx="{cx}" cy="{top + paint_h}" r="{ft_r}"/>',                          # FT circle
        f'<circle cx="{cx}" cy="{top + 34}" r="20"/>',                                    # hoop
        # 3-point arc: a wide arc sweeping under the basket
        f'<path d="M{cx - three_r},{top} A{three_r},{three_r} 0 0 0 {cx + three_r},{top}"/>',
        f'<circle cx="{cx}" cy="{CANVAS.height - 40}" r="200"/>',                          # mid-court circle
        '</g>',
    ]
    return "".join(p)


def _statistics_grid() -> str:
    """Faint horizontal rules — the 'statistics dark' data-table treatment."""
    stroke = f'stroke="{Color.GREY}" stroke-opacity="0.10" stroke-width="{Line.THIN}"'
    lines = "".join(
        f'<line x1="{MARGIN}" y1="{y}" x2="{CANVAS.width - MARGIN}" y2="{y}" {stroke}/>'
        for y in range(600, CANVAS.height - MARGIN, 180)
    )
    return lines


def _structural_grid() -> str:
    stroke = f'stroke="{Color.GREY}" stroke-opacity="0.07" stroke-width="{Line.THIN}"'
    cols = "".join(
        f'<line x1="{x}" y1="{MARGIN}" x2="{x}" y2="{CANVAS.height - MARGIN}" {stroke}/>'
        for x in range(MARGIN, CANVAS.width, (CANVAS.width - 2 * MARGIN) // 4)
    )
    return cols


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
    season = data["story"].get("season_code")
    round_number = data["story"].get("round_number")
    home_score = facts.get("home_score", 0)
    away_score = facts.get("away_score", 0)
    home_win = home_score >= away_score
    margin = abs(home_score - away_score)

    body: List[str] = []
    # HEADER (top) with the official Segunda FEB competition mark on the left.
    mark_h = 60
    mark_w = mark_h * (_MARK_BBOX[2] / _MARK_BBOX[3])
    body.append(competition_mark(CONTENT_X, MARGIN - 6, mark_h))
    hdr, _ = C.match_header(
        CONTENT_X, MARGIN, CONTENT_W,
        competition="Segunda FEB", round_label=f"Jornada {round_number}", status="FINAL",
        left_inset=mark_w + 18,
    )
    body.append(hdr)

    # SCOREBOARD — the content. Centered between header and footer; the margin is
    # the one non-redundant extra (round is in the header, season in the footer).
    sb, _ = C.scoreboard(
        CONTENT_X, 460, CONTENT_W,
        home=C.TeamSide(display.get("home_team", "Local"), home_score, is_winner=home_win),
        away=C.TeamSide(display.get("away_team", "Visitante"), away_score, is_winner=not home_win),
        variant="hero",
    )
    body.append(sb)

    # A single editorial datum under the scoreboard: the margin.
    mid_x = CANVAS.width / 2
    body.append(C.text(mid_x, 792, f"+{margin}", size=FontSize.H2, weight=FontWeight.HERO,
                       fill=Color.RED, anchor="middle"))
    body.append(C.text(mid_x, 826, "DIFERENCIA", size=FontSize.MICRO, weight=FontWeight.LABEL,
                       fill=Color.GREY, anchor="middle", tracking=LetterSpacing.CAPS, upper=True))

    # BRANDING (bottom)
    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W, competition="Segunda FEB", season=season)
    body.append(ft)
    return _svg_document("".join(body), IMAGE_BACKGROUND)


def _season_short(season: Any) -> str:
    """'2025-2026' → '2025-26' for a cleaner metadata line."""
    s = str(season or "")
    if "-" in s:
        a, b = s.split("-", 1)
        return f"{a}-{b[-2:]}" if len(b) == 4 else s
    return s


# ---------------------------------------------------------------------------
# Template: PLAYER OF THE ROUND
# ---------------------------------------------------------------------------


def render_player_of_round(data: Dict[str, Any]) -> str:
    facts = data["story"]["facts"]
    display = data.get("display", {})
    assets = data.get("assets", {})
    round_number = data["story"].get("round_number")

    body: List[str] = []
    hdr, _ = C.match_header(
        CONTENT_X, MARGIN, CONTENT_W,
        competition="Jugador de la jornada", round_label=f"Jornada {round_number}",
    )
    body.append(hdr)

    secondary = [
        (str(facts.get("rebounds", 0)), "REB"),
        (str(facts.get("assists", 0)), "AST"),
    ]
    hero_kwargs = dict(
        name=display.get("player", "Jugador"),
        team=display.get("team", ""),
        primary_stat=str(facts.get("points", 0)), primary_label="PTS",
        secondary_stats=secondary,
        initials=assets.get("player_initials"),
        badge="MVP",
    )
    # Center the player hero in the space between header and footer.
    _, hero_h = C.player_hero(CONTENT_X, 0, CONTENT_W, **hero_kwargs)
    top, bottom = MARGIN + 40 + Spacing.XL, FOOTER_Y - Spacing.XL
    y0 = top + max(0, (bottom - top - hero_h) // 2)
    ph, _ = C.player_hero(CONTENT_X, y0, CONTENT_W, **hero_kwargs)
    body.append(ph)

    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W,
                           competition="Segunda FEB", season=data["story"].get("season_code"))
    body.append(ft)
    return _svg_document("".join(body), IMAGE_BACKGROUND)


# ---------------------------------------------------------------------------
# Template: ROUND RECAP
# ---------------------------------------------------------------------------


def render_round_recap(data: Dict[str, Any]) -> str:
    facts = data["story"]["facts"]
    display = data.get("display", {})
    season = data["story"].get("season_code")
    round_number = data["story"].get("round_number")
    matches_played = facts.get("matches_played", 0)

    body: List[str] = []
    # HEADER — season lives in the footer, so keep this to the section name.
    hdr, _ = C.match_header(
        CONTENT_X, MARGIN, CONTENT_W,
        competition="Segunda FEB", round_label="Resumen de la jornada",
    )
    body.append(hdr)

    # HERO — giant round number + matches played.
    body.append(C.text(CONTENT_X, 200, "JORNADA", size=FontSize.LABEL, weight=FontWeight.LABEL,
                       fill=Color.GREY, tracking=LetterSpacing.EYEBROW, upper=True))
    body.append(C.text(CONTENT_X, 370, str(round_number), size=FontSize.HERO + 40,
                       weight=FontWeight.HERO, fill=Color.WHITE, tracking=LetterSpacing.HERO))
    body.append(C.text(CONTENT_X, 448, f"{matches_played} partidos disputados",
                       size=FontSize.BODY, weight=FontWeight.TITLE, fill=Color.WHITE))

    # HIGHLIGHTS — three editorial rows that fill the vertical space; the key
    # value sits right in red. Top scorer row shown only when known.
    rows = []
    top = display.get("top_scorer")
    if top and top != "—":
        rows.append(("Máximo anotador", top, f"{facts.get('top_scorer_points', '')} PTS"))
    rows.append(("Mayor diferencia", None, f"+{facts.get('biggest_win_margin', 0)}"))
    rows.append(("Partido más ajustado", None, f"{facts.get('closest_game_margin', 0)} PTS"))

    ry = 620
    step = min(180, (FOOTER_Y - 40 - ry) // max(1, len(rows)))
    for label, subject, value in rows:
        body.append(C.hline(CONTENT_X, ry, CONTENT_W, weight=Line.THIN, color=Color.GREY, opacity=0.28))
        body.append(C.text(CONTENT_X, ry + 46, label.upper(), size=FontSize.MICRO,
                           weight=FontWeight.LABEL, fill=Color.GREY, tracking=LetterSpacing.CAPS, upper=True))
        if subject:
            body.append(C.text(CONTENT_X, ry + 100, subject.upper(), size=FontSize.H3,
                               weight=FontWeight.TITLE, fill=Color.WHITE, upper=True))
        body.append(C.text(CONTENT_X + CONTENT_W, ry + 92, value, size=FontSize.H2,
                           weight=FontWeight.HERO, fill=Color.RED, anchor="end"))
        ry += step

    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W, competition="Segunda FEB", season=season)
    body.append(ft)
    return _svg_document("".join(body), IMAGE_BACKGROUND)


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
