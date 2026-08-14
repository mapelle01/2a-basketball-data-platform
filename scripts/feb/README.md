# FEB Source Connector (FASE 21.B2)

Real fetch from the FEB source -> normalize -> `POST /v1/commands/create_or_update_match`.

## Architecture (unchanged domain/contracts)

```
FEB source (intrafeb.feb.es BoxScore JSON)
  -> scripts/feb/ingest_match.py :fetch_feb_boxscore / parse_boxscore / to_command
  -> POST /v1/commands/create_or_update_match (existing command; idempotent via command_id UUIDv5)
```

The connector is standalone (scripts/). It does NOT modify the API image, domain,
contracts, handlers, migrations, staging, or production. Production POST only happens
with a real `FEB_API_KEY`.

## Real FEB source

- URL: `https://intrafeb.feb.es/LiveStats.API/api/v1/BoxScore/{match_id}`
- Auth: `Authorization: Bearer <FEB_TOKEN>`
- `FEB_TOKEN` lives in env (never in Git, never printed, never in logs/exceptions/URLs).
- Public match page: `https://baloncestoenvivo.feb.es/partito/{match_id}` (uses the token
  embedded in `_ctl0_token` to load the BoxScore).

## Env vars

| Var | Purpose | Required for |
|---|---|---|
| `FEB_TOKEN` | Bearer token for the FEB intrafeb API | real fetch |
| `FEB_MATCH_ID` | FEB match id | real fetch (or pass `--match-id`) |
| `FEB_SEASON_CODE` | e.g. `2025-2026` (explicit; no heuristic) | all |
| `FEB_COMPETITION_ID` | domain logical competition id, default `segunda-feb` (FEB `CompID` is preserved in `source`, not used to override domain id) | all |
| `FEB_BOX_SCORE_BASE_URL` | override API base (for tests/local) | real fetch |
| `FEB_API_KEY` | 64-hex production API key (Bearer sent to YOUR API) | POST to API |
| `FEB_TARGET_API` | base URL of your API | POST to API |

## Usage

### Offline (fixture + dry-run) — NEVER hits FEB or your API

```bash
FEB_SEASON_CODE=2025-2026 FEB_MATCH_ID=2486864 \
python3 scripts/feb/ingest_match.py \
  --fixture tests/ingestion/fixtures/boxscore_2486864.json \
  --dry-run
```

Does NOT require `FEB_TOKEN`, `FEB_SOURCE_URL`, or `FEB_API_KEY`. Prints only safe facts:
`external_id`, teams, scores, quarters, scheduled_at, command_id, `DRY_RUN`.

### Real fetch + submit to API (PRODUCTION POST; use with care)

```bash
export FEB_TOKEN='<feb bearer token>'            # from FEB intra app; never printed
export FEB_API_KEY='<64-hex production api key>'  # your API key; never printed
export FEB_SEASON_CODE='2025-2026'
export FEB_TARGET_API='https://feb-score-api-production.up.railway.app'
python3 scripts/feb/ingest_match.py --match-id 2486864
```

`--dry-run` can be combined to preview the normalized command without POSTing.

## Mapping (real fixture)

- `HEADER.CompID` -> `source`-preserved `comp_id` (NOT the domain `competition_id`).
- `HEADER.competition` -> human label ("SEGUNDA FEB").
- `HEADER.starttime` ("dd-mm-yyyy - HH:MM") -> ISO-8601 `scheduled_at` with **B2-provisional
  TZ offset `+01:00`** (FEB does not publish TZ; correct generalization is FASE 21.B3).
- `HEADER.TEAM[0|1]` -> home/away (`id` -> `external_id`, `name`, `teamCode`, `clubCode`).
  Home/away order follows FEB's `HEADER.TEAM` order.
- `HEADER.TEAM[].pts` -> final score (authoritative).
- `HEADER.QUARTERS.QUARTER` -> per-period partials.
- `BOXSCORE.TEAM[].PLAYER[]` -> player stats (`id`, `name`, `no`, `min`, `pts`, `reb`,
  `assist`, `val`, `to`, `bs`, `st`, `pf`, `p1m/a/p`, `p2m/a/p`, `p3m/a/p`, `fgm/a/p`).
- `external_id` = FEB `match_id` (real), e.g. `2486864`.

### Contract constraint (B2)

The schema `contracts/commands/create_or_update_match.v1.json` allows `raw` with only
`boxscore_ref` / `teamstats_ref` (additionalProperties: false). Therefore **full BoxScore
and player stats are NOT embedded** in the command (would break schema). Player stats are
parsed/normalized and are documented as FASE 21.B3 persistence (e.g. a `match_stats` table /
`raw_boxscore` blob). For B2 the command carries deterministic refs for traceability.

## Manual smoke (NOT in CI)

```bash
FEB_TOKEN='<feb token>' python3 scripts/feb/smoke_fetch_feb.py --match-id 2486864 \
  --out /tmp/boxscore_2486864.json
```

Validates HTTP 200 + HEADER/BOXSCORE present; writes raw JSON (FEB public content, no secrets)
to `--out`. Never prints the token.

## Idempotency

`command_id = UUIDv5(season_code|competition_id|external_id)` -> re-running the same match+
season+competition produces the SAME command_id; the API/server-side dedup (command_id in
outbox + domain) makes the ingestion idempotent. Changing `external_id` yields a different
command_id.

## Security

- Never print `FEB_TOKEN` or `FEB_API_KEY`.
- `smoke_fetch_feb.py` rejects malformed tokens (`=`, `Bearer ` prefix, newlines).
- No secrets in Git (gitignore / env only).
