# FASE 21.B1 — FEB SOURCE CONNECTOR

## Status

**PASS (offline-ready) / INGESTA REAL — PENDING FEB real source credential or public URL**

Se entregó el conector FEB-source (read-only fetch -> normalize -> submit
`create_or_update_match`), idempotent, sin secrets en Git, sin tocar dominio/staging/prod.
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

## Conclusión parcial

El conector FEB-source está entregado, testeado offline, idempotent, sin secrets en Git, sin tocar dominio/staging/prod, listo para la primera ingesta real en cuanto se provea una FEF_SOURCE_URL real.
