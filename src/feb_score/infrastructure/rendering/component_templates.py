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
import re
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
    Icons,
    LetterSpacing,
    Line,
    Radius,
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


# The official brand background images (blueprint moods), embedded as data URIs
# so the SVG is self-contained. Three moods share the same court-blueprint
# language: dark (default), light (editorial), red (impact — MVP/records).
# TODO(perf): when a PNG rasterizer lands, compose the background there and keep
# the persisted SVG light instead of embedding ~1.4MB per item.
BG_DARK = "court_dark"     # default: black blueprint, clean centre
BG_LIGHT = "court_light"   # editorial white blueprint
BG_RED = "court_red"       # red-impact blueprint (high-energy pieces)
IMAGE_BACKGROUND = BG_DARK

# Every embeddable image background (the moods + the earlier assets, kept for
# back-compat). Anything here is embedded; other names fall to procedural.
_IMAGE_BACKGROUNDS = {
    BG_DARK, BG_LIGHT, BG_RED,
    "tactical_blueprint", "tactical_blueprint_alt",
    "editorial_light", "editorial_light_alt", "red_accent",
}
_ASSET_DIR = Path(__file__).with_name("assets")


# Shared assets (the three court backgrounds and the competition mark) are the
# SAME bytes on every card: embedding them made a 5 KB card weigh 1.85 MB, 96% of
# it one background repeated in every stored row. Rendering therefore emits a
# REFERENCE, and ``inline_shared_assets`` expands it when a standalone file is
# needed. Stored form: compact. Served form: self-contained.
SHARED_ASSET_SCHEME = "feb-asset:"
_ASSET_REF_RE = re.compile(rf'{re.escape(SHARED_ASSET_SCHEME)}([A-Za-z0-9_\-]+)')


@lru_cache(maxsize=8)
def _asset_data_uri(name: str) -> str:
    raw = (_ASSET_DIR / f"{name}.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _asset_ref(name: str) -> str:
    """Reference to a shared asset, expanded at serve time."""
    return f"{SHARED_ASSET_SCHEME}{name}"


def inline_shared_assets(svg: str) -> str:
    """Expand shared-asset references into real data URIs.

    Call this wherever the SVG must stand on its own — the HTTP render endpoint,
    a file written to disk. An SVG with no references passes through unchanged,
    so it is safe to apply twice or to already-inlined content.
    """
    return _ASSET_REF_RE.sub(lambda m: _asset_data_uri(m.group(1)), svg)


# alias kept for the background call site
def _background_data_uri(name: str) -> str:
    return _asset_ref(name)


# The Segunda FEB competition mark (symbol only, no wordmark). RGBA, so it sits
# on the dark background cleanly. Cropped to its alpha bounding box via a nested
# viewBox so it's tight and centered wherever placed.
COMPETITION_MARK = "segunda_feb_mark"
_MARK_BBOX = (74, 16, 161, 209)  # x, y, w, h in the 316x316 source


def competition_mark(x: float, y: float, height: float) -> str:
    """Place the Segunda FEB symbol as a small competition seal."""
    bx, by, bw, bh = _MARK_BBOX
    width = height * (bw / bh)
    uri = _asset_ref(COMPETITION_MARK)
    return (
        f'<svg x="{x}" y="{y}" width="{width:.1f}" height="{height:.1f}"'
        f' viewBox="{bx} {by} {bw} {bh}" overflow="visible">'
        f'<image href="{uri}" x="0" y="0" width="316" height="316"/></svg>'
    )


def _corner_mark(height: float = 52) -> str:
    """The Segunda FEB mark in the top-right corner — a consistent competition
    signature for cards whose header doesn't already carry it."""
    mw = height * (_MARK_BBOX[2] / _MARK_BBOX[3])
    return competition_mark(CONTENT_X + CONTENT_W - mw, MARGIN - 4, height)


def context_tab(x: float, y: float, label: str, *, with_mark: bool = True,
                badge: Any = None, chevron: bool = False, height: float = 60):
    """A subtle filter/context tab: [lead] label [▾], boxed with a hairline
    border. The lead is EITHER a small red value chip (``badge``, e.g. "10" or
    "TOP 5" — a criteria) OR the competition mark (``with_mark`` — a scope). The
    editorial way to carry filters/criteria inside a ranking header.
    Returns (svg, width)."""
    pad = C.Spacing.MD
    lead_h = height - 28
    gap = 12
    if badge is not None:
        b_pad = 10
        badge_w = b_pad * 2 + len(str(badge)) * (C.FontSize.LABEL * 0.62)
        lead_w = badge_w
    elif with_mark:
        lead_w = lead_h * (_MARK_BBOX[2] / _MARK_BBOX[3])
    else:
        lead_w, gap = 0, 0
    # 0.62 em is an upper bound on Inter SemiBold's advance, MEASURED with
    # `resvg --query-all`: the old 0.54 underestimated digit-heavy labels by up
    # to 16px ("2022-23 → 2024-25" is 218px, not 202), so the chevron crowded
    # the text. Overestimating only pads the tab; underestimating collides.
    text_w = len(label) * (C.FontSize.LABEL * 0.62)
    chev_w = 36 if chevron else 0
    w = pad * 2 + lead_w + gap + text_w + chev_w

    parts = [
        C.rect(x, y, w, height, C.Color.INK, radius=C.Radius.MD),
        f'<rect x="{x}" y="{y}" width="{w:.1f}" height="{height}" fill="none"'
        f' stroke="{C.Color.GREY}" stroke-opacity="0.4" stroke-width="{C.Line.THIN}"'
        f' rx="{C.Radius.MD}"/>',
    ]
    cx = x + pad
    ly = y + (height - lead_h) / 2
    if badge is not None:
        # A small red brand chip carrying the criteria value (not semantic).
        parts.append(C.rect(cx, ly, lead_w, lead_h, C.Color.RED, radius=C.Radius.SM))
        parts.append(C.text(cx + lead_w / 2, ly + lead_h / 2 + 7, str(badge),
                            size=C.FontSize.LABEL, weight=C.FontWeight.DISPLAY,
                            fill=C.Color.WHITE, anchor="middle"))
        cx += lead_w + gap
    elif with_mark:
        parts.append(competition_mark(cx, ly, lead_h))
        cx += lead_w + gap
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


def filter_bar(x: float, y: float, tabs: List[Dict[str, Any]], *,
               gap: float = Spacing.SM, height: float = 60):
    """A row of context/filter tabs (criteria + scope), laid left to right — the
    SofaScore-style two-tab filter, in the FEB SCORE! identity. Each entry is the
    kwargs of one ``context_tab``. Returns (svg, total_width)."""
    parts: List[str] = []
    cx = x
    for tab in tabs:
        svg, w = context_tab(cx, y, height=height, **tab)
        parts.append(svg)
        cx += w + gap
    return "".join(parts), (cx - gap - x)


def _background(name: str) -> str:
    """Compose a background. The brand image background (tactical blueprint) is
    embedded and already carries the court lines, technical marks and red
    accents — so no geometric treatment is drawn over it."""
    if name in _IMAGE_BACKGROUNDS:
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
# Composition engine — the layer stack
# ---------------------------------------------------------------------------
# Every template is composed as an ordered stack of layers, painted back to
# front. Any layer may be empty (a template that has no photo simply passes ""),
# and asset-driven layers (IDENTITY / PHOTO) degrade to monochrome chrome when
# the crest/cutout isn't available — so a piece is always valid and never
# invents an asset it doesn't have.
#
#   BASE       the official background (image or procedural)   ← _background
#   IDENTITY   team echo / crest as texture (asset slot)       [awaits crests]
#   PHOTO      player cutout (asset slot)                       C.avatar / player_hero
#   GEOMETRY   frames, court lines, brackets (brand chrome)     C.corner_frame …
#   DATA       scores, stats, ratings, ranking rows             components
#   ACCENT     the single red accent / brand footer             C.accent_bar …

_LAYER_ORDER = ("base", "identity", "photo", "geometry", "data", "accent")


def compose(background: str, **layers: str) -> str:
    """Assemble a template from named layers, painted in the canonical z-order
    (see ``_LAYER_ORDER``). ``background`` selects the BASE layer; the rest are
    optional SVG fragments. Unknown/empty layers are skipped."""
    body = "".join(layers.get(name, "") or "" for name in _LAYER_ORDER[1:])
    return _svg_document(body, background)


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
    # Delight: a blowout (20+) ignites the Red-Impact mood; a normal game stays
    # on the dark blueprint. On red, red is the background, so the winner reads
    # white and the loser grey (brightness), not red.
    blowout = margin >= 20
    bg = BG_RED if blowout else IMAGE_BACKGROUND
    sb_colors = dict(winner_color=Color.WHITE, loser_color=Color.GREY) if blowout else {}

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
        variant="hero", **sb_colors,
    )
    body.append(sb)

    # A single editorial datum under the scoreboard: the margin.
    # Red discipline: the winner's score is the one red datum on this card, so
    # the margin reads in white (was a second red).
    mid_x = CANVAS.width / 2
    body.append(C.text(mid_x, 792, f"+{margin}", size=FontSize.H2, weight=FontWeight.HERO,
                       fill=Color.WHITE, anchor="middle"))
    body.append(C.text(mid_x, 826, "DIFERENCIA", size=FontSize.MICRO, weight=FontWeight.LABEL,
                       fill=Color.GREY, anchor="middle", tracking=LetterSpacing.CAPS, upper=True))

    # BRANDING (bottom)
    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W, competition="Segunda FEB", season=season)
    body.append(ft)
    return _svg_document("".join(body), bg)


