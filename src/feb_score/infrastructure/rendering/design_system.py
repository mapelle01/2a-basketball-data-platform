"""FEB SCORE! — Design tokens (identity v2.0).

Single source of truth for the visual identity, consolidated from the ten
official system boards (color, typography, logo, grid, shapes, photography,
background, icon, component, template). Every component and template reads
tokens from here — nothing hardcodes a hex, a font size or a spacing value.

Identity in one line: SPORTS DATA + EDITORIAL + PREMIUM + MODERN + DIGITAL.
Black / white = base · greys = structure · red = accent (≈60/25/15).
ONE TYPEFACE (Inter, five weights). NO extra colors. NO gradients. NO shadows.
CONTENT FIRST — BRAND SECOND.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


DESIGN_SYSTEM_VERSION = "2.0"


# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------

class Brand:
    NAME = "FEB SCORE!"
    WORDMARK_LINE_1 = "FEB"
    WORDMARK_LINE_2 = "SCORE!"
    COMPACT_MARK = "FS!"
    TAGLINE = "BASKETBALL. DATA. COMPETITION."
    SIGNATURE = "BASKETBALL DATA · STORIES · INSIGHTS"


# ---------------------------------------------------------------------------
# Color — the six official colors + semantic roles
# ---------------------------------------------------------------------------
# Proportion target ≈ 60% black/white, 25% greys/ink, 15% red. Red is an
# accent that guides attention to what matters (winner, status, key stat) —
# never a dominant surface, never decorative.

class Color:
    BLACK = "#000000"        # primary / main backgrounds / max contrast
    INK = "#111111"          # structural surfaces, panels, cards
    GREY = "#6B6B6B"         # secondary text, metadata, dividers
    LIGHT_GREY = "#E5E5E5"   # editorial surface, inactive
    RED = "#E10600"          # accent ONLY — winner, status, key highlight
    WHITE = "#FFFFFF"        # primary text on dark, contrast

    # Semantic role aliases (map role → value; components reference roles).
    PRIMARY = BLACK
    STRUCTURAL = INK
    SECONDARY = GREY
    SURFACE = LIGHT_GREY
    ACCENT = RED
    CONTRAST = WHITE


# ---------------------------------------------------------------------------
# Typography — Inter, five weights, numbers-first
# ---------------------------------------------------------------------------

class Font:
    FAMILY = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


class FontWeight:
    HERO = 900        # numbers, scores, hero figures — Inter Black
    DISPLAY = 800     # main headlines — Inter ExtraBold
    TITLE = 700       # secondary titles — Inter Bold
    LABEL = 600       # labels, categories, metadata — Inter SemiBold
    BODY = 400        # body, descriptions — Inter Regular


class FontSize:
    # Calibrated for the 1080x1350 canvas (typography board §13).
    HERO = 168        # scoreboard numbers, hero stat
    DISPLAY = 120     # DISPLAY / big headline
    H1 = 88
    H2 = 56
    H3 = 34
    LABEL = 22
    BODY = 24
    MICRO = 18        # metadata, footer legalese


class LetterSpacing:
    HERO = -4         # hero numbers: tight / slightly negative
    DISPLAY = -2
    HEADLINE = -0.5
    NORMAL = 0
    LABEL = 2         # labels open up slightly positive
    CAPS = 3
    EYEBROW = 4       # top-of-canvas micro headers


class LineHeight:
    HERO = 0.95       # 90–100 %
    HEADLINE = 1.08   # 100–115 %
    BODY = 1.45       # 140–150 %
    LABEL = 0.95


# ---------------------------------------------------------------------------
# Spacing — 8px base scale (with 4/12 micro half-steps)
# ---------------------------------------------------------------------------

class Spacing:
    MICRO = 4          # number ↔ label hairline, icon internal
    XS = 8             # number ↔ label
    SM = 12            # icon ↔ text
    MD = 16            # internal elements
    LG = 24            # related elements
    XL = 32            # block ↔ sub-block
    XXL = 48
    BLOCK = 64         # between main blocks / outer margin / safe area
    XXXL = 96
    HUGE = 128


# ---------------------------------------------------------------------------
# Grid & canvases
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Canvas:
    name: str
    width: int
    height: int
    safe_margin: int
    columns: int = 12
    gutter: int = 24


class Canvases:
    POST_SQUARE = Canvas("post_square", 1080, 1080, 64)
    POST_PORTRAIT = Canvas("post_portrait", 1080, 1350, 64)   # primary format
    STORY = Canvas("story", 1080, 1920, 64)
    HORIZONTAL = Canvas("horizontal", 1920, 1080, 80)


# ---------------------------------------------------------------------------
# Radius, border, lines — sharp-first, no shadows
# ---------------------------------------------------------------------------

class Radius:
    NONE = 0      # editorial / data (default)
    SM = 4        # controls
    MD = 8        # cards
    LG = 12       # highlighted


class Border:
    HAIRLINE = 1


class Line:
    HEAVY = 4     # primary rule
    MEDIUM = 2    # icon stroke, secondary rule
    THIN = 1      # auxiliary


# NO shadows in this identity — depth comes from surface elevation
# (BLACK vs INK), contrast and borders. There is deliberately no Shadow class.


# ---------------------------------------------------------------------------
# Background system — eight official backgrounds
# ---------------------------------------------------------------------------

class Background:
    BLACK_CLEAN = "black_clean"
    BLACK_RED_ACCENT = "black_red_accent"
    BLACK_STRUCTURAL = "black_structural"
    BLACK_COURT = "black_court"
    TACTICAL_DARK = "tactical_dark"
    WHITE_EDITORIAL = "white_editorial"
    LIGHT_GREY_EDITORIAL = "light_grey_editorial"
    STATISTICS_DARK = "statistics_dark"

    # The base surface color for each background (accents/structure drawn on top
    # by the renderer). Kept as data so templates pick a background by name.
    BASE: Dict[str, str] = {
        BLACK_CLEAN: Color.BLACK,
        BLACK_RED_ACCENT: Color.BLACK,
        BLACK_STRUCTURAL: Color.BLACK,
        BLACK_COURT: Color.BLACK,
        TACTICAL_DARK: Color.BLACK,
        WHITE_EDITORIAL: Color.WHITE,
        LIGHT_GREY_EDITORIAL: Color.LIGHT_GREY,
        STATISTICS_DARK: Color.BLACK,
    }

    @classmethod
    def is_dark(cls, name: str) -> bool:
        return cls.BASE.get(name, Color.BLACK) in (Color.BLACK, Color.INK)

    @classmethod
    def text_on(cls, name: str) -> str:
        """Primary text color for content placed on this background."""
        return Color.WHITE if cls.is_dark(name) else Color.BLACK

    @classmethod
    def secondary_on(cls, name: str) -> str:
        return Color.GREY


# ---------------------------------------------------------------------------
# Icon system — outline, 2px stroke, 24-grid
# ---------------------------------------------------------------------------

class IconStyle:
    STROKE_WIDTH = Line.MEDIUM   # 2px
    GRID = 24
    FILL = "none"
    LINECAP = "round"
    LINEJOIN = "round"


class IconState:
    DEFAULT = Color.INK
    ACTIVE = Color.RED
    INACTIVE = Color.GREY
    ON_DARK = Color.WHITE
    DISABLED = Color.LIGHT_GREY


# A minimal set of official outline glyphs (24x24 viewBox, stroke-based).
# Stat labels are set as text (PTS/REB/AST…) per the boards, so the graphic
# icon set stays small; more glyphs slot in with the same style.
class Icons:
    # Basketball: circle + seams (used as the scoreboard center mark / footer).
    BALL = (
        "M12 3a9 9 0 100 18 9 9 0 000-18z "
        "M3 12h18 M12 3v18 "
        "M5.6 5.6c3.2 2.2 3.2 10.6 0 12.8 "
        "M18.4 5.6c-3.2 2.2-3.2 10.6 0 12.8"
    )
    STAR = "M12 4l2.2 5.3 5.8.5-4.4 3.8 1.3 5.6L12 16.9 7.1 19.8l1.3-5.6L4 10.4l5.8-.5L12 4z"
    ARROW_UP = "M12 5v14 M6 11l6-6 6 6"
    ARROW_DOWN = "M12 19V5 M6 13l6 6 6-6"
    TROPHY = "M7 4h10v3a5 5 0 01-10 0V4z M9 13h6 M12 13v4 M9 20h6"


# ---------------------------------------------------------------------------
# Token export (for documentation / tooling)
# ---------------------------------------------------------------------------

def tokens_dict() -> Dict[str, object]:
    def _members(cls):
        return {k: v for k, v in vars(cls).items() if not k.startswith("_") and not callable(v)}

    return {
        "version": DESIGN_SYSTEM_VERSION,
        "brand": _members(Brand),
        "color": _members(Color),
        "font_weight": _members(FontWeight),
        "font_size": _members(FontSize),
        "letter_spacing": _members(LetterSpacing),
        "line_height": _members(LineHeight),
        "spacing": _members(Spacing),
        "radius": _members(Radius),
        "line": _members(Line),
    }
