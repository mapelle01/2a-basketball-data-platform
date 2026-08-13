# FASE 18.5 — RAILWAY HEALTHCHECK RECOVERY

Fecha: 2026-08-13

## Root Cause
El servicio `feb-score` en Railway arrancaba en **SQLite**, no en PostgreSQL, y crasheaba en el boot:

- `FEB_SCORE_DATABASE_URL` **no estaba definida** (no existía servicio PostgreSQL en el proyecto).
- `FEB_SCORE_ENV` **no era `production`** (no se activó el fail-fast de configuración).
- Resultado: `_build_db()` cae al backend SQLite → `sqlite3.OperationalError: unable to open database file` → el proceso muere antes de que uvicorn escuche → Railway marca "service unavailable" en el healthcheck durante los 5 minutos (`healthcheckTimeout=300`).

NO fue un defecto del código: es el comportamiento correcto del código con configuración/infraestructura ausentes.

## Evidence (real)
- **Logs de deploy (deployment fallido `3de9461b`):** `Traceback ... sqlite3.OperationalError: unable to open database file` en `connection.py:96` (sqlite path) → `Stopping Container`.
- **Logs de build (fallido):** `Starting Healthcheck / Path: /ready / Retry window: 5m0s / Attempt #1..#11 failed with service unavailable ... 1/1 replicas never became healthy!`.
- **Variables del servicio `feb-score` (solo nombres):** solo `RAILWAY_*` del sistema; cero `FEB_SCORE_*`.
- **Servicios del proyecto:** solo `feb-score` (Failed); sin PostgreSQL.
- **Deployments:** `4f911a84`, `cebab3d2`, `3de9461b` — todos FAILED.

## Changes
Solo configuración/infraestructura en Railway. **Ningún cambio de código** (no se parcheó la aplicación para ocultar el problema).

1. **Creado servicio PostgreSQL** (plugin Railway, imagen `ghcr.io/railwayapp-templates/postgres-ssl:18` → **PostgreSQL 18**, el default actual del plugin; no 16) — service ID `3f69528d`, región `ams`, volumen propio.
   - Se eliminó el duplicado accidental `Postgres-2_Wi` creado por el prompt interactivo del CLI (`--yes`).
2. **Variables configuradas en `feb-score`** (nombres; valores nunca impresos):
   - `FEB_SCORE_DATABASE_URL=${{Postgres.DATABASE_URL}}` (referencia privada)
   - `FEB_SCORE_API_KEYS=<clave generada con openssl rand -hex 32, rol smoke:admin>` — guardada en fichero 0600 fuera del repo, nunca expuesta
   - `FEB_SCORE_ENV=production`
   - `FEB_SCORE_LOG_LEVEL=info`
   - `FEB_SCORE_RATE_LIMIT=true`
   - `FEB_SCORE_RATE_LIMIT_PER_MINUTE=120`
3. **Dominio público HTTPS** generado: `https://feb-score-production.up.railway.app`.
4. **Redeploy** del servicio `feb-score`.

## Deployment Result
- Deployment: `7dbeda3b-1efd-4da3-9a47-8dcc5d14361f` — **SUCCESS**
- `railway service status` → Service: feb-score / Deployment: `7dbeda3b` / **Status: SUCCESS**
- Logs de startup (reales):
  - `gateway_ready backend=postgresql`
  - `Application startup complete.`
  - `Uvicorn running on http://0.0.0.0:8080` (puerto `PORT` inyectado por Railway; sin `FEB_SCORE_PORT`)
  - Healthcheck de Railway: `GET /ready` → 200 (primera réplica, `100.64.0.2`)

## Healthcheck
- Build log: `[1/1] Healthcheck succeeded!` (primer intento).
- `GET /health` → HTTP 200 `{"status":"ok"}`
- `GET /ready` → HTTP 200 `{"status":"ready","checks":{"schema_version":"1","database":"ok","migrations":"up_to_date"}}`

