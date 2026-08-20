# CONTENT ENGINE v1 — FINAL REPORT

**status:** delivered · 3 templates producing real content approved by fact + visual validators from 2025-2026 fixture data · pipeline runs end-to-end · CI 802/802 green

## Design System — FEB SCORE! identity v2.0

The visual layer was migrated from the early dark-blue draft to the official
**FEB SCORE!** identity (black/white/red), consolidated from the ten system
boards. Full detail in [design-system.md](design-system.md) and the
[Component Library](component-library.md).

- **colors:** six official — `BLACK #000` · `INK #111111` · `GREY #6B6B6B` · `LIGHT_GREY #E5E5E5` · `RED #E10600` · `WHITE #FFF`. Red is accent only (≈60/25/15). **No extra colors, no gradients, no shadows** — enforced by a test.
- **typography:** **Inter only, five weights** (HERO 900 / DISPLAY 800 / TITLE 700 / LABEL 600 / BODY 400). Numbers always 900. (JetBrains Mono removed.)
- **spacing:** 8px base with 4/12 micro half-steps; safe margin **64px**.
- **grid:** POST_PORTRAIT 1080×1350 primary; square/story/horizontal canvases defined.
- **icons:** outline, 2px stroke, 24-grid (was fill-based).
- **backgrounds:** eight official (`black_clean`, `black_red_accent`, `statistics_dark`, …).

**Component Library:** the 5 priority components (`match_header`, `scoreboard`,
`player_hero`, `stat_block`, `brand_footer`) are data-driven SVG functions in
[`components.py`](../../src/feb_score/infrastructure/rendering/components.py).
Templates are now **code compositions** ([`component_templates.py`](../../src/feb_score/infrastructure/rendering/component_templates.py))
rendered by `ComponentSvgRenderer` — no more `.svg` placeholder files. The
`TemplateRenderer` interface is unchanged, so the pipeline, validators and
fact-tracing are untouched. See [component-library.md](component-library.md).

## Templates

Every template renders a StoryObject through a slot contract defined in [`templates.py`](../../src/feb_score/domain/content/templates.py) and validated by the VisualValidator.

- **MATCH_FINAL** (`match_final_v1.svg`) — scoreboard hero, home/away identity discs, margin/round/season strip. Required slots: 7. Optional: 2.
- **PLAYER_OF_ROUND** (`player_of_round_v1.svg`) — big Level-C portrait disc with team-color halo, impact badge, name/team, 3-column stat grid (PTS/REB/AST). Required slots: 9.
- **ROUND_RECAP** (`round_recap_v1.svg`) — huge round number, 4 story cards (top scorer, biggest win, closest game, matches played), summary strip. Required slots: 7.

## Insight Engine

Rules implemented (deterministic, no LLM):

- `detect_match_final(match)` — one story per finalized match.
- `detect_player_of_round(round, players)` — highest `impact_score` in the round.
- `detect_round_recap(round, matches, players)` — aggregated round highlights.
- `detect_all_for_round(...)` — convenience entry point.

Every emitted fact is tagged in `source_refs` with a URI back to the 2aFEB_SCORE data platform.

## Content Planner

Deterministic weighted-sum scoring (0..100):

- `importance` × 0.30 (per StoryType baseline)
- `novelty` × 0.15
- `statistical_strength` × 0.20 (impact_score / points / margin)
- `visual_strength` × 0.15 (single-subject > multi-subject)
- `editorial_strength` × 0.20 (narrative types weighted higher)

`plan(stories, top_n=N)` returns every story marked SELECTED or REJECTED. On the sample round: PLAYER_OF_ROUND scores 84, ROUND_RECAP 72, MATCH_FINAL 61 (blowout gets the boost via statistical_strength).

## Story Object

Schema in [`story.py`](../../src/feb_score/domain/content/story.py):

```
StoryObject {
  story_type: StoryType (21 types cataloged, 3 with template mapping)
  season_code: str
  round_number: int | None
  entities: StoryEntities { player_external_id?, team_external_id?, ... }
  facts: Dict[str, Any]              — the payload; every field traceable
  source_refs: Dict[str, str]         — URIs back to 2aFEB_SCORE
  detected_at: datetime
  status: StoryStatus (DETECTED | SELECTED | REJECTED | SUPERSEDED)
  priority: int
  identity_key: sha256[:16]           — stable dedup key
  facts_hash: sha256[:16]             — detects post-publish corrections
}
```

