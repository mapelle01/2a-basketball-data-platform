"""FEB SCORE! — Component Library v1.0.

Reusable, data-driven building blocks that render to SVG fragments. Each
component is a pure function of (position, width, data) → (svg, height): it
never positions itself absolutely, it reports the height it used so a template
can stack components in a vertical flow with system spacing.

Every visual decision reads a token from ``design_system`` — no component
hardcodes a hex, size or space. Components compose (a Player Hero embeds a Stat
Block; a Stat Block embeds stat numbers). Fallbacks keep a piece valid when a
logo/photo/secondary datum is missing.

The five priority components:
  match_header · scoreboard · player_hero · stat_block · brand_footer
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

from .design_system import (
    Brand,
    Color,
    Font,
    FontSize,
    FontWeight,
    IconStyle,
    Icons,
    LetterSpacing,
    Line,
    Radius,
    Spacing,
)

SVG = str  # an SVG fragment
Rendered = Tuple[SVG, int]  # (fragment, height_used)


# ---------------------------------------------------------------------------
# Atoms — the indivisible primitives
# ---------------------------------------------------------------------------


def text(
    x: float,
    y: float,
    value: str,
    *,
    size: int,
    weight: int,
    fill: str,
    anchor: str = "start",
    tracking: float = LetterSpacing.NORMAL,
    upper: bool = False,
    italic: bool = False,
) -> SVG:
    content = escape(value.upper() if upper else value)
    style = ' font-style="italic"' if italic else ""
    return (
        f'<text x="{_n(x)}" y="{_n(y)}" fill="{fill}" font-family="{Font.FAMILY}"'
        f' font-size="{size}" font-weight="{weight}" text-anchor="{anchor}"'
        f' letter-spacing="{tracking}"{style}>{content}</text>'
    )


def rect(x: float, y: float, w: float, h: float, fill: str, radius: int = 0) -> SVG:
    r = f' rx="{radius}"' if radius else ""
    return f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" fill="{fill}"{r}/>'


def hline(x: float, y: float, w: float, *, weight: int = Line.THIN,
          color: str = Color.GREY, opacity: float = 1.0) -> SVG:
    op = f' stroke-opacity="{opacity}"' if opacity < 1 else ""
    return (
        f'<line x1="{_n(x)}" y1="{_n(y)}" x2="{_n(x + w)}" y2="{_n(y)}"'
        f' stroke="{color}" stroke-width="{weight}"{op}/>'
    )


def vline(x: float, y: float, h: float, *, weight: int = Line.THIN,
          color: str = Color.GREY, opacity: float = 1.0) -> SVG:
    op = f' stroke-opacity="{opacity}"' if opacity < 1 else ""
    return (
        f'<line x1="{_n(x)}" y1="{_n(y)}" x2="{_n(x)}" y2="{_n(y + h)}"'
        f' stroke="{color}" stroke-width="{weight}"{op}/>'
    )


def accent_bar(x: float, y: float, w: float, h: float = Line.HEAVY) -> SVG:
    """The signature red accent bar. The one licensed use of red as a shape."""
    return rect(x, y, w, h, Color.RED)


def icon(x: float, y: float, path: str, *, size: int = 24, color: str = Color.WHITE) -> SVG:
    scale = size / IconStyle.GRID
    return (
        f'<g transform="translate({_n(x)},{_n(y)}) scale({_n(scale)})">'
        f'<path d="{path}" fill="{IconStyle.FILL}" stroke="{color}"'
        f' stroke-width="{IconStyle.STROKE_WIDTH}" stroke-linecap="{IconStyle.LINECAP}"'
        f' stroke-linejoin="{IconStyle.LINEJOIN}"/></g>'
    )


def status_pill(x: float, y: float, label: str, *, live: bool = False) -> SVG:
    """A status tag (FINAL / LIVE / …). Red fill only for live/key states."""
    label_u = label.upper()
    pad_x, h = Spacing.SM, 34
    w = pad_x * 2 + len(label_u) * (FontSize.MICRO * 0.68)
    bg = Color.RED if live else Color.INK
    # Non-live pills get a hairline border so they read on any background.
    border = "" if live else (
        f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{h}" fill="none"'
        f' stroke="{Color.GREY}" stroke-opacity="0.5" stroke-width="{Line.THIN}"/>'
    )
    return (
        rect(x, y, w, h, bg, radius=0)
        + border
        + text(x + pad_x, y + h - 11, label_u, size=FontSize.MICRO, weight=FontWeight.LABEL,
               fill=Color.WHITE, tracking=LetterSpacing.CAPS, upper=True)
    ), w  # returns (svg, width) — pills flow horizontally


# ---------------------------------------------------------------------------
# 01 — MATCH HEADER
# ---------------------------------------------------------------------------


def match_header(
    x: float,
    y: float,
    width: float,
    *,
    competition: str,
    round_label: str,
    status: Optional[str] = None,
    on_dark: bool = True,
    left_inset: float = 0,
) -> Rendered:
    """Context strip: competition + round on the left, status pill on the right.
    Compact; never competes with the scoreboard. ``left_inset`` shifts the
    eyebrow right (e.g. to sit next to a competition mark the caller drew) and
    replaces the red accent bar."""
    fg = Color.WHITE if on_dark else Color.BLACK
    parts: List[SVG] = []
    if left_inset > 0:
        # A competition mark sits to the left (drawn by the caller): it already
        # says the competition, so the eyebrow is just the context (round) — no
        # repetition, matching how league seals are used editorially.
        tx, ty = x + left_inset, y + 34
        eyebrow = round_label.upper()
    else:
        parts.append(accent_bar(x, y, 48, Line.HEAVY))  # red eyebrow accent
        tx, ty = x, y + 30
        eyebrow = f"{competition} · {round_label}".upper()
    parts.append(text(tx, ty, eyebrow, size=FontSize.LABEL, weight=FontWeight.LABEL,
                      fill=Color.GREY, tracking=LetterSpacing.CAPS, upper=True))
    if status:
        pill_svg, pill_w = status_pill(
            x + width - _pill_width(status), y + 4, status,
            live=status.upper() in {"LIVE", "EN VIVO", "DIRECTO"},
        )
        parts.append(pill_svg)
    return _group(parts), 40


# ---------------------------------------------------------------------------
# 02 — SCOREBOARD
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TeamSide:
    name: str
    score: int
    is_winner: bool = False


def scoreboard(
    x: float,
    y: float,
    width: float,
    *,
    home: TeamSide,
    away: TeamSide,
    variant: str = "hero",
    on_dark: bool = True,
) -> Rendered:
    """Match result. Number-first: score dominates, team second. Red marks the
    winner only. Works with zero logos.

    variants: hero (stacked, huge) · compact (one line) · minimal (score only).
    """
    fg = Color.WHITE if on_dark else Color.BLACK
    if variant == "minimal":
        return _scoreboard_minimal(x, y, width, home, away, fg)
    if variant == "compact":
        return _scoreboard_compact(x, y, width, home, away, fg)
    return _scoreboard_hero(x, y, width, home, away, fg)


def _score_color(side: TeamSide, fg: str) -> str:
    return Color.RED if side.is_winner else fg


def _scoreboard_hero(x, y, width, home, away, fg) -> Rendered:
    """Two columns side by side — team name above, giant score below — with a
    center ball mark. Number-first and balanced (no empty gutter). Winner red."""
    parts: List[SVG] = []
    half = width / 2
    hx = x + half * 0.5          # center of the home column
    ax = x + half + half * 0.5   # center of the away column
    cx = x + half                # center line
    name_y = y + 44
    num_y = y + 236              # baseline of the giant numbers

    for col_cx, side in ((hx, home), (ax, away)):
        parts.append(text(col_cx, name_y, side.name.upper(), size=FontSize.H3,
                          weight=FontWeight.DISPLAY, fill=fg, anchor="middle",
                          tracking=LetterSpacing.HEADLINE, upper=True))
        parts.append(text(col_cx, num_y, str(side.score), size=FontSize.HERO,
                          weight=FontWeight.HERO, fill=_score_color(side, fg),
                          anchor="middle", tracking=LetterSpacing.HERO))

    # Center ball mark, vertically aligned with the numbers.
    ball_cy = num_y - 66
    parts.append(icon(cx - 18, ball_cy - 18, Icons.BALL, size=36, color=Color.GREY))
    return _group(parts), 268


def _scoreboard_compact(x, y, width, home, away, fg) -> Rendered:
    parts: List[SVG] = []
    parts.append(text(x, y + 60, home.name.upper(), size=FontSize.H3,
                      weight=FontWeight.TITLE, fill=fg, upper=True))
    parts.append(text(x + width, y + 60, away.name.upper(), size=FontSize.H3,
                      weight=FontWeight.TITLE, fill=fg, anchor="end", upper=True))
    parts.append(text(x + width / 2 - 60, y + 60, str(home.score), size=FontSize.H1,
                      weight=FontWeight.HERO, fill=_score_color(home, fg), anchor="end"))
    parts.append(text(x + width / 2, y + 60, "–", size=FontSize.H2, weight=FontWeight.HERO,
                      fill=Color.GREY, anchor="middle"))
    parts.append(text(x + width / 2 + 60, y + 60, str(away.score), size=FontSize.H1,
                      weight=FontWeight.HERO, fill=_score_color(away, fg)))
    return _group(parts), 96


def _scoreboard_minimal(x, y, width, home, away, fg) -> Rendered:
    line = f"{home.score} – {away.score}"
    parts = [text(x + width / 2, y + 70, line, size=FontSize.H1, weight=FontWeight.HERO,
                  fill=fg, anchor="middle", tracking=LetterSpacing.DISPLAY)]
    return _group(parts), 96


# ---------------------------------------------------------------------------
# 03 — PLAYER HERO
# ---------------------------------------------------------------------------


def player_hero(
    x: float,
    y: float,
    width: float,
    *,
    name: str,
    team: str,
    primary_stat: str,
    primary_label: str,
    secondary_stats: Sequence[Tuple[str, str]] = (),
    initials: Optional[str] = None,
    badge: Optional[str] = None,
    on_dark: bool = True,
) -> Rendered:
    """A featured player. Combines identity + a hero Stat Block. Valid WITHOUT a
    photo: falls back to a premium typographic composition (large initials mark),
    never a childish placeholder."""
    fg = Color.WHITE if on_dark else Color.BLACK
    parts: List[SVG] = []

    # Fallback "portrait": a photo-shaped panel (3:4) — INK fill so it reads as a
    # clean frame, a hairline border, a red corner accent, and large initials set
    # low like a name plate. Editorial placeholder, not a cartoon avatar.
    bw_, bh_ = 300, 400
    cx = x + width / 2
    px = cx - bw_ / 2
    parts.append(rect(px, y, bw_, bh_, Color.INK))
    parts.append(
        f'<rect x="{_n(px)}" y="{_n(y)}" width="{bw_}" height="{bh_}" fill="none"'
        f' stroke="{Color.GREY}" stroke-opacity="0.35" stroke-width="{Line.THIN}"/>'
    )
    parts.append(hline(px, y, 72, weight=Line.HEAVY, color=Color.RED))       # corner accent
    parts.append(vline(px, y, 72, weight=Line.HEAVY, color=Color.RED))
    parts.append(text(cx, y + bh_ * 0.62, (initials or "—"), size=FontSize.DISPLAY + 20,
                      weight=FontWeight.HERO, fill=Color.GREY, anchor="middle",
                      tracking=LetterSpacing.HERO))
    if badge:
        bw = _pill_width(badge)
        pill, _ = status_pill(cx + bw_ / 2 - bw, y + bh_ - 44, badge, live=True)
        parts.append(pill)

    cursor = y + bh_ + Spacing.XL
    # Identity
    parts.append(text(cx, cursor + 60, name.upper(), size=FontSize.H1, weight=FontWeight.DISPLAY,
                      fill=fg, anchor="middle", tracking=LetterSpacing.HEADLINE, upper=True))
    parts.append(text(cx, cursor + 100, team.upper(), size=FontSize.LABEL, weight=FontWeight.LABEL,
                      fill=Color.GREY, anchor="middle", tracking=LetterSpacing.CAPS, upper=True))
    cursor += 130

    # Embedded hero Stat Block
    sb, sb_h = stat_block(
        x, cursor, width,
        primary=primary_stat, primary_label=primary_label,
        secondary_stats=secondary_stats, variant="hero", on_dark=on_dark, center=True,
    )
    parts.append(sb)
    return _group(parts), (cursor - y) + sb_h


# ---------------------------------------------------------------------------
# 04 — STAT BLOCK
# ---------------------------------------------------------------------------


def stat_block(
    x: float,
    y: float,
    width: float,
    *,
    primary: str,
    primary_label: str,
    secondary_stats: Sequence[Tuple[str, str]] = (),
    variant: str = "hero",
    on_dark: bool = True,
    center: bool = False,
) -> Rendered:
    """A primary stat + optional secondary stats. Priority: number → label →
    secondary. Red highlights the primary label only when it earns attention.

    variants: hero (huge number) · standard · compact · inline.
    """
    fg = Color.WHITE if on_dark else Color.BLACK
    if variant == "inline":
        return _stat_inline(x, y, width, primary, primary_label, secondary_stats, fg)
    return _stat_stacked(x, y, width, primary, primary_label, secondary_stats, fg, variant, center)


def _stat_stacked(x, y, width, primary, primary_label, secondary, fg, variant, center) -> Rendered:
    num_size = {"hero": FontSize.HERO, "standard": FontSize.H1, "compact": FontSize.H2}.get(
        variant, FontSize.HERO
    )
    anchor = "middle" if center else "start"
    ox = x + width / 2 if center else x
    parts: List[SVG] = []
    parts.append(text(ox, y + num_size * 0.78, str(primary), size=num_size,
                      weight=FontWeight.HERO, fill=fg, anchor=anchor, tracking=LetterSpacing.HERO))
    parts.append(text(ox, y + num_size * 0.78 + 30, primary_label.upper(), size=FontSize.LABEL,
                      weight=FontWeight.LABEL, fill=Color.RED, anchor=anchor,
                      tracking=LetterSpacing.CAPS, upper=True))
    h = int(num_size * 0.78 + 40)

    if secondary:
        row_y = y + h + Spacing.LG
        n = len(secondary)
        col_w = width / n
        for i, (val, lab) in enumerate(secondary):
            col_cx = x + col_w * i + col_w / 2
            parts.append(text(col_cx, row_y + 40, str(val), size=FontSize.H3,
                              weight=FontWeight.HERO, fill=fg, anchor="middle"))
            parts.append(text(col_cx, row_y + 70, lab.upper(), size=FontSize.MICRO,
                              weight=FontWeight.LABEL, fill=Color.GREY, anchor="middle",
                              tracking=LetterSpacing.CAPS, upper=True))
            if i > 0:
                parts.append(vline(x + col_w * i, row_y + 6, 68, color=Color.INK))
        h += Spacing.LG + 80
    return _group(parts), h


def stat_group(
    x: float,
    y: float,
    width: float,
    stats: Sequence[Tuple[str, str]],
    *,
    on_dark: bool = True,
    highlight_first: bool = False,
) -> Rendered:
    """A horizontal row of equal stat columns (number above label, dividers
    between). The board's STAT GROUP. Reused for secondary-data strips."""
    fg = Color.WHITE if on_dark else Color.BLACK
    n = max(1, len(stats))
    col_w = width / n
    parts: List[SVG] = []
    for i, (val, lab) in enumerate(stats):
        cx = x + col_w * i + col_w / 2
        color = Color.RED if (highlight_first and i == 0) else fg
        parts.append(text(cx, y + 58, str(val), size=FontSize.H1, weight=FontWeight.HERO,
                          fill=color, anchor="middle"))
        parts.append(text(cx, y + 92, lab.upper(), size=FontSize.MICRO, weight=FontWeight.LABEL,
                          fill=Color.GREY, anchor="middle", tracking=LetterSpacing.CAPS, upper=True))
        if i > 0:
            parts.append(vline(x + col_w * i, y + 12, 80, color=Color.INK))
    return _group(parts), 104


