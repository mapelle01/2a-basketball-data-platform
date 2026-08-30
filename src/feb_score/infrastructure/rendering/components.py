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


def _opacity_attr(opacity: Optional[float]) -> str:
    """``fill-opacity`` only when asked. Softening a palette colour is how a
    light surface gets a legible secondary tone without adding a seventh hue."""
    return "" if opacity is None else f' fill-opacity="{opacity}"'


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
    opacity: Optional[float] = None,
) -> SVG:
    content = escape(value.upper() if upper else value)
    style = ' font-style="italic"' if italic else ""
    return (
        f'<text x="{_n(x)}" y="{_n(y)}" fill="{fill}"{_opacity_attr(opacity)} font-family="{Font.FAMILY}"'
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
    # The text is drawn CAPS-tracked, so its width includes the letter-spacing
    # between glyphs; sizing the box on the bare advance let the last letters
    # (the "S" of "MÁX. ASISTENCIAS") spill outside the red rectangle.
    w = pad_x * 2 + _caps_width(label_u, FontSize.MICRO)
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
# Frames & asset slots — the composition-engine primitives
# ---------------------------------------------------------------------------
# These carry the layer model IDENTITY / PHOTO: each is a SLOT that renders the
# real asset when present and degrades to a monochrome brand fallback when not.
# Nothing here invents data — a missing photo/logo becomes typographic chrome.


_Corner = str  # one of "tl", "tr", "bl", "br"


def corner_frame(
    x: float, y: float, w: float, h: float, *,
    arm: float = 64, thickness: int = Line.HEAVY, color: str = Color.WHITE,
    corners: Sequence[_Corner] = ("tl", "br"),
) -> SVG:
    """The signature L-bracket encuadre: short arms at chosen corners of the
    (x, y, w, h) box. Pure brand chrome — monochrome, no assets, no fill. Frames
    a photo, a hero number or a whole composition (the FEB SCORE! 'marco')."""
    x2, y2 = x + w, y + h
    t = thickness
    parts: List[SVG] = []
    for c in corners:
        if c == "tl":
            parts += [rect(x, y, arm, t, color), rect(x, y, t, arm, color)]
        elif c == "tr":
            parts += [rect(x2 - arm, y, arm, t, color), rect(x2 - t, y, t, arm, color)]
        elif c == "bl":
            parts += [rect(x, y2 - t, arm, t, color), rect(x, y2 - arm, t, arm, color)]
        elif c == "br":
            parts += [rect(x2 - arm, y2 - t, arm, t, color), rect(x2 - t, y2 - arm, t, arm, color)]
    return _group(parts)


def initials_of(name: str, n: int = 2) -> str:
    """Initials fallback for an avatar/portrait when no photo is available."""
    words = [w for w in name.replace(".", " ").split() if w]
    if not words:
        return "—"
    if len(words) == 1:
        return words[0][:n].upper()
    return (words[0][0] + words[-1][0]).upper()


def avatar(
    cx: float, cy: float, r: float, *,
    photo_uri: Optional[str] = None, initials: Optional[str] = None,
    badge_uri: Optional[str] = None, ring: bool = True,
) -> SVG:
    """A circular player slot (the lineup/ranking mugshot). Renders the photo
    clipped to a circle when ``photo_uri`` is given; otherwise an INK disc with
    the player's initials — a clean fallback, never an empty hole. ``badge_uri``
    (a team crest) is an optional small mark at the bottom-right; omitted when
    the crest isn't available."""
    parts: List[SVG] = []
    if photo_uri:
        cid = f"av{_n(cx)}_{_n(cy)}_{_n(r)}".replace(".", "")
        parts.append(f'<clipPath id="{cid}"><circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}"/></clipPath>')
        parts.append(
            f'<image href="{photo_uri}" x="{_n(cx - r)}" y="{_n(cy - r)}"'
            f' width="{_n(2 * r)}" height="{_n(2 * r)}" clip-path="url(#{cid})"'
            # Top-aligned, not centred: these are half-body federation portraits,
            # so centring the crop lands on the chest and fills the circle with
            # jersey. Aligning to the top keeps the head whole and crops the
            # torso, which is what a mugshot slot wants.
            f' preserveAspectRatio="xMidYMin slice"/>'
        )
    else:
        parts.append(f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}" fill="{Color.INK}"/>')
        parts.append(text(cx, cy + r * 0.34, (initials or "—"), size=int(r * 0.72),
                          weight=FontWeight.HERO, fill=Color.GREY, anchor="middle"))
    if ring:
        parts.append(
            f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}" fill="none"'
            f' stroke="{Color.GREY}" stroke-opacity="0.4" stroke-width="{Line.THIN}"/>'
        )
    if badge_uri:
        # A clean crest "coin": the FEB crest PNGs mostly ship on an OPAQUE WHITE
        # square, so the old black backing showed a white square with black
        # corners peeking out — the "se ve mal" the operator flagged. Instead put
        # the crest on a white disc and clip it to a circle, so an opaque-white
        # crest melts into the plate and a transparent one sits on neutral white;
        # a thin ring defines the coin on both the light and dark cards.
        br = r * 0.44
        bx, by = cx + r * 0.60, cy + r * 0.60
        plate = br + 3
        bid = f"bdg{_n(bx)}_{_n(by)}".replace(".", "").replace("-", "m")
        pad = br * 0.90            # breathing room so full-bleed crests don't clip
        parts.append(f'<circle cx="{_n(bx)}" cy="{_n(by)}" r="{_n(plate)}" fill="{Color.WHITE}"/>')
        parts.append(f'<clipPath id="{bid}"><circle cx="{_n(bx)}" cy="{_n(by)}" r="{_n(br)}"/></clipPath>')
        parts.append(
            f'<image href="{badge_uri}" x="{_n(bx - pad)}" y="{_n(by - pad)}"'
            f' width="{_n(2 * pad)}" height="{_n(2 * pad)}" clip-path="url(#{bid})"'
            f' preserveAspectRatio="xMidYMid meet"/>'
        )
        parts.append(
            f'<circle cx="{_n(bx)}" cy="{_n(by)}" r="{_n(plate)}" fill="none"'
            f' stroke="{Color.GREY}" stroke-opacity="0.45" stroke-width="{Line.THIN}"/>'
        )
    return _group(parts)


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
    winner_color: Optional[str] = None,
    loser_color: Optional[str] = None,
) -> Rendered:
    """Match result. Number-first: score dominates, team second. Red marks the
    winner only. Works with zero logos. ``winner_color``/``loser_color`` override
    the defaults (red winner, fg loser) — e.g. on the red-impact blowout mood,
    where red is the background, the winner reads white and the loser grey.

    variants: hero (stacked, huge) · compact (one line) · minimal (score only).
    """
    fg = Color.WHITE if on_dark else Color.BLACK
    wc = winner_color or Color.RED
    lc = loser_color or fg
    if variant == "minimal":
        return _scoreboard_minimal(x, y, width, home, away, fg)
    if variant == "compact":
        return _scoreboard_compact(x, y, width, home, away, fg, wc, lc)
    return _scoreboard_hero(x, y, width, home, away, fg, wc, lc)