Identity is `hash(story_type + season + round + entities + facts_hash)` — two pipeline runs over the same data produce the same identity; the queue rejects duplicates.

## Copy Generator

Contract in [`copy.py`](../../src/feb_score/domain/content/copy.py):

```
CopyContract {
  headline: str
  subtitle: str
  caption: str
  hashtags: (str, ...)
  facts_used: (str, ...)     — every fact key referenced in the strings
  locale: "es"
  generator: "deterministic-v1"
}
```

**v1 uses deterministic Spanish template strings** — every entity name and number comes from a `facts.get(key)` call, so hallucinations are impossible by construction. An LLM plug-in can replace the generator later; it must return the same contract with `facts_used` populated so the FactValidator can verify claims.

## Asset Provider

Contract in [`interfaces.py`](../../src/feb_score/application/content/interfaces.py):

```
AssetProvider.player_photo(id) -> Asset
AssetProvider.team_logo(id) -> Asset
AssetProvider.team_color(id) -> hex string
```

`Asset` carries `{kind, level, payload, payload_type, source}` — level is A/B/C so downstream code can log provenance.

v1 implementation: `StatisticalAssetProvider` (infra) — deterministic initials + a curated 10-color palette seeded by `entity_id`. Zero external calls.

## Fact Validator

Extracts every unsigned numeric literal from the copy (headline + subtitle + caption). Every extracted number must appear in the story's facts payload (walked recursively). A number in the copy that isn't in facts is a hallucination → FAIL.

**v1 policy: NUMBERS ONLY.** Entity-name checking is deferred to v2 because the deterministic generator provably cannot invent entities. The validator will get an entity check when an LLM enters the copy path.

## Visual Validator

Checks:
- All required slots for the template are non-null in the render data.
- No `{{ placeholder }}` remains unsubstituted in the rendered SVG.
- The rendered SVG parses as valid XML.

Full-fidelity visual QA (contrast, safe area, text overflow) requires rasterization; scheduled for v2 alongside the Level A/B asset work.

## Content Queue

State machine in [`queue.py`](../../src/feb_score/domain/content/queue.py):

```
DETECTED → GENERATING → GENERATED → VALIDATING → APPROVED → SCHEDULED → PUBLISHED
                                              └→ REJECTED
                                              └→ FAILED
```

`InMemoryContentQueue.add(item)` deduplicates by `story.identity_key` — a second pipeline run over the same round is a no-op. Persistence is a repository swap when needed.

## Real examples generated

From [scripts/content/generate_examples.py](../../scripts/content/generate_examples.py) using fixture data shaped like the 2aFEB_SCORE 2025-2026 season (4 matches, 7 player lines from Jornada 12):

- **match:** [`examples/content/match_final_2025-2026_R12.svg`](../../examples/content/match_final_2025-2026_R12.svg) — Alicante Cimarrones 104-72 Melilla Baloncesto. Priority 61, fact ✓, visual ✓.
- **player:** [`examples/content/player_of_round_2025-2026_R12.svg`](../../examples/content/player_of_round_2025-2026_R12.svg) — C. Sáez (31 pts / 9 reb / 5 ast / impacto 52.8). Priority 84, fact ✓, visual ✓.
- **round:** [`examples/content/round_recap_2025-2026_R12.svg`](../../examples/content/round_recap_2025-2026_R12.svg) — 4 partidos, top scorer C. Sáez, +32 mayor diferencia, 2 pts partido más ajustado. Priority 72, fact ✓, visual ✓.

Manifest: [`examples/content/manifest.json`](../../examples/content/manifest.json) — includes copy, facts_used, source_refs and validation results for each piece.

**Regenerate at any time with:** `python scripts/content/generate_examples.py`

## Architecture