# ---------------------------------------------------------------------------
# Template: PLAYER OF THE ROUND
# ---------------------------------------------------------------------------


# High-energy player story types get the Red-Impact mood, so a feed of player
# cards doesn't read as one dark template; routine ones stay on the blueprint.
_RED_PLAYER_STORIES = {"perfect_night", "sharpshooter", "triple_double", "season_high"}
# Season-scope leader cards frame the whole season, not a single round: their
# kicker is the season, never "JORNADA N".
_SEASON_LEADER_STORIES = {"top_scorer", "top_rebounder", "top_assist_provider"}


def _season_label(season_code: str) -> str:
    """'2024-2025' -> '2024-25' (fallback: the raw code)."""
    parts = (season_code or "").split("-")
    if len(parts) == 2 and len(parts[1]) == 4:
        return f"{parts[0]}-{parts[1][2:]}"
    return season_code or ""


# Headline sizing. The advance was MEASURED off rendered cards (0.623 em for a
# 21-char label, 0.636 for a 33-char one, Inter ExtraBold in caps); 0.66 keeps a
# margin so a label can never reach the safe edge. Tracking is added per gap in
# absolute px — folding it into the em factor is what made the first attempt
# overflow the column by up to 37px.
_HEAD_MAX, _HEAD_MIN, _HEAD_ADVANCE = 76, FontSize.H3, 0.66


def _fit_headline(label: str, width: float,
                  tracking: float = LetterSpacing.HEADLINE) -> int:
    """Largest size at which ``label`` fits one line of ``width``."""
    n = max(1, len(label))
    usable = width - (n - 1) * tracking
    return int(max(_HEAD_MIN, min(_HEAD_MAX, usable / (n * _HEAD_ADVANCE))))


def render_player_of_round(data: Dict[str, Any]) -> str:
    facts = data["story"]["facts"]
    display = data.get("display", {})
    assets = data.get("assets", {})
    round_number = data["story"].get("round_number")
    story_type = data["story"].get("story_type")
    red_mood = story_type in _RED_PLAYER_STORIES
    bg = BG_RED if red_mood else IMAGE_BACKGROUND

    body: List[str] = []
    # What this card calls itself comes from the story TYPE, not a per-template
    # default — that default is what made every card claim to be the player of
    # the round. A detector may still override via the facts.
    from ...domain.content.story import StoryType, badge_echoes_headline, labels_for
    try:
        defaults = labels_for(StoryType(story_type))
    except ValueError:
        defaults = {"section": "", "badge": ""}
    section = facts.get("section_label") or defaults["section"] or "Jugador de la jornada"
    # The chip under the portrait adds a qualifier; when it would only repeat
    # the headline (TRIPLE-DOBLE over a TRIPLE-DOBLE chip) it is dropped.
    badge = facts.get("badge_label") or defaults["badge"] or "MVP"
    # The season-leader cards carry a category tag ("MÁX. ANOTADOR") on purpose,
    # and want it on ALL THREE so a carousel is consistent. The echo guard would
    # otherwise drop only the scorer's — "ANOTADOR" is verbatim in its headline,
    # while "REBOTES"/"ASISTENCIAS" don't prefix-match "reboteador"/"asistente" —
    # leaving the three siblings inconsistent. Skip the guard for these types.
    _CATEGORY_TAG_TYPES = {"top_scorer", "top_rebounder", "top_assist_provider"}
    story_type = (data.get("story") or {}).get("story_type")
    if story_type not in _CATEGORY_TAG_TYPES and badge_echoes_headline(section, badge):
        badge = None
    # A single-game card can name the actual matchup ("JORNADA 5 · VS CB LLÍRIA")
    # via facts.kicker; without it, fall back to the season (leaders) or the
    # round number. The rival is what ties the performance to a real game.
    if facts.get("kicker"):
        kicker = str(facts["kicker"])
    elif story_type in _SEASON_LEADER_STORIES:
        kicker = f"TEMPORADA {_season_label(data['story'].get('season_code', ''))}"
    else:
        kicker = f"JORNADA {round_number}"

    # The descriptor is the card's first hit, so it is set as big as it fits —
    # fitted, not fixed, because these labels range from "JUGADOR DE LA JORNADA"
    # to "MÁXIMO REBOTEADOR DE LA TEMPORADA" and a fixed size would overflow the
    # long ones. A full-bleed scrim sits under it: the blueprint's red diagonals
    # otherwise cut straight through the words (same technique as the footer).
    # Reserve the top-right corner mark's column so a long headline
    # ("MÁXIMO REBOTEADOR DE LA TEMPORADA") stops before the Segunda FEB symbol
    # instead of crowding right up against it. Only the long ones shrink; short
    # headlines already fit inside the reduced width unchanged. Red-mood cards
    # draw no mark, so they keep the full width.
    _mark_w = 52 * (_MARK_BBOX[2] / _MARK_BBOX[3])
    head_w = CONTENT_W - (0 if red_mood else _mark_w + Spacing.XL)
    head_size = _fit_headline(section, head_w)
    head_base = MARGIN + 44 + head_size * 0.74
    body.append(
        f'<rect x="0" y="{MARGIN + 30}" width="{CANVAS.width}"'
        f' height="{head_size * 1.34 + 46:.0f}" fill="{Color.BLACK}" fill-opacity="0.72"/>'
    )
    body.append(C.accent_bar(CONTENT_X, MARGIN, 56, Line.HEAVY))
    body.append(C.text(CONTENT_X, head_base, section.upper(), size=head_size,
                       weight=FontWeight.DISPLAY, fill=Color.WHITE,
                       tracking=LetterSpacing.HEADLINE, upper=True))
    body.append(C.text(CONTENT_X, head_base + FontSize.LABEL + 16, kicker,
                       size=FontSize.LABEL, weight=FontWeight.LABEL, fill=Color.GREY,
                       tracking=LetterSpacing.CAPS, upper=True))
    if not red_mood:  # the red top corner can't host the dark mark cleanly
        body.append(_corner_mark())

    # The hero stat is chosen by the detector (points by default, but assists /
    # minutes / threes for the curious & shooting angles) via facts hints, so the
    # same card frames a different story.
    hero_value = facts.get("hero_value", facts.get("points", 0))
    hero_label = facts.get("hero_label", "PTS")
    sec_hint = facts.get("secondary") or [
        [facts.get("rebounds", 0), "REB"], [facts.get("assists", 0), "AST"]
    ]
    secondary = [(str(v), str(lab)) for v, lab in sec_hint]
    hero_kwargs = dict(
        name=display.get("player", "Jugador"),
        team=display.get("team", ""),
        primary_stat=str(hero_value), primary_label=hero_label,
        secondary_stats=secondary,
        initials=assets.get("player_initials"),
        photo_uri=assets.get("player_photo"),
        badge=badge,
    )
    # Place the hero below the kicker, biased upward so the kicker→portrait gap
    # stays tight (the slack falls to the bottom, where the footer anchors it).
    # The FEB Rating verdict band sits between the portrait and the footer, in a
    # FIXED position across every story type that uses this card — the hero stat
    # says what happened, the rating says how good it was. Only drawn when the
    # story actually carries a rating (never invented).
    rating = facts.get("rating")
    rating_px = C.RATING_SIZES["l"]
    band_h = rating_px + Spacing.MD if rating is not None else 0

    _, hero_h = C.player_hero(CONTENT_X, 0, CONTENT_W, **hero_kwargs)
    top, bottom = MARGIN + 116, FOOTER_Y - Spacing.MD - band_h
    y0 = top + max(0, int((bottom - top - hero_h) * 0.28))
    ph, _ = C.player_hero(CONTENT_X, y0, CONTENT_W, **hero_kwargs)
    body.append(ph)

    if rating is not None:
        band_y = FOOTER_Y - Spacing.MD - rating_px
        body.append(C.hline(CONTENT_X, band_y - Spacing.LG, CONTENT_W,
                            color=Color.GREY, opacity=0.35))
        rb, _ = C.rating_badge(CONTENT_X, band_y, float(rating), size="l")
        body.append(rb)
        # Name the mark beside the box, so the same object reads as "the FEB
        # Rating" here, on a ranking row and on the on-court lineup alike.
        lx = CONTENT_X + rating_px + Spacing.LG
        body.append(C.text(lx, band_y + rating_px / 2 - 6, "FEB", size=FontSize.LABEL,
                           weight=FontWeight.DISPLAY, fill=Color.WHITE,
                           tracking=LetterSpacing.CAPS, upper=True))
        body.append(C.text(lx, band_y + rating_px / 2 + 26, "RATING", size=FontSize.LABEL,
                           weight=FontWeight.LABEL, fill=Color.GREY,
                           tracking=LetterSpacing.CAPS, upper=True))

    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W,
                           competition="Segunda FEB", season=data["story"].get("season_code"))
    body.append(ft)
    return _svg_document("".join(body), bg)