def _score_color(side: TeamSide, winner_color: str, loser_color: str) -> str:
    return winner_color if side.is_winner else loser_color


def _scoreboard_hero(x, y, width, home, away, fg, wc=Color.RED, lc=None) -> Rendered:
    """Two columns side by side — team name above, giant score below — with a
    center ball mark. Number-first and balanced (no empty gutter). Winner red."""
    lc = lc if lc is not None else fg
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
                          weight=FontWeight.HERO, fill=_score_color(side, wc, lc),
                          anchor="middle", tracking=LetterSpacing.HERO))

    # Center ball mark, vertically aligned with the numbers.
    ball_cy = num_y - 66
    parts.append(icon(cx - 18, ball_cy - 18, Icons.BALL, size=36, color=Color.GREY))
    return _group(parts), 268


def _scoreboard_compact(x, y, width, home, away, fg, wc=Color.RED, lc=None) -> Rendered:
    lc = lc if lc is not None else fg
    parts: List[SVG] = []
    parts.append(text(x, y + 60, home.name.upper(), size=FontSize.H3,
                      weight=FontWeight.TITLE, fill=fg, upper=True))
    parts.append(text(x + width, y + 60, away.name.upper(), size=FontSize.H3,
                      weight=FontWeight.TITLE, fill=fg, anchor="end", upper=True))
    parts.append(text(x + width / 2 - 60, y + 60, str(home.score), size=FontSize.H1,
                      weight=FontWeight.HERO, fill=_score_color(home, wc, lc), anchor="end"))
    parts.append(text(x + width / 2, y + 60, "–", size=FontSize.H2, weight=FontWeight.HERO,
                      fill=Color.GREY, anchor="middle"))
    parts.append(text(x + width / 2 + 60, y + 60, str(away.score), size=FontSize.H1,
                      weight=FontWeight.HERO, fill=_score_color(away, wc, lc)))
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
    photo_uri: Optional[str] = None,
    badge: Optional[str] = None,
    on_dark: bool = True,
) -> Rendered:
    """A featured player. Combines identity + a hero Stat Block. The portrait is
    a SLOT: a real cutout when ``photo_uri`` is given, otherwise a premium
    typographic fallback (large initials mark) — never a childish placeholder.
    Either way it sits inside the signature L-bracket frame."""
    fg = Color.WHITE if on_dark else Color.BLACK
    parts: List[SVG] = []

    # PHOTO slot — a 3:4 portrait frame. With a cutout: the image, slice-fitted
    # and clipped to the panel. Without: an INK panel with large initials set low
    # like a name plate. Both wear the same white L-bracket encuadre + a red edge.
    bw_, bh_ = 300, 372
    cx = x + width / 2
    px = cx - bw_ / 2
    if photo_uri:
        cid = f"ph{_n(px)}_{_n(y)}".replace(".", "")
        parts.append(f'<clipPath id="{cid}"><rect x="{_n(px)}" y="{_n(y)}" width="{bw_}" height="{bh_}"/></clipPath>')
        parts.append(rect(px, y, bw_, bh_, Color.INK))
        parts.append(
            f'<image href="{photo_uri}" x="{_n(px)}" y="{_n(y)}" width="{bw_}" height="{bh_}"'
            f' clip-path="url(#{cid})" preserveAspectRatio="xMidYMid slice"/>'
        )
    else:
        parts.append(rect(px, y, bw_, bh_, Color.INK))
        parts.append(text(cx, y + bh_ * 0.62, (initials or "—"), size=FontSize.DISPLAY + 20,
                          weight=FontWeight.HERO, fill=Color.GREY, anchor="middle",
                          tracking=LetterSpacing.HERO))
    parts.append(
        f'<rect x="{_n(px)}" y="{_n(y)}" width="{bw_}" height="{bh_}" fill="none"'
        f' stroke="{Color.GREY}" stroke-opacity="0.35" stroke-width="{Line.THIN}"/>'
    )
    parts.append(accent_bar(px, y, 72))                                       # red top edge accent
    parts.append(corner_frame(px, y, bw_, bh_, arm=52, corners=("tl", "br")))  # signature encuadre
    if badge:
        # A centered plaque inside the portrait's lower edge — clear of the corner
        # brackets and of the name below, reads like a tag on the photo.
        bw = _pill_width(badge)
        pill, _ = status_pill(cx - bw / 2, y + bh_ - 46, badge, live=True)
        parts.append(pill)

    cursor = y + bh_ + Spacing.LG
    # Identity — step the name down for long names so it never overflows the frame.
    name_size = FontSize.H1 if len(name) <= 16 else FontSize.H2
    parts.append(text(cx, cursor + 58, name.upper(), size=name_size, weight=FontWeight.DISPLAY,
                      fill=fg, anchor="middle", tracking=LetterSpacing.HEADLINE, upper=True))
    parts.append(text(cx, cursor + 96, team.upper(), size=FontSize.LABEL, weight=FontWeight.LABEL,
                      fill=Color.GREY, anchor="middle", tracking=LetterSpacing.CAPS, upper=True))
    cursor += 128

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