```
domain/content/                     — pure, no IO
  story.py           StoryObject + StoryType (21 cataloged)
  insights.py        Insight Engine (detectors)
  planner.py         Content Planner (scoring)
  copy.py            Copy Generator (deterministic)
  validation.py      FactValidator + VisualValidator
  queue.py           Content Queue + state machine
  templates.py       Template contracts (required slots)

application/content/                — interfaces the pipeline depends on
  interfaces.py      TemplateRenderer, AssetProvider, Asset

application/use_cases/
  round_pipeline.py  RoundPipeline (composition surface)

infrastructure/rendering/           — concrete implementations
  design_system.py   Tokens (colors, typography, spacing, canvases, icons)
  svg_renderer.py    SvgTemplateRenderer (reads .svg files, substitutes)
  asset_provider.py  StatisticalAssetProvider (Level C fallback)

templates/content/                  — the .svg templates (versioned)
docs/content-engine/                — this + design-system.md
examples/content/                   — generated reference pieces
scripts/content/                    — example generator
```

DDD boundary respected: architecture tests confirm application never imports infrastructure, infrastructure imports only domain + application interfaces + the gateway port.

## Tests

- added: **12 essential tests** in [tests/domain/test_content_engine_v1.py](../../tests/domain/test_content_engine_v1.py) covering story identity/dedup, planner scoring/ordering, fact validator (hallucination detection + score-separator edge case), copy generator fact-usage discipline, pipeline end-to-end approval and dedup.
- total: **802 passed** (759 pre-existing + 47 v0 content + 12 v1 essential — CI green including architecture-boundary and no-third-party-in-infra guards).
- deliberately skipped: exhaustive per-detector permutations, per-template rendering snapshots (change on every visual iteration; noise, not safety). Follow the brief: quality > test-marathon.

## Limitations