# ---------------------------------------------------------------------------
# FEB RATING — the signature 0..10 mark, encoded within the palette
# ---------------------------------------------------------------------------
# Red is NOT semantic here (in sport/data red reads as "bad"). Red is the BRAND
# color, carried by the proportional meter — a fuller bar means a better rating,
# which IS intuitive. The number's QUALITY is read by brightness: white for a
# solid game, grey for a quiet one. The elite tier is marked by MAX contrast
# (a white fill), never by red-means-good.

RATING_ELITE = 8.0    # >= this: max brightness (white fill on the chip)
RATING_GOOD = 6.5     # >= this: white number (a solid game)
# below RATING_GOOD: grey number (a quiet game)
_RATING_METER_MIN = 5.0   # the meter maps 5..10 → 0..100% (the useful range),
_RATING_METER_MAX = 10.0  # so real differences read clearly (most are 5.5+).


def _rating_color(value: float) -> str:
    """Number color by brightness — never red (red isn't 'good' here)."""
    return Color.WHITE if value >= RATING_GOOD else Color.GREY


def _rating_fill(value: float) -> float:
    span = _RATING_METER_MAX - _RATING_METER_MIN
    return max(0.0, min(1.0, (value - _RATING_METER_MIN) / span))


def _fmt_rating(value: float) -> str:
    return f"{value:.1f}" if value < 10 else "10"