# ---------------------------------------------------------------------------
# Template: ROUND RECAP
# ---------------------------------------------------------------------------


# Secondary text on a LIGHT surface. The brand grey (#8A8F98) is tuned for dark
# cards — on white it measures 3.25:1, under the 4.5 a small label needs, and it
# washed out where the blueprint shows through. Softened INK reads 5.6:1 and
# introduces no seventh colour.
_LIGHT_SUB_ALPHA = 0.65


def _fit_to_width(text: str, width: float, max_size: int, min_size: int = 30) -> int:
    """Largest size at which ``text`` fits ``width``. The recap puts a name and
    a big number side by side, so the name must yield rather than collide — a
    long name shrinks instead of running into the figure."""
    n = max(1, len(text))
    size = int(width / (n * _HEAD_ADVANCE))
    return max(min_size, min(max_size, size))


def _fit_caps(text: str, width: float, max_size: int, min_size: int = 12) -> int:
    """Largest size at which a tracked, uppercase label fits ``width``. Measured
    with the same advance the stat labels use, so a long label shrinks instead
    of running past the margin."""
    size = max_size
    while size > min_size and C._caps_width(text.upper(), size) > width:
        size -= 1
    return size


# Spanish decimal separator is ",". A comma glyph carries a descender that
# extends below the baseline, so a hero number like "13,3" or "20,7" will
# visually kiss whatever text sits directly under it (the red label, or the
# name/team line). The rule for every hero-number template is: whenever the
# hero string carries a decimal separator ("," or "."), push the next line
# down by this clearance so the descender never collides with a subtitle.
# One helper, one number, so this cannot drift between templates as new hero
# layouts are added.
_HERO_COMMA_CLEARANCE = 44


def _hero_descender_pad(hero: str) -> int:
    """Vertical padding to add BELOW a hero number when it carries a decimal
    separator. Returns 0 for integer-only heroes."""
    return _HERO_COMMA_CLEARANCE if ("," in hero or "." in hero) else 0


def _wrap_words(text: str, max_chars: int) -> List[str]:
    """Greedy word-wrap into short lines — for the hero note's narrow column."""
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur); cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def render_round_recap(data: Dict[str, Any]) -> str:
    """LA JORNADA EN DATOS — the round as an editorial data sheet.

    Hierarchy comes from size, position and weight, never from colour: every
    figure is WHITE. Red is the brand only — the eyebrow, the block labels, the
    rules and one small rating indicator. Laid out on an 8px grid with wide
    negative space so the piece scans at thumbnail size.
    """
    facts = data["story"]["facts"]
    season = data["story"].get("season_code")
    round_number = data["story"].get("round_number")
    hero = facts.get("hero")
    top = facts.get("top")
    tiles = facts.get("tiles", [])
    X, W = CONTENT_X, CONTENT_W
    R = X + W
    body: List[str] = []

    # The blueprint must never compete with the data: a soft scrim calms it.
    body.append(f'<rect x="0" y="0" width="{CANVAS.width}" height="{CANVAS.height}"'
                f' fill="{Color.BLACK}" fill-opacity="0.45"/>')

    # ---- HEADER (8px grid: 104 / 200 / 280 / 312) -------------------------
    body.append(C.text(X, 104, f"SEGUNDA FEB · JORNADA {round_number}",
                       size=FontSize.MICRO, weight=FontWeight.LABEL, fill=Color.RED,
                       tracking=LetterSpacing.EYEBROW, upper=True))
    body.append(C.text(X, 200, "LA JORNADA", size=80, weight=FontWeight.HERO,
                       fill=Color.WHITE, tracking=LetterSpacing.HERO))
    body.append(C.text(X, 280, "EN DATOS", size=80, weight=FontWeight.HERO,
                       fill=Color.WHITE, tracking=LetterSpacing.HERO))
    body.append(C.accent_bar(X, 312, 88, Line.HEAVY))

    def rule(y: float) -> None:
        body.append(C.hline(X, y, W, weight=Line.THIN, color=Color.GREY, opacity=0.28))

    # ---- BLOCK 1 · EL GRAN DATO (392 → 660) -------------------------------
    if hero:
        rule(392)
        body.append(C.text(X, 432, "EL GRAN DATO", size=FontSize.MICRO,
                           weight=FontWeight.LABEL, fill=Color.RED,
                           tracking=LetterSpacing.CAPS, upper=True))
        name = str(hero["name"]).upper()
        body.append(C.text(X, 496, name, size=_fit_to_width(name, 440, FontSize.H2, 26),
                           weight=FontWeight.DISPLAY, fill=Color.WHITE, upper=True))
        if hero.get("team"):
            body.append(C.text(X, 528, str(hero["team"]).upper(), size=FontSize.MICRO,
                               weight=FontWeight.LABEL, fill=Color.GREY,
                               tracking=LetterSpacing.LABEL, upper=True))
        # The hero figure: white, the largest thing on the card.
        body.append(C.text(R, 544, str(hero["value"]), size=184, weight=FontWeight.HERO,
                           fill=Color.WHITE, anchor="end", tracking=LetterSpacing.HERO))
        if hero.get("unit"):
            body.append(C.text(R, 584, hero["unit"], size=FontSize.MICRO,
                               weight=FontWeight.LABEL, fill=Color.LIGHT_GREY, anchor="end",
                               tracking=LetterSpacing.CAPS, upper=True))
        for j, ln in enumerate(_wrap_words(str(hero.get("note", "")).upper(), 18)):
            body.append(C.text(R, 616 + j * 24, ln, size=FontSize.MICRO,
                               weight=FontWeight.BODY, fill=Color.GREY, anchor="end",
                               tracking=LetterSpacing.LABEL, upper=True))

    # ---- BLOCK 2 · MEJOR ACTUACIÓN (720 → 890) ----------------------------
    if top:
        rule(720)
        body.append(C.text(X, 760, "MEJOR ACTUACIÓN", size=FontSize.MICRO,
                           weight=FontWeight.LABEL, fill=Color.RED,
                           tracking=LetterSpacing.CAPS, upper=True))
        tname = str(top["name"]).upper()
        body.append(C.text(X, 824, tname, size=_fit_to_width(tname, 400, FontSize.H2, 26),
                           weight=FontWeight.DISPLAY, fill=Color.WHITE, upper=True))
        if top.get("team"):
            body.append(C.text(X, 856, str(top["team"]).upper(), size=FontSize.MICRO,
                               weight=FontWeight.LABEL, fill=Color.GREY,
                               tracking=LetterSpacing.LABEL, upper=True))
        # A metrics strip on the right: four cells split by hairlines.
        rating = top.get("rating")
        cells = [(top.get("points"), "PTS"), (top.get("rebounds"), "REB"),
                 (top.get("assists"), "AST")]
        if rating is not None:
            cells.append((C._fmt_rating(float(rating)), "NOTA FEB"))
        cw = 112
        for i, (val, lab) in enumerate(cells):
            cx = R - cw * (len(cells) - i) + cw / 2
            if i > 0:
                body.append(C.vline(cx - cw / 2, 776, 88, color=Color.GREY, opacity=0.28))
            body.append(C.text(cx, 824, str(val), size=FontSize.H2, weight=FontWeight.HERO,
                               fill=Color.WHITE, anchor="middle", tracking=LetterSpacing.DISPLAY))
            body.append(C.text(cx, 856, lab, size=FontSize.MICRO, weight=FontWeight.LABEL,
                               fill=Color.GREY, anchor="middle",
                               tracking=LetterSpacing.LABEL, upper=True))
        # The single red mark in the block: a small brand indicator under the
        # rating. It flags WHICH figure is the mark, not that it is a good one.
        if rating is not None:
            body.append(C.rect(R - cw / 2 - 16, 872, 32, 3, Color.RED))

    # ---- BLOCK 3 · THREE SECONDARY STORIES (952 → 1104) -------------------
    if tiles:
        rule(952)
        col = W / 3
        # One size across all three, so the row reads as a system rather than
        # three labels that each happen to fit.
        shown = tiles[:3]
        label_size = min(
            _fit_caps(str(t["label"]), col - (0 if i == 0 else 24) - 16, FontSize.MICRO)
            for i, t in enumerate(shown)
        )
        sub_size = min(
            _fit_caps(str(t.get("sub", "")).upper(), col - (0 if i == 0 else 24) - 16,
                      FontSize.MICRO)
            for i, t in enumerate(shown)
        )
        for i, tile in enumerate(shown):
            tx = X + i * col
            if i > 0:
                body.append(C.vline(tx, 968, 136, color=Color.GREY, opacity=0.22))
            pad = 0 if i == 0 else 24
            body.append(C.text(tx + pad, 1032, str(tile["value"]), size=72,
                               weight=FontWeight.HERO, fill=Color.WHITE,
                               tracking=LetterSpacing.DISPLAY))
            body.append(C.text(tx + pad, 1064, str(tile["label"]), size=label_size,
                               weight=FontWeight.LABEL, fill=Color.RED,
                               tracking=LetterSpacing.LABEL, upper=True))
            body.append(C.text(tx + pad, 1092, str(tile.get("sub", "")).upper(),
                               size=sub_size, weight=FontWeight.BODY, fill=Color.GREY,
                               tracking=LetterSpacing.LABEL, upper=True))

    ft, _ = C.brand_footer(X, FOOTER_Y, W, competition="Segunda FEB", season=season)
    body.append(ft)
    return _svg_document("".join(body), BG_DARK)