- **Copy is deterministic Spanish only.** An LLM generator plug-in is the intended v2 upgrade (entity check re-enabled at that point).
- **Assets are Level C only.** No player photos, no team logos, no venue imagery. Level A/B implementations plug into the same `AssetProvider` interface without template changes.
- **Only IG_PORTRAIT (1080×1350).** IG_POST and IG_STORY canvases documented but not yet templated.
- **Content Queue is in-memory.** Fine for per-round runs; needs a persistent repository (Postgres) before scheduling/queuing over time.
- **No publisher.** By design — the brief explicitly excludes Instagram publishing from v1. The Publisher abstraction is scaffolded conceptually; concrete `InstagramPublisher`/`WebPublisher` come after visual approval on real posts.
- **Novelty scoring is a heuristic.** Real "was this seen last round?" needs a persistent queue; v1 uses a deterministic proxy per StoryType.
- **VisualValidator is structural only.** No contrast, safe-area or overflow checks yet — requires rasterization.
- **Fixture data.** The 3 real examples use realistic-shaped fixture matches from Jornada 12 (schema matches the platform's read models). A follow-up step wires the pipeline to `MatchStatsRepository` + `ExplorationService` to consume live 2025-2026 data.

## Live data adapter (delivered)

The pipeline now runs against the real data platform, not just fixtures.

- **`LiveContentAdapter`** ([live_content_adapter.py](../../src/feb_score/application/use_cases/live_content_adapter.py)) — given `(season, round)`, reads `MatchRepository.search` (FINALIZED only) + `MatchStatsRepository` boxscore + batch-resolves team/player names from the catalog, and emits `MatchFactsInput` / `PlayerLineInput`. A missing catalog name becomes `None` (templates fall back to the external_id) — never invented.
- **Gateway methods** — `run_content_pipeline(season, round, top_n)`, `list_content_queue(status?)`, `get_content_item(id)`, `render_content_item(id)`. The pipeline (with its queue) is lazily built per gateway; templates dir from `FEB_SCORE_CONTENT_TEMPLATES_DIR` (default `templates/content`).
- **HTTP endpoints** ([content.py](../../src/feb_score/api/content.py)):
  - `POST /v1/content/pipeline/rounds/{season}/{round}?top_n=N` — authenticated; runs the pipeline, returns queued item summaries.
  - `GET /v1/content/queue?status=` — list queue, most important first.
  - `GET /v1/content/items/{id}` — item metadata (story, copy, validation).
  - `GET /v1/content/items/{id}/render.svg` — the rendered SVG (`image/svg+xml`).
- **Demo script** — `scripts/content/run_live_pipeline.py <season> <round> [top_n]` runs against the configured backend (SQLite locally, PostgreSQL when `FEB_SCORE_DATABASE_URL` is set), writing approved SVGs to `examples/content/live/`.
- **Tests:** +6 adapter (FINALIZED filter, name resolution, no-invention, DTO shaping) +9 HTTP integration (full stack through the real command/repo flow). Total now **817 passing**.

To generate real content from production: point `FEB_SCORE_DATABASE_URL` at the production DSN and run the demo script (or POST the endpoint) for a completed round.

## Robustness hardening (delivered)

The FEB feed is unstable (catalog names and boxscore rows can be missing). The engine now degrades gracefully instead of rejecting a whole piece:

- **Slot policy recalibrated** — a slot is REQUIRED only when the template cannot render without it. Display names (team/player) and a round's top scorer are OPTIONAL.
- **`display.*` namespace** — the pipeline resolves each display name to `catalog name OR external_id` (never blank, never invented — the external_id is a genuine data id). Templates consume `display.*`.
- **Copy stays honest** — the round recap omits the top-scorer clause entirely when a round has no boxscore rows (no fabricated "0 pts").
- **FactValidator** treats a numeric external_id as a real value (not a hallucination) and ignores numbers embedded in names ("76ers", "p1").
- Result: a round with no catalog and no player stats still produces approved `match_final` + `round_recap` pieces. Tests in `TestImperfectData`.

## Persistent queue (delivered)

The content queue moved from per-gateway in-memory to SQL (`content_queue` table, SQLite migration 006 + PostgreSQL migration 005):

- **Cross-run dedup** — UNIQUE `story_identity_key`; re-running a round adds nothing new.
- **Survives restart** — a new gateway over the same DB sees the full queue and can still render stored items (lossless round-trip via `ContentItem.from_dict`, SVG in its own column).
- **Audit trail** — created/updated/published timestamps, status, priority per row.
- **Novelty helper** — `seen_story_type_in_round(...)` enables real novelty scoring across runs.
- Repos: `SqliteContentQueueRepository` / `PgContentQueueRepository` implement the `ContentQueue` protocol; wired into both gateways. Tests in `tests/sqlite/test_content_queue_repo.py` + cross-restart HTTP tests.

## Expanded insights (delivered)

Detectors grew from 3 to 6 story types (all deterministic, round-data only, mapped to existing templates — visual work deferred):

- **BIGGEST_WIN** — the rout of the round (margin ≥ 20), a dedicated piece distinct from the plain match result. Reuses `match_final` with its own copy.
- **DOUBLE_DOUBLE / TRIPLE_DOUBLE** — one story per qualifying player (≥2 / ≥3 categories at 10+). Reuses `player_of_round`.
- On the sample round the pipeline now emits **8 pieces across 6 story types** from one round, all fact + visual validated, ranked by the planner (player-of-round 84, biggest-win 72, recap 72, double-double 62, match finals 61/52/49/43).

Total tests: **837 passing**.

## Content lifecycle (delivered)

The queue now runs the full publication cycle, not just up to validation:

```
DETECTED → GENERATING → GENERATED → VALIDATING ─┬→ APPROVED ─────────┐
                                                ├→ PENDING_REVIEW ───┤ (human)
                                                └→ REJECTED          │
                                     APPROVED → SCHEDULED → PUBLISHED
(any non-terminal) → FAILED
```

- **State machine** in the domain (`ContentItem`) — semantic transitions (`approve`, `reject`, `schedule`, `mark_published`, `fail`) each validate their precondition; an illegal move raises `InvalidContentTransition`, never silent corruption.
- **Review policy** ([review.py](../../src/feb_score/domain/content/review.py)) — after validation, high-impact stories (PLAYER_OF_ROUND, ROUND_RECAP, TRIPLE_DOUBLE, SEASON_HIGH, MILESTONE, UPSET, COMEBACK, or priority ≥ 80) route to **PENDING_REVIEW**; routine pieces (a plain match result) auto-**APPROVED**. One knob, tightened per season.
- **Publisher abstraction** ([interfaces.py](../../src/feb_score/application/content/interfaces.py)) + **DryRunPublisher** — the lifecycle runs end-to-end (…→ PUBLISHED) with zero external calls; the `PublishResult` records `dry_run: true`. Real Instagram/Web adapters implement the same interface without touching the lifecycle.
- **ContentLifecycleService** ([content_lifecycle.py](../../src/feb_score/application/use_cases/content_lifecycle.py)) — `approve_review` / `reject_review` / `schedule` / `publish`; validates the precondition *before* any external call so a real channel never delivers something that then fails its transition.
- **Persistence** — the SQL queue gained `update()`; transitions and the publish result survive restart (verified by cross-restart HTTP test).
- **HTTP** — `POST /v1/content/items/{id}/review/{approve,reject}`, `/schedule`, `/publish` (authenticated; illegal transition → 409).
- **Tests:** +20 (state machine, review policy, lifecycle service, HTTP flow, restart). Total **857 passing**.

On the sample round the pipeline now routes automatically: `match_final` → approved; `player_of_round` + `round_recap` → pending_review (waiting for a human).

## Season-context detectors (delivered)

Detection now reasons over the season, not just the round — the highest-value editorial stories:

- **SEASON_HIGH** — a player's new, strict, unique season-best scoring game (≥20 pts, with a real baseline of prior games). Reuses `player_of_round`.
- **WIN_STREAK / LOSS_STREAK** — a team on a 3+ consecutive win/loss run. Detected, scored, and **surfaced in the pipeline result's `pending_template`** (no team-shaped template yet — that's deferred visual work), so the insight isn't lost.
- **UPSET** — a team beats an opponent ranked 6+ places above it in the classification. Reuses `match_final`.