# Proportions of the stacked stat block, tuned as a set (the hero number is the
# reference and everything else is a ratio of it, so the block scales together).
_SB_LABEL_RATIO = 0.19      # unit label vs the hero number — the unit belongs to
                            # the figure, so it must read as part of it, not as a caption
_SB_SECONDARY_RATIO = 0.30  # secondary figures vs the hero: ~3:1 keeps a clear
                            # hierarchy without demoting them to a footnote
_SB_COL_RATIO = 0.95        # column width vs the secondary figure size — tight
                            # enough that the secondaries read as ONE unit
# Upper bound on the advance of one uppercase Inter 600 glyph, in em. MEASURED
# with `resvg --query-all` over real labels (ROB .648, TAPONES .656, ROBOS .673,
# ROBOS+TAPONES .668), rounded up so the fit is conservative: overestimating
# only widens a column, underestimating overlaps two.
_SB_LABEL_ADVANCE = 0.70
# Upper bound on a HERO-weight digit's advance (incl. the "." in "20.2"), in em.
# Secondary figures are set with DISPLAY tracking, so this is deliberately
# generous — overestimating only widens a column, underestimating lets two
# figures touch.
_SB_NUM_ADVANCE = 0.66
_SB_LABEL_MIN = 13          # below this a unit label stops being readable