def render_stat_hero(data: Dict[str, Any]) -> str:
    """Photo-less hero card: the NUMBER is the protagonist and the team crest is
    the IDENTITY anchor (where a photo would sit). For maximos / actuacion del
    ano when there is no usable player photo — so the account never depends on
    one. No team-colour gradients (rejected): black/white/grey + the red accent,
    and the crest as a large, low-opacity identity echo.
    """
    facts = data["story"]["facts"]
    display = data.get("display", {})
    assets = data.get("assets", {})
    story_type = data["story"].get("story_type")
    ink, sub = Color.WHITE, Color.GREY

    from ...domain.content.story import StoryType, labels_for
    try:
        section = facts.get("section_label") or labels_for(StoryType(story_type))["section"]
    except ValueError:
        section = facts.get("section_label") or "Dato de la temporada"
    if facts.get("kicker"):
        kicker = str(facts["kicker"])
    elif story_type in _SEASON_LEADER_STORIES:
        kicker = f"TEMPORADA {_season_label(data['story'].get('season_code',''))}"
    else:
        kicker = f"JORNADA {data['story'].get('round_number')}"

    hero = str(facts.get("hero_value", facts.get("points", 0)))
    hlab = str(facts.get("hero_label", "PTS"))
    name = str(display.get("player", "")).upper()
    team = str(display.get("team", "")).upper()
    sec_hint = facts.get("secondary") or [
        [facts.get("rebounds", 0), "REB"], [facts.get("assists", 0), "AST"]]
    secondary = [(str(v), str(l)) for v, l in sec_hint]
    rating = facts.get("rating")
    crest = assets.get("team_crest")

    body: List[str] = []

    # IDENTITY — the crest, large and faint, where a photo would be. Bleeds off
    # the right edge; the data column sits clear of it on the left. The FEB crest
    # PNGs ship on an opaque white box, so a raw low-opacity paste showed the box.
    # A filter keys it to a clean MONOCHROME silhouette: invert -> luminance to
    # alpha (white bg -> transparent, logo -> opaque) -> flood white. Any crest,
    # white-bg or transparent, becomes the same tidy identity echo.
    if crest:
        cs = 660
        cx = CANVAS.width - cs + 150
        cy = 250
        body.append(
            '<defs><filter id="crestwm" x="-5%" y="-5%" width="110%" height="110%">'
            '<feColorMatrix type="matrix" values="'
            '-1 0 0 0 1  0 -1 0 0 1  0 0 -1 0 1  0 0 0 1 0" result="inv"/>'
            '<feColorMatrix in="inv" type="luminanceToAlpha" result="a"/>'
            '<feComponentTransfer in="a" result="a2">'
            '<feFuncA type="linear" slope="1.35" intercept="0"/></feComponentTransfer>'
            '<feFlood flood-color="#FFFFFF" result="w"/>'
            '<feComposite in="w" in2="a2" operator="in"/></filter></defs>')
        body.append(
            f'<g opacity="0.16"><image href="{crest}" x="{cx}" y="{cy}"'
            f' width="{cs}" height="{cs}" preserveAspectRatio="xMidYMid meet"'
            f' filter="url(#crestwm)"/></g>')

    # HEADER
    body.append(C.accent_bar(CONTENT_X, MARGIN, 56, Line.HEAVY))
    _mark_w = 52 * (_MARK_BBOX[2] / _MARK_BBOX[3])
    head_size = _fit_headline(section, CONTENT_W - _mark_w - Spacing.XL)
    head_base = MARGIN + 44 + head_size * 0.74
    body.append(C.text(CONTENT_X, head_base, section.upper(), size=head_size,
                       weight=FontWeight.DISPLAY, fill=ink,
                       tracking=LetterSpacing.HEADLINE, upper=True))
    body.append(C.text(CONTENT_X, head_base + FontSize.LABEL + 16, kicker,
                       size=FontSize.LABEL, weight=FontWeight.LABEL, fill=sub,
                       tracking=LetterSpacing.CAPS, upper=True))
    body.append(_corner_mark())

    # HERO NUMBER — the protagonist.
    num_size = int(_fit_to_width(hero, CONTENT_W * 0.66, 320, 150))
    ny = 700
    body.append(C.text(CONTENT_X - 6, ny, hero, size=num_size, weight=FontWeight.HERO,
                       fill=ink, tracking=LetterSpacing.HERO))
    # A comma in the hero (20,7) has a descender that dips below the baseline;
    # without extra padding it kisses the red label just below and the label
    # kisses the name. The clearance rule lives in _hero_descender_pad so every
    # hero-number template uses the same number.
    label_y = ny + FontSize.H2 + _hero_descender_pad(hero)
    body.append(C.text(CONTENT_X, label_y, hlab.upper(), size=FontSize.H2,
                       weight=FontWeight.DISPLAY, fill=Color.RED,
                       tracking=LetterSpacing.CAPS, upper=True))

    # IDENTITY (text) — name + team.
    name_y = label_y + 96
    name_size = int(_fit_to_width(name, CONTENT_W, FontSize.H1, 44))
    body.append(C.text(CONTENT_X, name_y, name, size=name_size,
                       weight=FontWeight.DISPLAY, fill=ink,
                       tracking=LetterSpacing.HEADLINE, upper=True))
    body.append(C.text(CONTENT_X, name_y + 44, team, size=FontSize.LABEL,
                       weight=FontWeight.LABEL, fill=sub,
                       tracking=LetterSpacing.CAPS, upper=True))

    # SECONDARY stats — hidden by default now: reviewed live and the "26 PART ·
    # 13,3 MEDIA" line crowded the card without adding editorial value. Kept
    # behind a facts.show_secondary hint in case a future card wants them back.
    if facts.get("show_secondary"):
        sg, _ = C.stat_group(CONTENT_X, name_y + 92, 560,
                             [(v, l) for v, l in secondary])
        body.append(sg)

    # FEB RATING band above the footer (only if present).
    if rating is not None:
        rpx = C.RATING_SIZES["l"]
        band_y = FOOTER_Y - Spacing.MD - rpx
        body.append(C.hline(CONTENT_X, band_y - Spacing.LG, CONTENT_W,
                            color=Color.GREY, opacity=0.35))
        rb, _ = C.rating_badge(CONTENT_X, band_y, float(rating), size="l")
        body.append(rb)
        lx = CONTENT_X + rpx + Spacing.LG
        body.append(C.text(lx, band_y + rpx / 2 - 6, "FEB", size=FontSize.LABEL,
                           weight=FontWeight.DISPLAY, fill=ink,
                           tracking=LetterSpacing.CAPS, upper=True))
        body.append(C.text(lx, band_y + rpx / 2 + 26, "RATING", size=FontSize.LABEL,
                           weight=FontWeight.LABEL, fill=sub,
                           tracking=LetterSpacing.CAPS, upper=True))

    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W, competition="Segunda FEB",
                           season=data["story"].get("season_code"))
    body.append(ft)
    return _svg_document("".join(body), IMAGE_BACKGROUND)