Architecture: a `SeasonContext` DTO ([season_insights.py](../../src/feb_score/domain/content/season_insights.py)) carries the raw season data; the detectors do the reasoning (domain-pure). `LiveContentAdapter.build_season_context` assembles it from existing read models — `list_player_stats_by_season` (history, fetched only for the round's high scorers), `list_season_team_rounds` (streaks), `list_season_team_leaderboard` classification (upsets). The pipeline runs these when a `season_context` is passed; the gateway builds and passes it automatically.

`RoundPipeline.run` now returns a `RunResult` (`items` + `pending_template`) instead of a bare list. Verified end-to-end against multi-round SQL fixtures: a player's 35-pt night correctly fires SEASON_HIGH through the real adapter. Tests: +13 (unit detectors, adapter season context). Total **870 passing**.

## Backend polish (delivered)

Three loose ends in the pipeline, tightened:

- **Dedup before render** — the pipeline now checks `queue.by_story_identity` *before* rendering, so an idempotent re-run of a round spends zero renders on stories already queued (proven by a counting-renderer test). Previously it rendered, then discarded on `add()`.
- **Honest metrics** — `RunResult.metrics` (`RunMetrics`) reports `stories_detected`, `stories_selected`, `content_generated` (newly queued only), `duplicates_skipped`, `rejected`, `pending_review`, `failed`, `pending_template`. Surfaced in the pipeline endpoint response. A re-run now correctly reports `content_generated: 0, duplicates_skipped: N` instead of miscounting duplicates as generated.
- **Real novelty scoring** — the planner's novelty dimension now consults the queue: a story type already covered for this round (`seen_story_type_in_round`, on both the SQL and in-memory queues) takes a penalty, so re-runs don't keep re-elevating existing content. The planner stays pure (it receives the seen-set as data; the pipeline builds it from the queue).

Tests: +5. Total **875 passing**.

## Next phase

In priority order:

1. **PNG rasterization** — infrastructure adapter (headless renderer OR cairo) so Instagram-ready PNGs come out. Contains no design logic; pure format conversion.
2. **Real channel Publisher** — an Instagram/Web adapter behind the existing `Publisher` interface (the abstraction + dry-run + full lifecycle are done; only the channel integration remains).
3. **Post-ingest trigger** — call `run_content_pipeline` automatically when a round completes (hook into the auto-ingest orchestrator).
4. **Templates 4–15 + LLM copy** — dedicated designs (starting with the team-streak template the streak detector is waiting on) and an LLM copy generator (same `CopyContract`, FactValidator re-enables entity checks).

## Season handling

The engine is fully season-parametrized — zero hardcoded season codes. 2025/2026 is the sandbox; moving to 2026/2027 as the live season is a parameter change, not a code change.