def rating_badge(
    x: float,
    y: float,
    value: float,
    *,
    variant: str = "hero",
    width: float = 360,
    on_dark: bool = True,
) -> Rendered:
    """The FEB Rating mark. variants:
    hero    — giant number + RATING label + proportional red meter (protagonist)
    chip    — compact boxed number for lists/rankings (elite = red fill)
    inline  — number + tiny meter, for a stat row
    """
    if variant == "chip":
        return _rating_chip(x, y, value)
    if variant == "inline":
        return _rating_inline(x, y, value, width)
    return _rating_hero(x, y, value, width, on_dark)


def _rating_hero(x, y, value, width, on_dark) -> Rendered:
    parts: List[SVG] = []
    cx = x + width / 2
    color = _rating_color(value)
    parts.append(text(cx, y + 130, _fmt_rating(value), size=FontSize.HERO,
                      weight=FontWeight.HERO, fill=color, anchor="middle",
                      tracking=LetterSpacing.HERO))
    parts.append(text(cx, y + 168, "RATING", size=FontSize.LABEL, weight=FontWeight.LABEL,
                      fill=Color.GREY, anchor="middle", tracking=LetterSpacing.CAPS, upper=True))
    # Proportional red meter under the number.
    mw, mh, my = width * 0.62, 8, y + 196
    mx = cx - mw / 2
    parts.append(rect(mx, my, mw, mh, Color.INK))
    parts.append(rect(mx, my, mw * _rating_fill(value), mh, Color.RED))
    return _group(parts), 220


