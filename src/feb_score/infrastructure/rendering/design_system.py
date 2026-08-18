"""Content Design System v1 — brand tokens for the 2aFEB SCORE editorial layer.

Every visual decision in templates MUST reference a constant from this module.
Templates never hardcode a color, a font-size or a spacing value — the token
IS the contract. Bumping v1 -> v2 changes the tokens; templates re-render with
the new look automatically.

Brand: 2aFEB SCORE (editorial). Separate visual identity from the technical
platform name but shares the same wordmark. The editorial voice is deportivo,
moderno, editorial — bold numbers, clean grid, mobile-first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


DESIGN_SYSTEM_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Color tokens
# ---------------------------------------------------------------------------
# Palette philosophy: near-black bases (never pure #000 — hurts on OLED),
# cool neutral greys for hierarchy, a single accent (electric blue) for CTAs
# and stat highlights, and a "success" green kept for future trend indicators.

class Color:
    # Backgrounds
    BG_DEEP = "#0b0d13"
    BG_SURFACE = "#141821"
    BG_ELEVATED = "#1a1f2b"
    BG_SUNKEN = "#0f1219"

    # Text
    TEXT_PRIMARY = "#f8fafc"
    TEXT_SECONDARY = "#cbd5e1"
    TEXT_MUTED = "#94a3b8"
    TEXT_DISABLED = "#475569"

    # Accents
    ACCENT = "#3b82f6"
    ACCENT_ON = "#ffffff"
    ACCENT_DIM = "#1e3a8a"

    # Semantic
    SUCCESS = "#10b981"
    WARNING = "#f59e0b"
    DANGER = "#ef4444"

    # Divider
    BORDER = "#334155"
    BORDER_SUBTLE = "#1e293b"


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
# Primary: Inter — best-in-class UI sans, wide weight range, tabular numerals.
# Mono: JetBrains Mono — used ONLY for scores and stat numerals.
# One family for prose, one for numerals. Zero drift.

class Font:
    PRIMARY = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    MONO = "'JetBrains Mono', 'SF Mono', Menlo, monospace"


class FontSize:
    DISPLAY = 96      # hero titles (round recap headline)
    H1 = 78           # match / player headlines
    H2 = 56           # section titles
    H3 = 42           # team names, big card titles
    H4 = 32           # stat values
    BODY_LG = 26      # subheadlines
    BODY = 22         # labels, body text
    BODY_SM = 20      # secondary labels
    CAPTION = 18      # metadata
    MICRO = 16        # tiny caps labels
    NANO = 14         # footer legalese


class FontWeight:
    REGULAR = 400
    MEDIUM = 500
    SEMIBOLD = 600
    BOLD = 700
    EXTRABOLD = 800
    BLACK = 900


class LetterSpacing:
    TIGHT_DISPLAY = -2
    TIGHT = -0.5
    NORMAL = 0
    LABEL = 2         # uppercase micro labels
    CAPS = 3          # eyebrow labels
    HERO_CAPS = 4     # top-of-canvas mini-headers


# ---------------------------------------------------------------------------
# Spacing scale (8pt grid)
# ---------------------------------------------------------------------------

class Spacing:
    XS = 8
    SM = 16
    MD = 24
    LG = 32
    XL = 48
    XXL = 64
    XXXL = 96


# ---------------------------------------------------------------------------
# Grid — canvas dimensions and safe areas
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Canvas:
    """A named canvas format with its safe area."""

    name: str
    width: int
    height: int
    safe_margin: int

    @property
    def aspect(self) -> str:
        from math import gcd
        g = gcd(self.width, self.height)
        return f"{self.width // g}:{self.height // g}"


class Canvases:
    IG_POST = Canvas(name="ig_post", width=1080, height=1080, safe_margin=60)
    IG_PORTRAIT = Canvas(name="ig_portrait", width=1080, height=1350, safe_margin=60)
    IG_STORY = Canvas(name="ig_story", width=1080, height=1920, safe_margin=80)


# ---------------------------------------------------------------------------
# Radii, borders, shadows
# ---------------------------------------------------------------------------

class Radius:
    SM = 8
    MD = 12
    LG = 16
    XL = 24
    PILL = 999


class Border:
    HAIRLINE = 1
    STANDARD = 2
    HEAVY = 4


# ---------------------------------------------------------------------------
# Iconography — SVG paths (inline, dep-free)
# ---------------------------------------------------------------------------
# Every stat/metric has ONE canonical glyph. Templates reference by key
# (`Icons.POINTS`) so a v1 -> v2 icon refresh is centralized.

class Icons:
    # 24x24 viewBox, path definitions only. Stroke or fill applied by template.
    POINTS = "M12 2l2.6 6.3 6.9.6-5.2 4.5 1.6 6.6L12 16.8 6.1 20l1.6-6.6L2.5 8.9l6.9-.6L12 2z"
    REBOUNDS = "M12 2a10 10 0 100 20 10 10 0 000-20zm0 3a7 7 0 016.7 5H14V7.3A7 7 0 0112 5zm-2 0v5H5.3A7 7 0 0110 5zm-4.7 7H10v5.7A7 7 0 015.3 12zM14 17.7V12h4.7A7 7 0 0114 17.7z"
    ASSISTS = "M8 7a3 3 0 116 0 3 3 0 01-6 0zm-4 13a5 5 0 0110 0v1H4v-1zm14-3l-3-3v2h-4v2h4v2l3-3z"
    STEALS = "M3 12l4-4v3h7V8l4 4-4 4v-3H7v3l-4-4z"
    BLOCKS = "M12 3l9 4v6c0 5-3.7 9.4-9 10-5.3-.6-9-5-9-10V7l9-4z"
    MINUTES = "M12 2a10 10 0 100 20 10 10 0 000-20zm1 5v6l4 2-1 2-5-3V7h2z"
    WINS = "M20 6l-11 11-5-5 1.4-1.4L9 14.2 18.6 4.6 20 6z"
    LOSSES = "M18 6L6 18M6 6l12 12"
    FIRE = "M12 2c1 3 4 4 4 8a4 4 0 01-8 0c0-1 .5-2 1-3-1 1-2 2-2 4a5 5 0 0010 0c0-4-3-6-5-9z"
    TROPHY = "M6 4h12v2a4 4 0 01-4 4v2h2v2h-2v2h4v2H8v-2h4v-2h-2v-2h2v-2A4 4 0 016 6V4z"
    RANK_UP = "M12 4l7 8h-4v8h-6v-8H5l7-8z"
    RANK_DOWN = "M12 20l-7-8h4V4h6v8h4l-7 8z"
    STAR = "M12 2l2.6 6.3 6.9.6-5.2 4.5 1.6 6.6L12 16.8 6.1 20l1.6-6.6L2.5 8.9l6.9-.6L12 2z"


# ---------------------------------------------------------------------------
# Image system — Level A / B / C
# ---------------------------------------------------------------------------
# Level A: official photo (player, team logo, venue) — when licensed.
# Level B: contextual (court, ball, arena, texture) — when no photo.
# Level C: statistical design (numbers, geometry, team color, iconography) —
#         always available; the fallback that keeps the layout professional
#         even without any image.
#
# v1 delivers Level C ONLY. AssetProvider interface is ready for A/B later.

class ImageLevel:
    OFFICIAL = "A"
    CONTEXTUAL = "B"
    STATISTICAL = "C"


# ---------------------------------------------------------------------------
# Template variables exposed to SVG substitution
# ---------------------------------------------------------------------------
# Convenience dict so any template can render ${design.color.accent} etc.
# The SvgTemplateRenderer walks nested dicts — so `design.color.ACCENT`
# resolves to Color.ACCENT.

def tokens_dict() -> Dict[str, Dict[str, object]]:
    return {
        "version": DESIGN_SYSTEM_VERSION,
        "color": {k: v for k, v in vars(Color).items() if not k.startswith("_")},
        "font": {k: v for k, v in vars(Font).items() if not k.startswith("_")},
        "font_size": {k: v for k, v in vars(FontSize).items() if not k.startswith("_")},
        "font_weight": {k: v for k, v in vars(FontWeight).items() if not k.startswith("_")},
        "spacing": {k: v for k, v in vars(Spacing).items() if not k.startswith("_")},
        "radius": {k: v for k, v in vars(Radius).items() if not k.startswith("_")},
        "border": {k: v for k, v in vars(Border).items() if not k.startswith("_")},
        "letter_spacing": {
            k: v for k, v in vars(LetterSpacing).items() if not k.startswith("_")
        },
    }