def _caps_width(text: str, size: float) -> float:
    """Rendered width of an uppercase, CAPS-tracked label."""
    n = len(text)
    return n * size * _SB_LABEL_ADVANCE + max(0, n - 1) * LetterSpacing.CAPS


def _stat_stacked(x, y, width, primary, primary_label, secondary, fg, variant, center) -> Rendered:
    num_size = {"hero": FontSize.HERO, "standard": FontSize.H1, "compact": FontSize.H2}.get(
        variant, FontSize.HERO
    )
    label_size = max(FontSize.LABEL, round(num_size * _SB_LABEL_RATIO))
    anchor = "middle" if center else "start"
    ox = x + width / 2 if center else x
    baseline = y + num_size * 0.78
    parts: List[SVG] = []
    parts.append(text(ox, baseline, str(primary), size=num_size,
                      weight=FontWeight.HERO, fill=fg, anchor=anchor, tracking=LetterSpacing.HERO))
    # Sit the unit under the figure: close enough to belong to it, but clear of
    # the digits. Scaled to the label so the clearance holds at any hero size —
    # 0.95 put the caps ~7px under the baseline and read as a collision.
    label_y = baseline + label_size * 1.30
    parts.append(text(ox, label_y, primary_label.upper(), size=label_size,
                      weight=FontWeight.DISPLAY, fill=Color.RED, anchor=anchor,
                      tracking=LetterSpacing.CAPS, upper=True))
    h = int(label_y - y + Spacing.SM)

    if secondary:
        # Group the secondary stats in a narrow band centered under the hero
        # number (not spread edge-to-edge), so they read as one tight unit.
        sec_size = max(FontSize.H3, round(num_size * _SB_SECONDARY_RATIO))
        lab_size = FontSize.LABEL
        n = len(secondary)
        # The band used to be sized from the FIGURE alone, so a label wider than
        # its column silently overlapped its neighbour — "ROBOS" and "TAPONES"
        # printed on top of each other with the divider buried under them. Size
        # it to whichever is wider, then shrink the label if even the full
        # content width cannot hold it.
        widest = max(_caps_width(str(lab), lab_size) for _, lab in secondary)
        # ...and by the VALUE: a 4-char figure like "20.2" is far wider than the
        # 2-digit number the old sizing assumed, so it nearly touched its
        # neighbour ("26 20.2" read as one blob). Size each column to whichever
        # is wider — label or figure — plus a gap, so short pairs breathe too.
        widest_val = max(len(str(val)) * sec_size * _SB_NUM_ADVANCE for val, _ in secondary)
        per_col = max(sec_size * 2 * _SB_COL_RATIO,
                      widest + Spacing.MD,
                      widest_val + Spacing.LG)
        band = min(width, n * per_col)
        bx = (ox - band / 2) if center else x
        col_w = band / n
        if widest + Spacing.MD > col_w:
            lab_size = max(
                _SB_LABEL_MIN, int(lab_size * (col_w - Spacing.MD) / widest)
            )
        row_y = y + h + Spacing.MD
        rule_h = sec_size + lab_size + Spacing.SM
        for i, (val, lab) in enumerate(secondary):
            col_cx = bx + col_w * i + col_w / 2
            parts.append(text(col_cx, row_y + sec_size * 0.78, str(val), size=sec_size,
                              weight=FontWeight.HERO, fill=fg, anchor="middle",
                              tracking=LetterSpacing.DISPLAY))
            parts.append(text(col_cx, row_y + sec_size * 0.78 + lab_size + 2, lab.upper(),
                              size=lab_size, weight=FontWeight.LABEL, fill=Color.GREY,
                              anchor="middle", tracking=LetterSpacing.CAPS, upper=True))
            if i > 0:
                parts.append(vline(bx + col_w * i, row_y, rule_h,
                                   color=Color.GREY, opacity=0.28))
        h += Spacing.MD + int(rule_h)
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
RATING_GOOD = 6.0     # >= this: white number (a normal game or better)
# below RATING_GOOD: grey number (a below-average game)
_RATING_METER_MIN = 4.0   # the meter maps 4..10 → 0..100% (the realistic band,
_RATING_METER_MAX = 10.0  # since the curve puts an average game near ~6.5).