def render_player_streak(data: Dict[str, Any]) -> str:
    """Dedicated card for consecutive-game rachas.

    Two-column layout: the streak length is the giant number on the left, the
    player photo bleeds down the right half, the name/team sit at the bottom.
    No FEB Rating band — the streak IS the story. A partial red arc wraps the
    number so the visual weight of the run is felt before the caption is read.
    Falls back to typographic initials when no licensed photo exists, same as
    every other player card.
    """
    facts = data["story"]["facts"]
    display = data.get("display", {})
    assets = data.get("assets", {})

    # The number+label under it already says "5 DOBLES-DOBLES SEGUIDOS" plainly,
    # so the top-left eyebrow gets an editorial section header instead of a
    # verbatim echo. Callers can still override via facts.section_label.
    _KIND_SECTIONS = {
        "scoring": "EN RACHA · ANOTACIÓN",
        "double_double": "EN RACHA · DOBLES-DOBLES",
    }
    section_default = _KIND_SECTIONS.get(str(facts.get("streak_kind", "")), "EN RACHA")
    section = str(facts.get("section_label") or section_default)
    kicker = str(facts.get("kicker") or f"JORNADA {data['story'].get('round_number')}")
    hero = str(facts.get("hero_value") or facts.get("streak_length") or "")
    hlab = str(facts.get("hero_label") or "SEGUIDOS")
    name = str(display.get("player") or facts.get("player_name") or "").upper()
    team = str(display.get("team") or facts.get("team_name") or "").upper()

    body: List[str] = []

    # PHOTO — full-bleed on the right ~55%, with a hefty gradient fade on its
    # left edge so it dissolves into the black background instead of showing a
    # hard rectangle seam. The fade must reach far enough right to swallow the
    # WHITE background common in FEB studio portraits, not just a dark cutout.
    # When the photo is missing, no gradient, no rectangle: the left column
    # stretches to fill.
    photo_uri = assets.get("player_photo")
    photo_x = 540  # column split — the number + name column gets the left half
    photo_w = CANVAS.width - photo_x
    photo_h = CANVAS.height
    if photo_uri:
        body.append(
            '<defs>'
            # A wide fade: opaque black from the left edge, still 60% at 25%,
            # transparent by 50% — kills the abrupt white edge of studio shots
            # without eating the face.
            '<linearGradient id="photofade" x1="0" y1="0" x2="1" y2="0">'
            '<stop offset="0" stop-color="#0A0A0A" stop-opacity="1"/>'
            '<stop offset="0.25" stop-color="#0A0A0A" stop-opacity="0.6"/>'
            '<stop offset="0.5" stop-color="#0A0A0A" stop-opacity="0"/>'
            '</linearGradient></defs>'
        )
        body.append(
            f'<image href="{photo_uri}" x="{photo_x}" y="0"'
            f' width="{photo_w}" height="{photo_h}"'
            f' preserveAspectRatio="xMidYMid slice"/>'
        )
        body.append(
            f'<rect x="{photo_x}" y="0" width="{photo_w}" height="{photo_h}"'
            f' fill="url(#photofade)"/>'
        )

    # Section headline + eyebrow accent (top-left) — CONSTRAINED to the left
    # column so a long "EN RACHA · DOBLES-DOBLES" never slides under the photo.
    # Drawn AFTER the photo so it always wins the z-order on the fade band.
    left_col_w = photo_x - MARGIN - Spacing.LG
    body.append(C.accent_bar(CONTENT_X, MARGIN, 96, Line.HEAVY))
    head_size = FontSize.H3
    # If a caller-supplied section still overflows the left column, step it
    # down until it fits so the truncation-under-photo bug can't come back.
    while head_size > 20 and len(section) * head_size * 0.62 > left_col_w:
        head_size -= 2
    head_y = MARGIN + 44 + head_size * 0.74
    body.append(C.text(CONTENT_X, head_y, section.upper(), size=head_size,
                       weight=FontWeight.DISPLAY, fill=Color.WHITE,
                       tracking=LetterSpacing.HEADLINE, upper=True))
    body.append(_corner_mark())

    # GIANT NUMBER on the left. Sized inversely to digit count so both "5" and
    # "12" fill roughly the same visual space and neither crowds the name.
    num_col_w = photo_x - MARGIN - Spacing.LG
    num_size = 620 if len(hero) <= 1 else 460 if len(hero) == 2 else 340
    num_center_x = MARGIN + num_col_w / 2
    num_center_y = 720
    # SVG text baseline sits at the bottom, so drop the anchor by ~0.36 of the
    # size to visually center the digit.
    body.append(C.text(num_center_x, num_center_y + num_size * 0.36, hero,
                       size=num_size, weight=FontWeight.HERO, fill=Color.WHITE,
                       anchor="middle", tracking=LetterSpacing.HERO))

    # No decorative arc around the number: reviewed live and it read as a
    # broken ring cutting through the digit, not as a run accent. The red
    # presence lives on the small underline below the label instead.

    # SMALL LABEL under the number. When the hero carries a decimal separator
    # ("13,3"), push the label down by the standard descender clearance so the
    # comma's tail doesn't kiss the red label. Same rule that stat_hero uses;
    # applied via _hero_descender_pad so both templates cannot drift.
    label_baseline = (num_center_y + num_size * 0.36 + FontSize.LABEL
                      + Spacing.MD + _hero_descender_pad(hero))
    body.append(C.text(num_center_x, label_baseline,
                       hlab.upper(), size=FontSize.LABEL, weight=FontWeight.LABEL,
                       fill=Color.RED, tracking=LetterSpacing.CAPS, upper=True,
                       anchor="middle"))
    # A short red underline under the label — the card's main red accent
    # since the wrapping arc was retired.
    body.append(C.accent_bar(num_center_x - 40, label_baseline + 12, 80,
                             Line.THIN))
    # OPTIONAL EXTRAS — one small line under the label (e.g. "+2 TRIPLES-DOBLES"
    # on a season DD leader card). Absent facts collapse the block cleanly.
    extras = str(facts.get("extras_label") or "").strip()
    if extras:
        body.append(C.text(num_center_x,
                           label_baseline + FontSize.LABEL + Spacing.SM,
                           extras.upper(), size=FontSize.LABEL - 2,
                           weight=FontWeight.LABEL, fill=Color.GREY,
                           tracking=LetterSpacing.CAPS, upper=True,
                           anchor="middle"))

    # PLAYER NAME + TEAM at the bottom-left. Two lines when a long name would
    # otherwise crowd the photo column; kept in one when it comfortably fits.
    name_size = FontSize.H1 if len(name) <= 14 else FontSize.H2
    name_max_w = photo_x - MARGIN - 24
    parts = name.split()
    line_break = None
    if len(name) > 18 and len(parts) >= 2:
        # Break on the largest word split closest to the middle.
        mid = len(parts) // 2
        line_break = (" ".join(parts[:mid]), " ".join(parts[mid:]))
    name_bottom = FOOTER_Y - 96
    if line_break:
        body.append(C.text(CONTENT_X, name_bottom - name_size,
                           line_break[0], size=name_size, weight=FontWeight.DISPLAY,
                           fill=Color.WHITE, tracking=LetterSpacing.HEADLINE, upper=True))
        body.append(C.text(CONTENT_X, name_bottom,
                           line_break[1], size=name_size, weight=FontWeight.DISPLAY,
                           fill=Color.WHITE, tracking=LetterSpacing.HEADLINE, upper=True))
    else:
        body.append(C.text(CONTENT_X, name_bottom, name, size=name_size,
                           weight=FontWeight.DISPLAY, fill=Color.WHITE,
                           tracking=LetterSpacing.HEADLINE, upper=True))
    # Extra gap between the name's last line and the team label so the comma
    # descender in "PALTARAK, MIKHAIL" doesn't kiss the team baseline.
    body.append(C.text(CONTENT_X, name_bottom + FontSize.LABEL + 28, team,
                       size=FontSize.LABEL, weight=FontWeight.LABEL,
                       fill=Color.GREY, tracking=LetterSpacing.CAPS, upper=True))

    # FOOTER — same competition/season strip every card carries.
    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W,
                           competition="Segunda FEB",
                           season=data["story"].get("season_code"))
    body.append(ft)

    return _svg_document("".join(body), IMAGE_BACKGROUND)


