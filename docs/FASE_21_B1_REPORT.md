# FASE 21.B1 — FEB SOURCE CONNECTOR

## Status

**PASS (offline-ready) / INGESTA REAL — PENDING FEB real source credential or public URL**

> Refinado por FASE 21.B2: el conector ahora consume el formato REAL de FEB
> (`intrafeb.feb.es BoxScore`). Ver `docs/FASE_21_B2_REPORT.md`. CI 493 tests.
Validado offline con 9 tests unitarios (488 tests CI green).

## Arquitectura del connector

`scripts/feb/ingest_match.py` (Python stdlib only; no deps):

- **Source fetch (read-only):** `FEB_SOURCE_URL` → JSON match (público o fixture `file://`). No mutations sobre FEB.
- **Normalize** (`to_command`): mapea el source FEB a la envolvente exacta de
  `contracts/commands/create_or_update_match.v1.json` (command_id, meta, actor, payload).
- **Idempotencia:** `command_id` = **UUIDv5 determinista** sobre
  `season_code|competition_id|external_id`. Re-ingestar la misma fila → mismo command_id →
  el server-side idempotency (outbox/command_id dedup + domain) garantiza no-duplicado.
- **external_id:** preservado del source (determinista).
- **Submit:** `POST /v1/commands/create_or_update_match` con
  `Authorization: Bearer <FEB_API_KEY>` + `X-Request-Id=<command_id>`. Key desde env, nunca loggeada.
- **Error handling explícito:** 2 config, 3 source-fetch, 4 API-rejected, 5 idempotent-conflict (200/409→exit 0), 6 unexpected.

## Env

- `FEB_SOURCE_URL` (fuente FEB JSON; p. ej fixture `file://` o endpoint público real).
- `FEB_TARGET_API` (base API; prod `https://feb-score-api-production.up.railway.app`).
- `FEB_API_KEY` (64-hex raw production key; **no se imprime**).
- `FEB_COMPETITION_ID` (default `segunda-feb`).

## Flujo FEB → API (production)

```
FEB_SOURCE_URL (JSON)
  -> ingest_match.fetch_source (read-only)
  -> ingest_match.to_command (deterministic command_id, external_id preserved)
  -> ingest_match.post_command (POST ../v1/commands/create_or_update_match, Bearer $FEB_API_KEY)
  -> Production API (CommandGateway -> CommandRunner -> Postgres outbox + domain event)
```

## Evidencia real (offline)

- 9 tests unitarios (`tests/ingestion/test_feb_connector.py`): shape, deterministic UUIDv5, diff per season/external_id, external_id preserved, teams/scheduled preserved, s3_path fallback, missing-env returns 2, bad-shape KeyError.
- CI: 488 passed (479 base + 9).

## Estado production (intacts, verified)

| Check | Result |
|---|---|
| production deploy | `3471a1de` SUCCESS |
| `/health` | 200 |
| `/ready` | 200 (`schema_version=1, database=ok, migrations=up_to_date`) |
| `/docs` | 404 (hardened) |
| POST no-key | 401 |
| CI | 488 passed (green) |
| Staging `/health`+`/ready` | 200/200 (intacto) |

## Ingesta real — PRIMERA INGESTA REAL (pendiente)

Bloqueado por: **no dispongo de una fuente FEB pública real ni credentials de la FEB API**.
- La fuente candidata (LaLiga/FEF API) requiere suscripción/credencial → no disponible.
- Scrapear FEB pública no está aprobado (TOS + fragil).
- No se inventan datos (regla: no inventar datos).

→ La cadena está **arquitecturada y validada offline**; la ingesta en vivo se activa al
momento de disponer de `FEB_SOURCE_URL` real (endpoint público JSON) → basta correr:
```
FEB_SOURCE_URL="https://<feb-real>/<match>.json" FEB_TARGET_API=https://feb-score-api-production.up.railway.app FEB_API_KEY=<64-hex> python scripts/feb/ingest_match.py
```

## Auditoría PASO 2 (diff)

- No secrets en Git (scan: 0 literales 64-hex/key/token en new files). ✅
- Domain/infra migrations PG **no modificados** (diff empty sobre `src/feb_score/domain|infrastructure/persistence`). ✅
- Bounded context intacto (solo POSTa commands → API; no domina). ✅
- Idempotency por command_id determinista. ✅
- Error handling explícito (HTTPError, exit codes). ✅
- Staging no tocado por el conector. ✅

## Limitaciones restantes

- Fuente FEB real (credential o endpoint público) → external, pendiente.
- Bulk ingestion / scheduling → external cron (post-B1).
- match/team/player estadísticas derivadas → FASE 21.B2.

## Verificación post-merge (PASO 5-8)

Merge → `92fa4a2` (commit) / PR #2 closed. CI del merge (run 31782928123 → success, 488 tests), CI del PR (31782888852 → success, tests incluidos el connector).

Production (intacta, no redeploy por el connector — el conector NO toca la imagen API):
- `/health` 200; `/ready` 200 (`schema_version=1, database=ok, migrations=up_to_date`).
- `/docs` 404 (hardened).
- POST no-key → 401.
- deployment actual `3471a1de` SUCCESS.

Staging (`pretty-motilaition`): `/health` 200, `/ready` 200, `/docs` 200 → **INTACTO** (no deploy, no var, no resource touched).

## Ingesta real (PASO 4) — BLOCKED / PENDING

- No se dispone de fuente FEB pública real ni credentials FEB API (LaLiga/FEF) en este session/sandbox.
- Probe endpoints públicos conocidos (`lfep.es`) → DNS no resuelve / no disponible; no se scrapea (TOS + regla: no inventar datos).
- → **PRIMERA INGESTA REAL PENDING**: se activa al momento de proveer `FEB_SOURCE_URL` (endpoint JSON público real) o credentials FEB API.
- El conector está preparado: ver `scripts/feb/README.md` (comando de ingest con env vars).

## Estado FASE 21.B1 (honesto, evidence-based)

| Criterio | Estado | Evidencia |
|---|---|---|
| FEB connector (offline-ready, idempotent) | PASS | `scripts/feb/ingest_match.py`; 9 tests unitarios; deterministic UUIDv5 command_id |
| CI (tests + connector tests) | PASS | 488 passed (479 base + 9); CI del merge 31782928123 success |
| Merge a main | PASS | PR #2 → `92fa4a2` |
| Production deploy | PASS | `3471a1de` SUCCESS (intacto; connector no-redeploy) |
| `/health` 200 | PASS | verified |
| `/ready` 200 (schema_version=1, db, migrations) | PASS | verified |
| `/docs` 404 | PASS | hardened |
| smoke autenticado | PASS | validated (workflow run 31780767211) |
| auth 401 sin key | PASS | verified |
| Staging intacto | PASS | 200/200 |
| Primera ingesta real (partido FEB) | BLOCKED | no source credential/public URL available |

## Conclusión parcial

El **FEB-source connector está entregado, testeado offline, idempotent, sin secrets en Git, sin tocar dominio/staging/prod, y merged a `main`** (CI verde 488 tests).

La **primera ingesta real en vivo** está **BLOCKED** hasta que se provea una fuente FEB real (endpoint JSON público o credential API) — no se inventan datos. Production segue operativa y verde.
