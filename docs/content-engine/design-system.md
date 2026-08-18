# 2aFEB SCORE — Content Design System v1

Design tokens for the editorial layer. Every template consumes tokens from
[`design_system.py`](../../src/feb_score/infrastructure/rendering/design_system.py) — never hardcodes values.

## Brand decision

**Editorial brand:** `2aFEB SCORE` (same wordmark as the technical platform).
**Rationale:** the audience discovers the content before the data platform, so name continuity earns brand equity for both. Kept independent from Futbolea (that project is football, unrelated).

The visual identity is separate from the platform's operational identity — a v2 rebrand affects only templates, never the API.

## Color

| Token | Hex | Use |
|---|---|---|
| `BG_DEEP` | `#0b0d13` | Canvas background |
| `BG_SURFACE` | `#141821` | Cards |
| `BG_ELEVATED` | `#1a1f2b` | Elevated cards / stat blocks |
| `BG_SUNKEN` | `#0f1219` | Inset areas (avatar placeholders) |
| `TEXT_PRIMARY` | `#f8fafc` | Headlines, big numbers |
| `TEXT_SECONDARY` | `#cbd5e1` | Section labels |
| `TEXT_MUTED` | `#94a3b8` | Metadata |
| `TEXT_DISABLED` | `#475569` | Ranks/placeholders |
| `ACCENT` | `#3b82f6` | Score highlights, single accent |
| `ACCENT_ON` | `#ffffff` | Text on accent |
| `SUCCESS` | `#10b981` | Positive trend (future) |
| `WARNING` | `#f59e0b` | Neutral trend (future) |
| `DANGER` | `#ef4444` | Negative trend (future) |

**Rule:** exactly ONE accent per canvas. If everything is highlighted, nothing is.
Near-black never `#000` (bad on OLED) — always the deep-navy `BG_DEEP`.

## Typography

Two families only.

- **Inter** — everything textual (headlines, labels, prose).
- **JetBrains Mono** — scores and stat numerals ONLY. Tabular by default, aligns cleanly.

### Scale

| Token | px | Use |
|---|---|---|
| `DISPLAY` | 96 | Round recap hero |
| `H1` | 78 | Match / player headline |
| `H2` | 56 | Section titles |
| `H3` | 42 | Team names, card titles |
| `H4` | 32 | Stat values |
| `BODY_LG` | 26 | Subheadlines |
| `BODY` | 22 | Body / labels |
| `BODY_SM` | 20 | Secondary labels |
| `CAPTION` | 18 | Metadata |
| `MICRO` | 16 | Uppercase micro-labels |
| `NANO` | 14 | Footer legalese |

Weight scale is Inter's native 400/500/600/700/800/900.
Letter-spacing: display copy tightens (`-2` / `-0.5`), uppercase labels open up (`2` / `3` / `4`).

## Spacing (8-pt grid)

`XS 8`, `SM 16`, `MD 24`, `LG 32`, `XL 48`, `XXL 64`, `XXXL 96`.
Every gap, padding and margin is one of these — no arbitrary values.

## Grid & canvases

Three named canvases (add later if needed):

| Canvas | Size | Safe margin |
|---|---|---|
| `IG_POST` | 1080×1080 | 60 |
| `IG_PORTRAIT` | 1080×1350 | 60 |
| `IG_STORY` | 1080×1920 | 80 |

**v1 uses only `IG_PORTRAIT`** — the 4:5 format wins in the Instagram feed and doubles as a decent thumbnail. Story format arrives in v2.

Safe area = margin on all sides. No copy, score or logo may cross it.

## Radii, borders, shadows

- `Radius.SM 8` chips · `MD 12` inline stats · `LG 16` cards · `XL 24` hero · `PILL 999` avatars.
- Borders: hairline (`1`) for subtle separators, standard (`2`) for avatar rings, heavy (`4`) for eyebrow bars.
- **No shadows in v1** — flat, editorial. Depth comes from surface elevation (`BG_SURFACE` vs `BG_ELEVATED`), not blur.

## Iconography

Single glyph per stat (points, rebounds, assists, steals, blocks, minutes, wins, losses, fire, trophy, rank up/down, star). Inline SVG paths in `Icons` (design_system.py) — dep-free, colored via CSS/fill. **No emojis, no Material Icons, no mixed sets.**

## Image system

Three levels, in fallback order:

- **Level A — Official photo** (player, team logo, venue). Used when licensed and available.
- **Level B — Contextual** (court, ball, arena, texture). Used when no A available.
- **Level C — Statistical design** (numbers, geometry, team color, iconography). Always available; keeps the layout professional even with zero imagery.

**v1 delivers Level C only.** The `AssetProvider` interface is ready for A/B — a template never knows which level filled its slot; it consumes an asset descriptor.

## What NOT to do

- Never hardcode a hex value in a template. Reference `Color.*`.
- Never introduce a third font family "just for this template".
- Never invent a spacing value. Round to the scale.
- Never use two accent colors on one canvas.
- Never place text closer to the edge than `safe_margin`.
- Never render a template if a required slot is missing (VisualValidator will reject it).

## Versioning

`DESIGN_SYSTEM_VERSION = "1.0"`. A published content object records the token version it was rendered with, so historical posts remain reproducible even after a v2 refresh.