def _rating_color(value: float) -> str:
    """Number color by brightness — never red (red isn't 'good' here)."""
    return Color.WHITE if value >= RATING_GOOD else Color.GREY


def _rating_fill(value: float) -> float:
    span = _RATING_METER_MAX - _RATING_METER_MIN
    return max(0.0, min(1.0, (value - _RATING_METER_MIN) / span))


def _fmt_rating(value: float) -> str:
    # Spanish decimal comma: the cards are written in Spanish, so 9,0 — not 9.0.
    return f"{value:.1f}".replace(".", ",") if value < 10 else "10"


# The FEB Rating is ONE recognizable object — a boxed note with a proportional
# red meter along its bottom edge — drawn at three sizes. It must read as the
# same mark on a ranking row, on an on-court lineup and on a player card, so
# there is deliberately no alternative shape: only S / M / L.
RATING_SIZES = {"s": 46, "m": 88, "l": 132}


def rating_badge(
    x: float,
    y: float,
    value: float,
    *,
    size: str = "m",
    on_dark: bool = True,
) -> Rendered:
    """The FEB Rating mark: a boxed note. ``size`` is "s" (lineups/lists),
    "m" (rankings) or "l" (protagonist on a player card). Tier reads by
    CONTRAST (elite = brightest fill); the red meter length carries the value —
    red never means "good"."""
    px = RATING_SIZES.get(size)
    if px is None:
        raise ValueError(f"unknown rating size {size!r}; use one of {sorted(RATING_SIZES)}")
    return _rating_chip(x, y, value, size=px, on_dark=on_dark)