def _rating_chip(x, y, value) -> Rendered:
    """Compact boxed rating. Tier by BRIGHTNESS (elite = white fill / black text
    = max contrast), plus a proportional red brand meter along the bottom edge.
    Red never means 'good' — the meter length does."""
    size = 88
    elite = value >= RATING_ELITE
    good = value >= RATING_GOOD
    if elite:
        bg, txt, border = Color.WHITE, Color.BLACK, ""
    else:
        bg, txt = Color.INK, (Color.WHITE if good else Color.GREY)
        edge = Color.WHITE if good else Color.GREY
        border = (
            f'<rect x="{_n(x)}" y="{_n(y)}" width="{size}" height="{size}" fill="none"'
            f' stroke="{edge}" stroke-opacity="0.6" stroke-width="{Line.MEDIUM}" rx="{Radius.SM}"/>'
        )
    parts = [
        rect(x, y, size, size, bg, radius=Radius.SM),
        border,
        text(x + size / 2, y + size / 2 + 14, _fmt_rating(value), size=FontSize.H3,
             weight=FontWeight.HERO, fill=txt, anchor="middle"),
        # brand meter along the bottom edge
        rect(x + 8, y + size - 12, size - 16, 5, Color.INK if elite else Color.BLACK),
        rect(x + 8, y + size - 12, (size - 16) * _rating_fill(value), 5, Color.RED),
    ]
    return _group(parts), size


