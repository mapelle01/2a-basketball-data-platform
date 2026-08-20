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


def hline(x: float, y: float, w: float, *, weight: int = Line.THIN, color: str = Color.GREY) -> SVG:
    return (
        f'<line x1="{_n(x)}" y1="{_n(y)}" x2="{_n(x + w)}" y2="{_n(y)}"'
        f' stroke="{color}" stroke-width="{weight}"/>'
    )


def vline(x: float, y: float, h: float, *, weight: int = Line.THIN, color: str = Color.GREY) -> SVG:
    return (
        f'<line x1="{_n(x)}" y1="{_n(y)}" x2="{_n(x)}" y2="{_n(y + h)}"'
        f' stroke="{color}" stroke-width="{weight}"/>'
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
    fg = Color.WHITE
    return (
        rect(x, y, w, h, bg, radius=0)
        + text(x + pad_x, y + h - 11, label_u, size=FontSize.MICRO, weight=FontWeight.LABEL,
               fill=fg, tracking=LetterSpacing.CAPS, upper=True)
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
) -> Rendered:
    """Context strip: competition + round on the left, status pill on the right.
    Compact; never competes with the scoreboard."""
    fg = Color.WHITE if on_dark else Color.BLACK
    parts: List[SVG] = []
    # Red eyebrow accent bar
    parts.append(accent_bar(x, y, 48, Line.HEAVY))
    eyebrow = f"{competition} · {round_label}".upper()
    parts.append(text(x, y + 30, eyebrow, size=FontSize.LABEL, weight=FontWeight.LABEL,
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
    parts: List[SVG] = []
    # HOME row
    parts.append(text(x, y + 40, home.name.upper(), size=FontSize.H2,
                      weight=FontWeight.DISPLAY, fill=fg, tracking=LetterSpacing.HEADLINE, upper=True))
    parts.append(text(x + width, y + 168, str(home.score), size=FontSize.HERO,
                      weight=FontWeight.HERO, fill=_score_color(home, fg), anchor="end",
                      tracking=LetterSpacing.HERO))
    # center divider with ball mark (knockout rect assumes a dark ground)
    mid = y + 220
    parts.append(hline(x, mid, width, weight=Line.MEDIUM, color=Color.GREY))
    parts.append(rect(x + width / 2 - 26, mid - 16, 52, 32, Color.BLACK))  # knockout behind ball
    parts.append(icon(x + width / 2 - 14, mid - 14, Icons.BALL, size=28, color=Color.GREY))
    # AWAY row
    parts.append(text(x, mid + 88, away.name.upper(), size=FontSize.H2,
                      weight=FontWeight.DISPLAY, fill=fg, tracking=LetterSpacing.HEADLINE, upper=True))
    parts.append(text(x + width, mid + 216, str(away.score), size=FontSize.HERO,
                      weight=FontWeight.HERO, fill=_score_color(away, fg), anchor="end",
                      tracking=LetterSpacing.HERO))
    return _group(parts), 470


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

    # Fallback "portrait": a bordered square with large initials + red corner
    # accent. Editorial, not a cartoon avatar.
    box = 300
    cx = x + width / 2
    parts.append(rect(cx - box / 2, y, box, box, Color.INK))
    parts.append(hline(cx - box / 2, y, 80, weight=Line.HEAVY, color=Color.RED))  # corner accent
    parts.append(vline(cx - box / 2, y, 80, weight=Line.HEAVY, color=Color.RED))
    parts.append(text(cx, y + box / 2 + 40, (initials or "—"), size=FontSize.DISPLAY,
                      weight=FontWeight.HERO, fill=Color.GREY, anchor="middle",
                      tracking=LetterSpacing.HERO))
    if badge:
        bw = _pill_width(badge)
        pill, _ = status_pill(cx + box / 2 - bw, y + box - 38, badge, live=True)
        parts.append(pill)

    cursor = y + box + Spacing.XL
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
