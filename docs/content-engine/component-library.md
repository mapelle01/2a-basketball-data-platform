# FEB SCORE! — Component Library v1.0

Reusable, data-driven building blocks that render to SVG. Each component is a
pure function `(x, y, width, data) → (svg, height)`: it never positions itself
absolutely; it reports the height it used so a template stacks components in a
vertical flow with system spacing. Every visual decision reads a token from the
[design system](design-system.md).

```
DESIGN TOKENS  →  COMPONENTS  →  TEMPLATE COMPOSITIONS  →  AUTOMATED CONTENT
```

Code: [`components.py`](../../src/feb_score/infrastructure/rendering/components.py) ·
compositions: [`component_templates.py`](../../src/feb_score/infrastructure/rendering/component_templates.py) ·
renderer: `ComponentSvgRenderer` in [`svg_renderer.py`](../../src/feb_score/infrastructure/rendering/svg_renderer.py).

## Architecture

```
TEMPLATE (composition)
├── HEADER / METADATA      →  01 match_header
├── MAIN CONTENT           →  02 scoreboard   (match context)
│                          →  03 player_hero  (player context)
├── SECONDARY DATA         →  04 stat_block
└── BRANDING               →  05 brand_footer
```

- **Atoms** (indivisible): `text`, `rect`, `hline`/`vline`, `accent_bar`,
  `icon`, `status_pill`.
- **Frames & slots**: `corner_frame` (the signature L-bracket encuadre — pure
  monochrome chrome), `avatar` and the `player_hero` portrait (asset **slots**:
  real cutout/crest when present, monochrome initials fallback when not),
  `initials_of`.
- **Molecules** (the five components below) compose atoms.
- **Compositions** (templates) compose molecules on an official background.

## Composition engine — the layer stack

Templates are assembled by `compose(background, **layers)` in
`component_templates.py`, which paints named layers back to front in a fixed
z-order. Any layer may be empty; asset-driven layers degrade to brand chrome, so
a piece is always valid and never invents an asset it doesn't have.

```
BASE      official background (image or procedural)   ← _background
IDENTITY  team echo / crest as texture (asset slot)   [awaits crests]
PHOTO     player cutout (asset slot)                  ← avatar / player_hero
GEOMETRY  frames, court lines, brackets (chrome)      ← corner_frame …
DATA      scores, stats, ratings, ranking rows        ← components
ACCENT    the single red accent / brand footer        ← accent_bar …
```

When real crests (PNG w/ alpha) and player cutouts arrive, they fill the
IDENTITY / PHOTO slots that already exist — no template rework. Team-color
gradients are deliberately **out** of the engine (identity: no per-team colors,
no decorative gradients).

Components nest: a **player_hero** embeds a hero **stat_block**, which embeds
stat numbers. That nesting is what makes the system reusable.

## Design principles (enforced)

- **Consistency** — a scoreboard is the same component in every post.
- **Reusability** — components reused across templates.
- **Fallback safety** — a piece stays valid with no logo / no photo / no
  secondary data (tested).
- **Automation ready** — components are built from data, never hand-placed.
- **Restraint** — only the six official colors; red as accent (winner / key
  stat only). A test rejects any non-palette color.

---

## 01 — match_header

**Purpose:** identify the context (competition · round · status). Compact;
never competes with the scoreboard.

- **Inputs:** `competition`, `round_label`, `status?`, `on_dark`
- **Layout:** red eyebrow accent bar → competition·round label (grey, caps) →
  status pill (right, red when live/final).
- **Color:** grey label; red only on the eyebrow bar and a live status.
- **Fallback:** `status` omitted → no pill.

## 02 — scoreboard

**Purpose:** display a result. Number-first: score dominates, team second, red
marks the **winner only**. Works with zero logos.

- **Inputs:** `home` / `away` = `TeamSide(name, score, is_winner)`, `variant`, `on_dark`
- **Variants:** `hero` (stacked, huge numbers + ball divider) · `compact` (one
  line) · `minimal` (score only).
- **Priority:** score → team → status → secondary.
- **Color:** winner score red; loser and names white/black; center rule grey.
- **Fallback:** no logos needed; names carry identity.

## 03 — player_hero

**Purpose:** feature a player. Combines identity + an embedded hero stat_block.
Valid **without a photo**.

- **Inputs:** `name`, `team`, `primary_stat`, `primary_label`,
  `secondary_stats[]`, `initials?`, `badge?`, `on_dark`
- **Layout:** portrait slot (or initials fallback with red corner accent) →
  name (display) → team (grey caps) → embedded hero stat_block.
- **Fallback:** no photo → premium typographic composition with large initials
  (never a childish avatar); `initials` missing → "—".

## 04 — stat_block

**Purpose:** a primary stat + optional secondary stats. Priority: number →
label → secondary.

- **Inputs:** `primary`, `primary_label`, `secondary_stats[] = (value, label)`,
  `variant`, `on_dark`, `center`
- **Variants:** `hero` (huge number) · `standard` · `compact` · `inline`.
- **Color:** number white/black; primary label red (the one place red earns
  attention); secondary labels grey; column dividers ink.
- **Fallback:** `secondary_stats` empty → just the primary block.

## 05 — brand_footer

**Purpose:** close a piece, reinforce the brand — discreet, never a giant
watermark. Works on white / black / image backgrounds.

- **Inputs:** `competition?`, `season?`, `variant`
- **Variants:** `dark` (white wordmark) · `light` (black wordmark) · `compact`
  (FS! mark).
- **Layout:** small vertical red accent → oblique "FEB SCORE!" wordmark →
  metadata (right, grey caps).

---

## Templates (compositions)

`match_final` (black+red-accent bg), `player_of_round` (black clean),
`round_recap` (statistics dark). The renderer maps `template_id` → a composition
function; no template files. Adding a template = one function that stacks
components. Adding a component variant = one branch, reused everywhere.

## Rendering path (unchanged contract)

```
Story → Copy → data{story,copy,assets,display,meta}
      → ComponentSvgRenderer.render(template_id, data)
      → component_templates.render_<id>(data)
      → components.* → SVG (1080×1350)
      → Fact + Visual validation → Queue
```

The `TemplateRenderer` interface is unchanged, so the pipeline, validators,
fact-tracing (`source_refs`) and determinism are untouched. Rendering stays
swappable: a future PNG/HTML/React renderer implements the same interface.

## Tests

[`test_component_library.py`](../../tests/domain/test_component_library.py):
valid SVG, fallback safety (no logo / no photo / no secondary), the red-accent
rule (winner only), and identity restraint (only official palette colors).