def render_stat_leaderboard(data: Dict[str, Any]) -> str:
    facts = data["story"]["facts"]
    season = data["story"].get("season_code")
    round_number = data["story"].get("round_number")
    leaders = facts.get("leaders", [])

    # LIGHT DATA mood: rankings read best on the editorial white blueprint, so
    # text inverts to dark and the rating chip uses its on-light tiers.
    ink, sub = Color.BLACK, Color.INK

    body: List[str] = []
    # Title + subtitle
    body.append(C.text(CONTENT_X, 180, "Máximos anotadores", size=FontSize.H1,
                       weight=FontWeight.DISPLAY, fill=ink, tracking=LetterSpacing.HEADLINE))
    body.append(C.text(CONTENT_X, 232, "LA JORNADA EN CIFRAS", size=FontSize.LABEL,
                       weight=FontWeight.LABEL, fill=sub, opacity=_LIGHT_SUB_ALPHA, tracking=LetterSpacing.CAPS, upper=True))

    # Two-tab filter bar: criteria (a red count chip) + scope (competition mark).
    bar, _ = filter_bar(CONTENT_X, 288, [
        {"label": f"Top {len(leaders)}", "badge": len(leaders), "with_mark": False, "chevron": True},
        {"label": f"Jornada {round_number}", "with_mark": True, "chevron": True},
    ])
    body.append(bar)

    # Column note so the rating chip reads as a 0..10 score, not a bare number.
    body.append(C.text(CONTENT_X + CONTENT_W, 400, "FEB RATING /10", size=FontSize.MICRO,
                       weight=FontWeight.LABEL, fill=sub, opacity=_LIGHT_SUB_ALPHA, anchor="end",
                       tracking=LetterSpacing.LABEL, upper=True))

    # Ranking rows: rank · avatar · name/team · points · FEB Rating chip.
    # The avatar is a SLOT — initials today, a real cutout when photos land.
    ry = 430
    n = max(1, len(leaders))
    step = min(132, (FOOTER_Y - 60 - ry) // n)
    chip = 88
    av_r = 42
    av_cx = CONTENT_X + 40 + av_r
    name_x = av_cx + av_r + Spacing.LG
    for row in leaders:
        name = row.get("player_name") or row.get("player_external_id", "—")
        team = row.get("team_name") or row.get("team_external_id", "")
        body.append(C.hline(CONTENT_X, ry - 24, CONTENT_W, weight=Line.THIN, color=Color.INK, opacity=0.15))
        body.append(C.text(CONTENT_X, ry + 20, str(row.get("rank", "")), size=FontSize.H3,
                           weight=FontWeight.HERO, fill=sub, opacity=_LIGHT_SUB_ALPHA))
        body.append(C.avatar(av_cx, ry + 8, av_r, initials=C.initials_of(name),
                             photo_uri=row.get("photo_uri"), badge_uri=row.get("badge_uri")))
        body.append(C.text(name_x, ry + 16, name.upper(), size=FontSize.H3,
                           weight=FontWeight.TITLE, fill=ink, upper=True))
        if team:
            body.append(C.text(name_x, ry + 46, team.upper(), size=FontSize.MICRO,
                               weight=FontWeight.LABEL, fill=sub, opacity=_LIGHT_SUB_ALPHA, tracking=LetterSpacing.LABEL, upper=True))
        body.append(C.text(CONTENT_X + CONTENT_W - chip - 40, ry + 22, str(row.get("points", 0)),
                           size=FontSize.H2, weight=FontWeight.HERO, fill=ink, anchor="end",
                           tracking=LetterSpacing.DISPLAY))
        # A row without a rating (too few minutes, or no shooting data) simply
        # shows no mark — never a stand-in 0.
        row_rating = row.get("rating")
        if row_rating is not None:
            rating_svg, _ = C.rating_badge(CONTENT_X + CONTENT_W - chip, ry - 24,
                                           float(row_rating), size="m", on_dark=False)
            body.append(rating_svg)
        ry += step

    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W, competition="Segunda FEB",
                           season=season, variant="light")
    body.append(ft)
    return _svg_document("".join(body), BG_LIGHT)


# ---------------------------------------------------------------------------
# Template: BEST FIVE (the round's five best by FEB Rating, as a ranking grid)
# ---------------------------------------------------------------------------


def render_best_five_grid(data: Dict[str, Any]) -> str:
    """The round's five best players by FEB Rating, ranked. A grid, not a court:
    these are the best five of the night, not an ideal lineup by position, so
    nothing claims a position (the position data is not clean enough to). The
    NOTE is the metric they are ranked by, so it is the number that stands out;
    the scoring line rides underneath the name as context.
    """
    facts = data["story"]["facts"]
    season = data["story"].get("season_code")
    round_number = data["story"].get("round_number")
    lineup = facts.get("lineup", [])
    ink, sub = Color.BLACK, Color.INK

    # The same grid serves the round quinteto and the all-time list. Rank
    # numbers are OFF for the latter on purpose: at the top the note saturates
    # (five 9,8s across three seasons), so numbering them would invent an order
    # the data does not support.
    title = facts.get("title", "El quinteto de la jornada")
    subtitle = facts.get("subtitle", "LOS 5 MEJORES POR NOTA FEB")
    scope_label = facts.get("scope_label", f"Jornada {round_number}")
    count_label = facts.get("count_label", "Mejor 5")
    show_rank = facts.get("show_rank", True)
    # What the right-hand column IS. The automatic quinteto ranks by FEB
    # Rating; a hand-made one can rank by anything, and a card that says
    # "FEB RATING" over a column of points per game would be lying.
    metric_label = facts.get("metric_label", "FEB RATING /10")

    body: List[str] = []
    body.append(C.text(CONTENT_X, 176, title,
                       size=_fit_to_width(title, CONTENT_W, 76, 44),
                       weight=FontWeight.DISPLAY, fill=ink, tracking=LetterSpacing.HEADLINE))
    body.append(C.text(CONTENT_X, 232, subtitle, size=FontSize.LABEL,
                       weight=FontWeight.LABEL, fill=sub, opacity=_LIGHT_SUB_ALPHA, tracking=LetterSpacing.CAPS, upper=True))
    bar, _ = filter_bar(CONTENT_X, 288, [
        {"label": count_label, "badge": len(lineup), "with_mark": False, "chevron": True},
        {"label": scope_label, "with_mark": True, "chevron": True},
    ])
    body.append(bar)
    body.append(C.text(CONTENT_X + CONTENT_W, 400, metric_label, size=FontSize.MICRO,
                       weight=FontWeight.LABEL, fill=sub, opacity=_LIGHT_SUB_ALPHA, anchor="end",
                       tracking=LetterSpacing.LABEL, upper=True))

    ry = 430
    n = max(1, len(lineup))
    # A five fills the card at 132. A hand-made ranking can legitimately come
    # back with four (only four players matched), and four rows at 132 leave the
    # bottom third empty — so a short list breathes instead of hugging the top.
    step = min(132 if n >= 5 else 168, (FOOTER_Y - 60 - ry) // n)
    chip = 88
    av_r = 42
    av_cx = CONTENT_X + 40 + av_r
    name_x = av_cx + av_r + Spacing.LG
    for i, row in enumerate(lineup, start=1):
        name = row.get("player_name") or row.get("player_external_id", "—")
        team = row.get("team_name") or row.get("team_external_id", "")
        stat = row.get("context") or (
            f"{row.get('points', 0)} PTS · {row.get('rebounds', 0)} REB "
            f"· {row.get('assists', 0)} AST")
        body.append(C.hline(CONTENT_X, ry - 24, CONTENT_W, weight=Line.THIN,
                            color=Color.INK, opacity=0.15))
        if show_rank:
            body.append(C.text(CONTENT_X, ry + 20, str(row.get("rank", i)), size=FontSize.H3,
                               weight=FontWeight.HERO, fill=sub, opacity=_LIGHT_SUB_ALPHA))
        body.append(C.avatar(av_cx, ry + 8, av_r, initials=C.initials_of(name),
                             photo_uri=row.get("photo_uri"), badge_uri=row.get("badge_uri")))
        # Fit the name to the room left of the rating/value column, so a very
        # long name ("OLUWASESAN BENJAMIN MICHAEL RUSSELL") shrinks instead of
        # running under the note box. Reserve enough for either the rating chip
        # or a right-anchored value.
        name_avail = (CONTENT_X + CONTENT_W - 150) - name_x
        name_size = _fit_to_width(name.upper(), name_avail, FontSize.H3, 18)
        body.append(C.text(name_x, ry + 10, name.upper(), size=name_size,
                           weight=FontWeight.TITLE, fill=ink, upper=True))
        body.append(C.text(name_x, ry + 40, stat, size=FontSize.MICRO,
                           weight=FontWeight.LABEL, fill=sub, opacity=_LIGHT_SUB_ALPHA, tracking=LetterSpacing.LABEL, upper=True))
        rating = row.get("rating")
        if rating is not None:
            rb, _ = C.rating_badge(CONTENT_X + CONTENT_W - chip, ry - 24,
                                   float(rating), size="m", on_dark=False)
            body.append(rb)
        elif row.get("value") is not None:
            # No note to show: the ranked figure takes the badge's place as the
            # number that stands out. Plain type, not a rating box — the box is
            # the FEB Rating's mark and means /10.
            body.append(C.text(CONTENT_X + CONTENT_W, ry + 26, str(row["value"]),
                               size=FontSize.H2, weight=FontWeight.HERO, fill=ink,
                               anchor="end", tracking=LetterSpacing.HEADLINE))
        ry += step

    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W, competition="Segunda FEB",
                           season=season, variant="light")
    body.append(ft)
    return _svg_document("".join(body), BG_LIGHT)


# ---------------------------------------------------------------------------
# Template: BEST FIVE (the round's ideal lineup, on a court diagram)
# ---------------------------------------------------------------------------