def _rating_chip(x, y, value, size: int = 88, on_dark: bool = True) -> Rendered:
    """Compact boxed rating. Tier by CONTRAST against the background (elite = the
    most prominent fill), plus a proportional red brand meter along the bottom
    edge. Red never means 'good' — the meter length does. ``size`` scales the box
    (88 for rankings, 46 for the on-court 'mini' chip). ``on_dark`` inverts the
    tiers for a light background (elite = solid black on light)."""
    elite = value >= RATING_ELITE
    good = value >= RATING_GOOD
    num_size = FontSize.H3 if size >= 64 else FontSize.LABEL
    pad = max(6, round(size * 0.09))
    mh = max(4, round(size * 0.06))
    my = y + size - pad - mh
    border = ""
    if on_dark:
        # brightness = quality: elite is brightest (white).
        if elite:
            bg, txt, track = Color.WHITE, Color.BLACK, Color.INK
        else:
            bg, txt, track = Color.INK, (Color.WHITE if good else Color.GREY), Color.BLACK
            edge = Color.WHITE if good else Color.GREY
    else:
        # on light, darkness = quality: elite is darkest (black).
        if elite:
            bg, txt, track = Color.BLACK, Color.WHITE, Color.LIGHT_GREY
        else:
            bg, txt, track = Color.WHITE, (Color.BLACK if good else Color.GREY), Color.LIGHT_GREY
            edge = Color.INK if good else Color.GREY
    if not elite:
        border = (
            f'<rect x="{_n(x)}" y="{_n(y)}" width="{size}" height="{size}" fill="none"'
            f' stroke="{edge}" stroke-opacity="0.6" stroke-width="{Line.MEDIUM}" rx="{Radius.SM}"/>'
        )
    parts = [
        rect(x, y, size, size, bg, radius=Radius.SM),
        border,
        text(x + size / 2, y + size / 2 + num_size * 0.40, _fmt_rating(value), size=num_size,
             weight=FontWeight.HERO, fill=txt, anchor="middle"),
        # brand meter along the bottom edge
        rect(x + pad, my, size - 2 * pad, mh, track),
        rect(x + pad, my, (size - 2 * pad) * _rating_fill(value), mh, Color.RED),
    ]
    return _group(parts), size


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


def _short_season(season: Optional[str]) -> Optional[str]:
    """'2025-2026' → '2025-26' for a compact metadata line."""
    if not season:
        return season
    s = str(season)
    if "-" in s:
        a, b = s.split("-", 1)
        return f"{a}-{b[-2:]}" if len(b) == 4 else s
    return s


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
    # Full-bleed scrim so the wordmark reads cleanly over busy background marks
    # (the blueprint's technical ticks otherwise collide with "FEB SCORE!").
    # Assumes symmetric margins (x on each side).
    canvas_w = width + 2 * x
    scrim = Color.BLACK if on_dark else Color.WHITE
    parts.append(
        f'<rect x="0" y="{_n(y - 22)}" width="{_n(canvas_w)}" height="74"'
        f' fill="{scrim}" fill-opacity="0.88"/>'
    )
    parts.append(accent_bar(x, y, 4, 30))  # small vertical red accent
    if variant == "compact":
        parts.append(text(x + 16, y + 24, Brand.COMPACT_MARK, size=FontSize.LABEL,
                          weight=FontWeight.DISPLAY, fill=fg, italic=True))
    else:
        parts.append(text(x + 16, y + 24, Brand.NAME, size=FontSize.LABEL,
                          weight=FontWeight.DISPLAY, fill=fg, italic=True,
                          tracking=LetterSpacing.HEADLINE))
    meta = " · ".join([m for m in (competition, _short_season(season)) if m])
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
    # Must match status_pill's own width exactly, or the centered pill sits off
    # centre. Same CAPS-tracked measure, including the letter-spacing.
    return Spacing.SM * 2 + _caps_width(label.upper(), FontSize.MICRO)


def _n(v: float) -> str:
    """Format a number: drop the trailing .0 so the SVG stays clean."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)
