# FEB SCORE! — Design System v2.0

The visual identity, consolidated from the ten official system boards into code
tokens in [`design_system.py`](../../src/feb_score/infrastructure/rendering/design_system.py).
Every component and template reads tokens from there — nothing hardcodes a hex,
a font size, or a spacing value.

> **Identity:** SPORTS DATA + EDITORIAL + PREMIUM + MODERN + DIGITAL.
> Black/white = base · greys = structure · red = accent (≈60/25/15).
> **ONE TYPEFACE. NO extra colors. NO gradients. NO shadows. CONTENT FIRST — BRAND SECOND.**

## Source of truth

The ten `*_system.png` boards under `~/Desktop/sistemas` (color, typography,
logo, grid, shapes, photography, background, icon, component, template). The
older `mini-grid` draft (brand "2FEB SCORE!") is **superseded** — the brand is
**FEB SCORE!**.

## Color

Six official colors, with semantic roles. Red is an accent that guides
attention (winner, status, key stat) — never a dominant surface, never decoration.

| Token / role | Hex | Use |
|---|---|---|
| `BLACK` / PRIMARY | `#000000` | Main backgrounds, max contrast |
| `INK` / STRUCTURAL | `#111111` | Panels, cards, structure |
| `GREY` / SECONDARY | `#6B6B6B` | Secondary text, metadata, dividers |
| `LIGHT_GREY` / SURFACE | `#E5E5E5` | Editorial surfaces, inactive |
| `RED` / ACCENT | `#E10600` | **Accent only** — winner, status, key highlight |
| `WHITE` / CONTRAST | `#FFFFFF` | Text on dark, contrast |

Forbidden: any other color, gradients, colored shadows, alternate reds.
A test (`TestIdentityRestraint`) fails the build if a template emits a
non-palette color.

## Typography

**Inter, five weights. Numbers first** (scores/stats always Inter 900).

| Role | Weight | Use |
|---|---|---|
| HERO | 900 | Numbers, scores, hero figures |
| DISPLAY | 800 | Main headlines |
| TITLE | 700 | Secondary titles |
| LABEL | 600 | Labels, categories, metadata |
| BODY | 400 | Body, descriptions |

Sizes (1080×1350): HERO 168 · DISPLAY 120 · H1 88 · H2 56 · H3 34 · BODY 24 ·
LABEL 22 · MICRO 18. Tracking: negative on hero numbers, positive on labels.
Line-height: 90–100% hero, 100–115% headline, 140–150% body. Labels uppercase,
titles sentence case. Left-align first.

The wordmark "FEB SCORE!" is set oblique (italic); everything else is upright.

## Spacing (8px base, 4/12 micro half-steps)

`MICRO 4` · `XS 8` (number↔label) · `SM 12` (icon↔text) · `MD 16` (internal) ·
`LG 24` (related) · `XL 32` (block↔sub-block) · `XXL 48` · `BLOCK 64` (main
blocks / outer margin / safe area) · `XXXL 96` · `HUGE 128`.

## Grid & canvases

12 columns, gutter 24px. **Outer margin / safe area 64px** (80px on 16:9).

| Canvas | Size | Margin |
|---|---|---|
| `POST_PORTRAIT` | 1080×1350 | 64 · **primary** |
| `POST_SQUARE` | 1080×1080 | 64 |
| `STORY` | 1080×1920 | 64 |
| `HORIZONTAL` | 1920×1080 | 80 |

## Shapes, lines, radius, borders

Corners **sharp** by default (radius 0 for editorial/data; 4 controls, 8 cards,
12 highlighted). Lines 4/2/1px. Border hairline 1px. **No shadows** — depth
comes from surface elevation (BLACK vs INK), contrast and borders.

Red accent shapes: the accent bar (the one licensed use of red as a shape),
plus vertical/corner/diagonal accents.

## Icons

**Outline, 2px stroke, round caps, 24-grid, no fill.** States: default (ink),
active (red), inactive (grey), on-dark (white), disabled (light grey). Stat
labels (PTS/REB/AST…) are set as text per the boards, so the graphic glyph set
stays minimal.

## Backgrounds (eight official)

`black_clean` · `black_red_accent` (solid red diagonal, no gradient) ·
`black_structural` · `black_court` · `tactical_dark` · `white_editorial` ·
`light_grey_editorial` · `statistics_dark`. **ONE BACKGROUND SYSTEM, NOT ONE PER
POST.** `Background.text_on(name)` / `is_dark(name)` pick legible text.

## What NOT to do

- No hex/size/space hardcoded in a component — reference a token.
- No second typeface; Inter only, five weights.
- No color outside the six; no gradients; no shadows.
- No per-team colors — teams read by initials in white/grey; red marks the winner.
- No element closer to the edge than the 64px safe margin.

## Versioning

`DESIGN_SYSTEM_VERSION = "2.0"` (the black/white/red identity; v1.0 was the
earlier dark-blue draft, now removed). A content item records the version it was
rendered with, so historical posts stay reproducible.