def _court_diagram(x: float, y: float, w: float, h: float, *, opacity: float = 0.22) -> str:
    """A clean half-court drawn as thin lines — both the GEOMETRY layer and the
    coordinate system the five players are placed on. Basket at top. Procedural,
    no asset: the court is code, so positions always align to it."""
    cx = x + w / 2
    key_w, key_h = w * 0.30, h * 0.32
    ft_r = key_w * 0.5
    three_r = w * 0.52
    stroke = (f'stroke="{Color.GREY}" stroke-opacity="{opacity}" fill="none"'
              f' stroke-width="{Line.MEDIUM}" stroke-linecap="round" stroke-linejoin="round"')
    p = [
        f'<g {stroke}>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4"/>',              # court box
        f'<rect x="{cx - key_w/2}" y="{y}" width="{key_w}" height="{key_h}"/>',  # the key
        f'<circle cx="{cx}" cy="{y + 28}" r="14"/>',                            # hoop
        f'<circle cx="{cx}" cy="{y + key_h}" r="{ft_r}"/>',                     # FT circle
        f'<path d="M{cx - three_r},{y} A{three_r},{three_r} 0 0 0 {cx + three_r},{y}"/>',  # 3pt arc
        f'<line x1="{x}" y1="{y + h}" x2="{x + w}" y2="{y + h}"/>',             # half-court line
        '</g>',
    ]
    return "".join(p)


# Five spots as fractions of the court box (basket at top): a center near the
# rim, two forwards on the wings, two guards up top on the perimeter.
_LINEUP_SPOTS = [
    ("C", 0.50, 0.12),
    ("PF", 0.19, 0.42), ("SF", 0.81, 0.42),
    ("PG", 0.32, 0.76), ("SG", 0.68, 0.76),
]


def render_best_five_court(data: Dict[str, Any]) -> str:
    facts = data["story"]["facts"]
    season = data["story"].get("season_code")
    round_number = data["story"].get("round_number")
    lineup = facts.get("lineup", [])

    # Header (DATA layer, above the court).
    head: List[str] = []
    head.append(C.text(CONTENT_X, 150, "El quinteto ideal", size=FontSize.H1,
                       weight=FontWeight.DISPLAY, fill=Color.WHITE, tracking=LetterSpacing.HEADLINE))
    head.append(C.text(CONTENT_X, 196, "LA MEJOR ALINEACIÓN DE LA JORNADA", size=FontSize.LABEL,
                       weight=FontWeight.LABEL, fill=Color.GREY, tracking=LetterSpacing.CAPS, upper=True))
    bar, _ = filter_bar(CONTENT_X, 240, [
        {"label": "Mejor 5", "badge": 5, "with_mark": False, "chevron": True},
        {"label": f"Jornada {round_number}", "with_mark": True, "chevron": True},
    ])
    head.append(bar)
    head.append(_corner_mark())

    # Court (GEOMETRY layer) + the five players placed on it (DATA layer).
    bx, by, bw, bh = CONTENT_X, 372, CONTENT_W, 792
    court = _court_diagram(bx, by, bw, bh)

    players: List[str] = []
    r = 60
    for (spot, fx, fy), row in zip(_LINEUP_SPOTS, lineup):
        px, py = bx + bw * fx, by + bh * fy
        name = row.get("player_name") or row.get("player_external_id", "—")
        position = row.get("position", "")
        rating = row.get("rating")
        players.append(C.avatar(px, py, r, initials=C.initials_of(name),
                                photo_uri=row.get("photo_uri"), badge_uri=row.get("badge_uri")))
        # The position is the whole point of this card, so it leads — a red tag
        # above the name.
        if position:
            players.append(C.text(px, py + r + 30, position.upper(), size=FontSize.MICRO,
                                  weight=FontWeight.LABEL, fill=Color.RED, anchor="middle",
                                  tracking=LetterSpacing.CAPS, upper=True))
        players.append(C.text(px, py + r + 56, name.upper(), size=FontSize.MICRO,
                              weight=FontWeight.TITLE, fill=Color.WHITE, anchor="middle", upper=True))
        if rating is not None:
            chip, _ = C.rating_badge(px - 23, py + r + 72, float(rating), size="s")
            players.append(chip)

    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W, competition="Segunda FEB", season=season)
    return compose(Background.STATISTICS_DARK, geometry=court,
                   data="".join(head) + "".join(players) + ft)


# ---------------------------------------------------------------------------
# Template: TEAM STREAK (a team card — the win/loss run visualized)
# ---------------------------------------------------------------------------


def render_team_streak(data: Dict[str, Any]) -> str:
    facts = data["story"]["facts"]
    assets = data.get("assets", {})
    season = data["story"].get("season_code")
    team = facts.get("team_name") or facts.get("team_external_id", "Equipo")
    is_win = facts.get("streak_kind", "win") == "win"
    length = int(facts.get("streak_length", 0))
    word = "VICTORIAS" if is_win else "DERROTAS"
    section = "Racha de victorias" if is_win else "Racha de derrotas"

    body: List[str] = []
    cx = CANVAS.width / 2

    # Kicker (same prominent style as the player card). A streak is a
    # season-spanning run, so the kicker frames the season, not a single round.
    body.append(C.accent_bar(CONTENT_X, MARGIN, 56, Line.HEAVY))
    body.append(C.text(CONTENT_X, MARGIN + 50, section.upper(), size=FontSize.H3,
                       weight=FontWeight.DISPLAY, fill=Color.WHITE,
                       tracking=LetterSpacing.HEADLINE, upper=True))
    body.append(C.text(CONTENT_X, MARGIN + 92, f"TEMPORADA {_season_label(season)}", size=FontSize.LABEL,
                       weight=FontWeight.LABEL, fill=Color.GREY,
                       tracking=LetterSpacing.CAPS, upper=True))
    body.append(_corner_mark())

    # Crest SLOT — a square with the team initials (a real crest drops in later).
    cs, cy0 = 220, 240
    px = cx - cs / 2
    crest = assets.get("team_crest")
    if crest:
        cid = f"cr{int(px)}_{cy0}"
        body.append(f'<clipPath id="{cid}"><rect x="{px:.0f}" y="{cy0}" width="{cs}" height="{cs}"/></clipPath>')
        body.append(C.rect(px, cy0, cs, cs, Color.INK))
        body.append(f'<image href="{crest}" x="{px:.0f}" y="{cy0}" width="{cs}" height="{cs}"'
                    f' clip-path="url(#{cid})" preserveAspectRatio="xMidYMid meet"/>')
    else:
        body.append(C.rect(px, cy0, cs, cs, Color.INK))
        body.append(C.text(cx, cy0 + cs * 0.66, C.initials_of(team), size=FontSize.DISPLAY,
                           weight=FontWeight.HERO, fill=Color.GREY, anchor="middle",
                           tracking=LetterSpacing.HERO))
    body.append(
        f'<rect x="{px:.0f}" y="{cy0}" width="{cs}" height="{cs}" fill="none"'
        f' stroke="{Color.GREY}" stroke-opacity="0.35" stroke-width="{Line.THIN}"/>'
    )
    body.append(C.accent_bar(px, cy0, 64))
    body.append(C.corner_frame(px, cy0, cs, cs, arm=44, corners=("tl", "br")))

    # Team name (steps down a size for long names so it never overflows).
    name_size = FontSize.H1 if len(team) <= 14 else FontSize.H2
    body.append(C.text(cx, cy0 + cs + 80, team.upper(), size=name_size, weight=FontWeight.DISPLAY,
                       fill=Color.WHITE, anchor="middle", tracking=LetterSpacing.HEADLINE, upper=True))

    # Hero streak number + label (number white — red stays the brand accent, on
    # the run chips below, never a semantic "good/bad").
    ny = cy0 + cs + 300
    body.append(C.text(cx, ny, str(length), size=FontSize.HERO, weight=FontWeight.HERO,
                       fill=Color.WHITE, anchor="middle", tracking=LetterSpacing.HERO))
    body.append(C.text(cx, ny + 40, f"{word} SEGUIDAS", size=FontSize.LABEL, weight=FontWeight.LABEL,
                       fill=Color.RED, anchor="middle", tracking=LetterSpacing.CAPS, upper=True))

    # The run, visualized: one mark per game. Red squares for wins, grey-outline
    # for losses. Capped so a long run still fits (a "+N" tail carries the rest).
    shown = min(length, 8)
    chip, gap = 72, Spacing.SM
    extra = length - shown
    tail_w = 44 if extra > 0 else 0
    total = shown * chip + (shown - 1) * gap + (tail_w + gap if extra > 0 else 0)
    sx = cx - total / 2
    ry = ny + 96
    letter = "V" if is_win else "D"
    for i in range(shown):
        x = sx + i * (chip + gap)
        if is_win:
            body.append(C.rect(x, ry, chip, chip, Color.RED, radius=Radius.SM))
            body.append(C.text(x + chip / 2, ry + chip / 2 + 12, letter, size=FontSize.H3,
                               weight=FontWeight.HERO, fill=Color.WHITE, anchor="middle"))
        else:
            body.append(C.rect(x, ry, chip, chip, Color.INK, radius=Radius.SM))
            body.append(f'<rect x="{x:.0f}" y="{ry}" width="{chip}" height="{chip}" fill="none"'
                        f' stroke="{Color.GREY}" stroke-opacity="0.6" stroke-width="{Line.MEDIUM}" rx="{Radius.SM}"/>')
            body.append(C.text(x + chip / 2, ry + chip / 2 + 12, letter, size=FontSize.H3,
                               weight=FontWeight.HERO, fill=Color.GREY, anchor="middle"))
    if extra > 0:
        tx = sx + shown * (chip + gap)
        body.append(C.text(tx + tail_w / 2, ry + chip / 2 + 10, f"+{extra}", size=FontSize.H3,
                           weight=FontWeight.HERO, fill=Color.GREY, anchor="middle"))

    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W, competition="Segunda FEB", season=season)
    body.append(ft)
    return _svg_document("".join(body), IMAGE_BACKGROUND)