def _rating_inline(x, y, value, width) -> Rendered:
    color = _rating_color(value)
    parts = [
        text(x, y + 40, _fmt_rating(value), size=FontSize.H2, weight=FontWeight.HERO, fill=color),
        text(x + 110, y + 40, "RATING", size=FontSize.MICRO, weight=FontWeight.LABEL,
             fill=Color.GREY, tracking=LetterSpacing.CAPS, upper=True),
    ]
    mw, my = width - 260, y + 28
    mx = x + 250
    parts.append(rect(mx, my, mw, 6, Color.INK))
    parts.append(rect(mx, my, mw * _rating_fill(value), 6, Color.RED))
    return _group(parts), 56


def rating_scale(x: float, y: float, width: float, value: float) -> Rendered:
    """The 0..10 scale with a marker at the player's rating — an educational
    strip (the 'rating tipoff' idea), monochrome + red marker."""
    parts: List[SVG] = []
    parts.append(rect(x, y, width, 10, Color.INK))
    parts.append(rect(x, y, width * (value / 10.0), 10, Color.RED))
    for tick in (0, 5, 10):
        tx = x + width * (tick / 10.0)
        parts.append(vline(tx, y - 6, 22, weight=Line.THIN, color=Color.GREY, opacity=0.5))
        parts.append(text(tx, y + 48, str(tick), size=FontSize.MICRO, weight=FontWeight.LABEL,
                          fill=Color.GREY, anchor="middle"))
    # Marker
    mx = x + width * (value / 10.0)
    parts.append(rect(mx - 3, y - 10, 6, 30, Color.RED))
    parts.append(text(mx, y - 20, _fmt_rating(value), size=FontSize.BODY, weight=FontWeight.HERO,
                      fill=Color.WHITE, anchor="middle"))
    return _group(parts), 70