## PostgreSQL
- Servicio: `Postgres` — **Online** (deployment `47cdf15c`, volume `postgres-volume`).
- Imagen: `postgres-ssl:18` (PostgreSQL 18; el plugin Railway ya no ofrece 16 por defecto — documentado, no ocultado).
- Conectividad real: `database=ok` + `schema_version=1` + `migrations=up_to_date` vía `/ready`.
- **Privado:** sin TCP proxy público ni dominio público para Postgres; la API se conecta por referencia interna `${{Postgres.DATABASE_URL}}`.

## Smoke Test
Ejecutado con `scripts/staging_smoke.sh` contra el dominio real con la API key de staging (valor nunca impreso):
1. `GET /health` → 200
2. `GET /ready` → 200
3. `POST /v1/commands/create_or_update_match` (external_id `smoke-1786649868`) → **HTTP 200**, `status=accepted`, evento `match_upserted` (event_id `feba8836-...`, command_id `ca9258f6-...`)
4. `GET /v1/matches/smoke-1786649868` → HTTP 200 con el match creado

Traza real en logs: `command_started → command_completed events=1 → event_published MatchUpserted → dispatch_completed delivered=1 → http_request POST 200 → GET match 200`.

## Security
- HTTPS: certificado Let's Encrypt válido para `*.up.railway.app` (notBefore 2026-07-29, notAfter 2026-10-27; `ssl_verify_result=0`), HTTP/2.
- PostgreSQL privado (sin proxy TCP, sin dominio público).
- Autenticación: POST de comando sin API key → **HTTP 401** (probado).
- Lecturas públicas correctas: match inexistente → HTTP 404.
- Secrets: `FEB_SCORE_API_KEYS`/`FEB_SCORE_DATABASE_URL` nunca impresos en logs (verificado en logs de deploy; solo figuran nombres de variables).
- Non-root: contenedor ejecutado como usuario `feb` (uid 1000) por el Dockerfile.
- `/docs` público: presente por diseño (FastAPI; no es un cambio de esta fase).

## Observability
- Logs de aplicación (`feb_score ... http_request duration_ms=... request_id=...`), de uvicorn y del dispatcher.
- `request_id` presente en TODAS las peticiones (p.ej. `88174570-...` en el POST, `316d8011-...` en el primer /ready).
- Healthcheck y readiness funcionando (liveness `/health` + readiness `/ready`).
- Restart policy `ALWAYS` en `railway.toml`; sin restarts observados (contenedor estable desde 17:01:39Z hasta el smoke ~17:37Z).

## Remaining Gaps
- **BACKUP / DR (FASE E de 18.2): NO configurado todavía.** Railway ofrece volume snapshots, PITR (pgBackRest) y `pg_dump`; ninguno activo aún. No se declara ningún backup operativo.
- **Restore drill: NO ejecutado** (pendiente tras configurar backup).
- **Rollback (FASE F): NO probado** aún (deploy actual `7dbeda3b` es la versión buena; la anterior quedó Failed).
- PostgreSQL **18** en lugar de 16 (default del plugin Railway).
- `/docs` público (decisión documentada de FASE 17).
- Rate limiter en memoria (correcto para 1 réplica; migrar a store compartido si se escala).
- `startCommand` en `railway.toml` + `ENTRYPOINT` en Dockerfile redundantes (inofensivo; limpiar si se toca).

## STAGING GATE
**PASS — STAGING DEPLOYED**

Criterios cumplidos con evidencia real (no simulada):
- [x] PostgreSQL Running (Online, privado)
- [x] API Running (SUCCESS)
- [x] Build PASS / Deploy PASS
- [x] `/health` HTTP 200
- [x] `/ready` HTTP 200
- [x] `schema_version=1`, `database=ok`, `migrations=up_to_date`
- [x] POST `create_or_update_match` HTTP 200, `status=accepted`, evento `match_upserted`
- [x] GET match HTTP 200
- [x] Logs de startup correctos (`gateway_ready backend=postgresql`, `Uvicorn running on 0.0.0.0:8080`)
- [x] Servicio estable tras el smoke

NO se declara PRODUCTION DEPLOYED ni BACKUP OPERATIONAL. Siguiente fase (18.6): configurar backup/PITR real, ejecutar restore drill y rollback con evidencia.