# ---------------------------------------------------------------------------
# Template: BEST DUO (two teammates + their combined total)
# ---------------------------------------------------------------------------


def _rating_scale_card(x: float, y: float, w: float, value: float) -> tuple:
    """Boxed FEB RATING with a 0..10 segmented meter (the duo mockup's card)."""
    h = 118
    pad = Spacing.MD
    parts = [
        f'<rect x="{x:.0f}" y="{y}" width="{w:.0f}" height="{h}" fill="none"'
        f' stroke="{Color.GREY}" stroke-opacity="0.4" stroke-width="{Line.THIN}" rx="{Radius.MD}"/>',
        C.text(x + pad, y + 36, "FEB RATING", size=FontSize.MICRO, weight=FontWeight.LABEL,
               fill=Color.GREY, tracking=LetterSpacing.CAPS, upper=True),
        C.text(x + pad, y + 92, C._fmt_rating(value), size=FontSize.H2, weight=FontWeight.HERO,
               fill=Color.WHITE),
    ]
    mx = x + pad + 116
    mw = w - (mx - x) - pad
    my = y + 58
    seg, gap = 10, 5
    sw = (mw - (seg - 1) * gap) / seg
    filled = int(round(value))
    for i in range(seg):
        sx = mx + i * (sw + gap)
        if i < filled:
            parts.append(f'<rect x="{sx:.1f}" y="{my}" width="{sw:.1f}" height="18" fill="{Color.RED}" rx="2"/>')
        else:
            parts.append(f'<rect x="{sx:.1f}" y="{my}" width="{sw:.1f}" height="18" fill="{Color.GREY}"'
                         f' fill-opacity="0.3" rx="2"/>')
    for tick in (0, 5, 10):
        tx = mx + mw * (tick / 10)
        parts.append(C.text(tx, my + 44, str(tick), size=FontSize.MICRO, weight=FontWeight.LABEL,
                            fill=Color.GREY, anchor="middle"))
    return "".join(parts), h


def _duo_column(cx: float, avatar_cy: float, col_w: float, name: str, pts,
                rating: Any = None,
                *, initials: str, photo_uri=None, badge_uri=None) -> str:
    r = 108
    parts = [C.avatar(cx, avatar_cy, r, initials=initials, photo_uri=photo_uri, badge_uri=badge_uri)]
    side = 2 * r + 44
    parts.append(C.corner_frame(cx - side / 2, avatar_cy - side / 2, side, side,
                                arm=46, corners=("tl", "tr", "bl", "br")))
    ny = avatar_cy + r + 70
    parts.append(C.text(cx, ny, name.upper(), size=FontSize.H3, weight=FontWeight.DISPLAY,
                        fill=Color.WHITE, anchor="middle", tracking=LetterSpacing.HEADLINE, upper=True))
    bx, by, bh = cx - col_w / 2, ny + 42, 92
    parts.append(f'<rect x="{bx:.0f}" y="{by}" width="{col_w:.0f}" height="{bh}" fill="none"'
                 f' stroke="{Color.GREY}" stroke-opacity="0.4" stroke-width="{Line.THIN}" rx="{Radius.MD}"/>')
    parts.append(C.text(cx - 16, by + 66, str(pts), size=FontSize.H1, weight=FontWeight.HERO,
                        fill=Color.WHITE, anchor="end", tracking=LetterSpacing.DISPLAY))
    parts.append(C.text(cx + 6, by + 62, "PTS", size=FontSize.LABEL, weight=FontWeight.LABEL,
                        fill=Color.GREY, tracking=LetterSpacing.CAPS, upper=True))
    if rating is not None:
        card, _ = _rating_scale_card(bx, by + bh + Spacing.SM, col_w, float(rating))
        parts.append(card)
    return "".join(parts)


def render_best_duo(data: Dict[str, Any]) -> str:
    facts = data["story"]["facts"]
    season = data["story"].get("season_code")
    round_number = data["story"].get("round_number")
    n1 = facts.get("p1_name") or facts.get("p1_external_id", "Jugador 1")
    n2 = facts.get("p2_name") or facts.get("p2_external_id", "Jugador 2")
    assets = data.get("assets", {})

    body: List[str] = []
    # Kicker.
    body.append(C.accent_bar(CONTENT_X, MARGIN, 210, Line.HEAVY))
    body.append(C.text(CONTENT_X, MARGIN + 92, "EL MEJOR DÚO", size=FontSize.H1,
                       weight=FontWeight.DISPLAY, fill=Color.WHITE, tracking=LetterSpacing.HEADLINE, upper=True))
    body.append(C.text(CONTENT_X, MARGIN + 138, f"JORNADA {round_number}", size=FontSize.LABEL,
                       weight=FontWeight.LABEL, fill=Color.GREY, tracking=LetterSpacing.CAPS, upper=True))

    # Two columns (teammates, not a versus).
    left_cx = CONTENT_X + CONTENT_W * 0.25
    right_cx = CONTENT_X + CONTENT_W * 0.75
    col_w, avatar_cy = 384, 400
    body.append(_duo_column(left_cx, avatar_cy, col_w, n1, facts.get("p1_points", 0),
                            facts.get("p1_rating"), initials=C.initials_of(n1),
                            photo_uri=assets.get("p1_photo"), badge_uri=assets.get("team_crest")))
    body.append(_duo_column(right_cx, avatar_cy, col_w, n2, facts.get("p2_points", 0),
                            facts.get("p2_rating"), initials=C.initials_of(n2),
                            photo_uri=assets.get("p2_photo"), badge_uri=assets.get("team_crest")))
    # The uniting "+" on the center line, level with the stat boxes.
    body.append(C.text(CANVAS.width / 2, avatar_cy + 300, "+", size=FontSize.DISPLAY,
                       weight=FontWeight.HERO, fill=Color.WHITE, anchor="middle"))

    # Separator + center ball, then the combined total (the protagonist).
    sep_y = 902
    body.append(C.hline(CONTENT_X, sep_y, CONTENT_W, weight=Line.THIN, color=Color.GREY, opacity=0.25))
    body.append(C.icon(CANVAS.width / 2 - 18, sep_y - 18, Icons.BALL, size=36, color=Color.RED))

    combined = facts.get("combined_points", 0)
    box_w, box_h, box_y = 500, 210, 972
    box_x = CANVAS.width / 2 - box_w / 2
    body.append(C.corner_frame(box_x, box_y, box_w, box_h, arm=56, color=Color.RED,
                               corners=("tl", "tr", "bl", "br")))
    body.append(C.text(CANVAS.width / 2, box_y + 150, str(combined), size=FontSize.HERO,
                       weight=FontWeight.HERO, fill=Color.WHITE, anchor="middle", tracking=LetterSpacing.HERO))
    body.append(C.text(CANVAS.width / 2, box_y + 200, "PTS COMBINADOS", size=FontSize.LABEL,
                       weight=FontWeight.LABEL, fill=Color.RED, anchor="middle",
                       tracking=LetterSpacing.CAPS, upper=True))

    ft, _ = C.brand_footer(CONTENT_X, FOOTER_Y, CONTENT_W, competition="Segunda FEB", season=season)
    body.append(ft)
    return _svg_document("".join(body), BG_RED)  # high-energy mood for the duo


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_RENDERERS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "match_final": render_match_final,
    "player_of_round": render_player_of_round,
    "round_recap": render_round_recap,
    "stat_leaderboard": render_stat_leaderboard,
    "stat_hero": render_stat_hero,
    # Same layout as player_of_round (photo-first hero) but reachable from the
    # season-scoped CUSTOM_HERO story, so the operator can pick between the
    # crest silhouette (stat_hero) and the photo hero (stat_hero_photo) when
    # generating a single-player card from the Explorer.
    "stat_hero_photo": render_player_of_round,
    # Consecutive-game rachas — bespoke layout: giant streak number on the
    # left, full-bleed player photo on the right, name/team at the bottom.
    "player_streak": render_player_streak,
    "best_five": render_best_five_grid,
    "best_five_court": render_best_five_court,
    "team_streak": render_team_streak,
    "best_duo": render_best_duo,
}


def render_template(template_id: str, data: Dict[str, Any]) -> str:
    fn = _RENDERERS.get(template_id)
    if fn is None:
        raise KeyError(f"no component template for {template_id!r}")
    return fn(data)


def has_template(template_id: str) -> bool:
    return template_id in _RENDERERS