def _stat_inline(x, y, width, primary, primary_label, secondary, fg) -> Rendered:
    parts: List[SVG] = []
    parts.append(text(x, y + 44, str(primary), size=FontSize.H2, weight=FontWeight.HERO, fill=fg))
    parts.append(text(x + 90, y + 44, primary_label.upper(), size=FontSize.LABEL,
                      weight=FontWeight.LABEL, fill=Color.RED, tracking=LetterSpacing.CAPS, upper=True))
    cx = x + 260
    for val, lab in secondary:
        parts.append(text(cx, y + 44, f"{val} {lab.upper()}", size=FontSize.LABEL,
                          weight=FontWeight.LABEL, fill=Color.GREY))
        cx += 130
    return _group(parts), 56


# ---------------------------------------------------------------------------
# 05 — BRAND FOOTER
# ---------------------------------------------------------------------------


def brand_footer(
    x: float,
    y: float,
    width: float,
    *,
    competition: Optional[str] = None,
    season: Optional[str] = None,
    variant: str = "dark",
) -> Rendered:
    """Closes a piece and reinforces the brand — discreet, never a giant
    watermark. variants: dark (white mark) · light (black mark) · compact (FS!).
    """
    on_dark = variant != "light"
    fg = Color.WHITE if on_dark else Color.BLACK
    parts: List[SVG] = []
    parts.append(accent_bar(x, y, 4, 30))  # small vertical red accent
    if variant == "compact":
        parts.append(text(x + 16, y + 24, Brand.COMPACT_MARK, size=FontSize.LABEL,
                          weight=FontWeight.DISPLAY, fill=fg, italic=True))
    else:
        parts.append(text(x + 16, y + 24, Brand.NAME, size=FontSize.LABEL,
                          weight=FontWeight.DISPLAY, fill=fg, italic=True,
                          tracking=LetterSpacing.HEADLINE))
    meta = " · ".join([m for m in (competition, season) if m])
    if meta:
        parts.append(text(x + width, y + 24, meta.upper(), size=FontSize.MICRO,
                          weight=FontWeight.LABEL, fill=Color.GREY, anchor="end",
                          tracking=LetterSpacing.LABEL, upper=True))
    return _group(parts), 40


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _group(parts: Sequence[SVG]) -> SVG:
    return "".join(parts)


def _pill_width(label: str) -> float:
    return Spacing.SM * 2 + len(label) * (FontSize.MICRO * 0.68)


def _n(v: float) -> str:
    """Format a number: drop the trailing .0 so the SVG stays clean."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)
