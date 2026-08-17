# PRODUCTION RUNBOOK — FEB-SCORE v1.0.0 (Railway)

Estado: **PRODUCTION DEPLOYED** (FASE 19). Project Railway: `feb-score-production`,
environment `production`, servicios `feb-score-api` + `Postgres`.

## 1. URLs

- API: `https://feb-score-api-production.up.railway.app`
- Health: `GET /health` (liveness)
- Readiness: `GET /ready` (comprueba `schema_version=1`, `database=ok`, `migrations=up_to_date`)
- OpenAPI: `/openapi.json` (Swagger UI: `/docs`, público por decisión de staging/prod-first; restringir en fase posterior si se exige)

## 2. Configuración mínima (1 réplica)

- 1 API réplica (build desde `Dockerfile`; `railway.toml`).
- 1 PostgreSQL privado (`postgres-ssl:18`, región ams, volumen `postgres-volume`).
- PITR continuo ON (bucket `Postgres-PITR`, ams); pgBackRest retención full=4/diff=14.
- Backup lógico offsite: `pg_dump -Fc` → bucket Railway S3-compatible `Postgres-PITR/prod-dumps/` (prefijo). NOTA: Railway plan limita buckets (3 max); el dump lógico reutiliza el bucket PITR con prefijo. Para DR verdadero external S3, ver Limitations.
- Rate limit: `FEB_SCORE_RATE_LIMIT=true`, `FEB_SCORE_RATE_LIMIT_PER_MINUTE=120` (in-memory, 1 réplica).
- restartPolicyType=ALWAYS; healthcheckPath=/ready; overlapSeconds=0; healthcheckTimeout=300.

## 3. Deploy

### CD (GitHub Actions)
- Workflow: `.github/workflows/deploy-production.yml` (propuesto/crear).
- Disparador: `workflow_dispatch` (manual) con `environment: production` de GitHub + approval (proteger rama). NO deploys automáticos desde push.
- Secrets de GitHub: `RAILWAY_TOKEN` (scoped production), `RAILWAY_SERVICE_NAME=feb-score-api`, `RAILWAY_PROD_DOMAIN`, `FEB_SCORE_PROD_SMOKE_KEY`.
- Secuencia CI: tests (477) + pip check → `railway up --service feb-score-api` → esperar `SUCCESS` → `GET /ready` 200 + `schema_version=1` → smoke autenticado → `POST` sin key 401.

### Local / manual
```
railway link --project feb-score-production
railway up --service feb-score-api -y --detach
railway service status --service feb-score-api     # esperar SUCCESS
```
Las migrations corren en boot (`server.py: db.migrate()`); con `overlapSeconds=0` nunca hay 2 migraciones simultáneas. La guarda de schema-futuro (`postgres/connection.py`) aborta el boot si el binario es más antiguo que el schema.

## 4. Rollback

- Railway conserva el histórico de deployments; rollback = redeployar una versión anterior.
- Vía CLI: `railway api 'mutation { deploymentRedeploy(id: "<deployment_id>") { id status } }'`.
- Checklist: deployment anterior → SUCCESS → `/health` 200 → `/ready` 200 (schema_version=1) → smoke autenticado → datos intactos (GET match conocido) → smoke PASS. Luego restaurar la versión production correcta.
- No afecta a la base (solo redeploy de la imagen app). Con `overlapSeconds=0`, el redeploy reemplaza sin solapamiento.
- NOTA: los datos persisten en el PostgreSQL; un rollback de app NO revierte datos. Para rollback de datos, usar restore (sección 6).

## 5. Secrets rotation

- API key: generar `openssl rand -hex 32` → formato `key=prod:admin`.
- Settear sin pasar el valor por args: `printf '%s=prod:admin\n' "$NEW" | railway variable set --service feb-score-api FEB_SCORE_API_KEYS --stdin` → triggers redeploy.
- Verificar: nueva key → smoke OK; key anterior → 401.
- Database URL: `${{Postgres.DATABASE_URL}}` (referencia interna privada; rotación del PG la gestiona Railway).
- Nunca imprimir valores; usar GitHub secret manager para FEB_SCORE_PROD_SMOKE_KEY.

## 6. Backup & restore

### PITR continuo (físico)
- Status: `railway postgres pitr status --service Postgres` (enabled / bucket wired yes).
- Restore a timestamp (para DR/recuperación puntual):
  `railway postgres pitr restore --service Postgres --at "<RFC3339>" --new-service-name <svc> -y`
  (crea una instancia hermana; validar schema_version=1, tablas, datos; borrar tras).
- RPO efectivo ~60s (WAL archive-timeout). RTO restore PITR observado ~39s (staging) / ~varía.

### pg_dump lógico offsite
- Conexión: túnel SSH `railway connect Postgres --tunnel-only --ssh -P 15433` → pg_dump 18 cliente.
- Dump: `pg_dump -h 127.0.0.1 -p 15433 -U postgres -d railway -Fc -f /tmp/.../feb_score_prod_<ts>.dump`.
- Upload offsite: `aws --endpoint-url "$AWS_ENDPOINT_URL" s3 cp <dump> s3://postgres-pitr-prod-dumps/prod-dumps/<file>` (reusar bucket PITR con prefijo, o bucket externo si existe).
- SHA-256 del dump; verificar integridad tras download.
- Retención: versionar por timestamp; purge manual o vía schedule (cuando esté disponible).

### Restore lógico drill (isla, no sobre production)
- `createdb feb_restore_test_prod` → `pg_restore -d feb_restore_test_prod --no-owner <dump>` → validar schema_version=1, 12 tablas, domain_events, match conocido → DROP DATABASE.

## 7. Incident response

- `/ready` 503 → revisar `FEB_SCORE_DATABASE_URL` (referencia), credenciales, `schema_version`. Logs: `railway logs --service feb-score-api`.
- Healthcheck falla (>300s) → confirmar que la app escucha en `${{PORT}}` y `/ready` responde 200.
- Boot falla por schema futuro → binario más antiguo que la base; volver al commit correcto (`/ready` + guarda en `postgres/connection.py`).
- Smoke 401 → `FEB_SCORE_API_KEYS` no incluye la key de smoke o rol insuficiente.
- 5xx → filtrar `request_id` en logs; revisar events/domain_events.

## 8. Health checks

- `GET /health` → 200 `{"status":"ok"}` (liveness).
- `GET /ready` → 200 `{"status":"ready","checks":{"schema_version":"1","database":"ok","migrations":"up_to_date"}}` (readiness).
- Railway healthcheck: `/ready`, timeout 300s, `restartPolicyType=ALWAYS`.

## 9. RPO / RTO

| Tipo | RPO | RTO observado |
|---|---|---|
| PITR continuo (físico) | ~60s (WAL) | ~39s (restore drill, staging) |
| pg_dump lógico | según frecuencia de dump (manual) | ~7s (restore drill, prod) |

Objetivo production (provisional): RPO ≤ 5 min (PITR), RTO ≤ 30 min.

## 10. Troubleshooting (rápido)

- `railway service status --service feb-score-api` → estado deployment.
- `railway logs --service feb-score-api --tail 200` → runtime logs.
- `railway metrics --service feb-score-api` → resource/HTTP metrics.
- `railway connect Postgres --tunnel-only --ssh -P 15433` → psql/túnel privado para dumps/restores.
- `railway deployment list --service feb-score-api` → histórico de deployments.
- `railway bucket info --bucket Postgres-PITR` / `railway bucket list` → estado backups (no imprimir creds).

## 11. Proveedor / contactos

- Railway: project `feb-score-production`, workspace `espanadeantes's Projects`, región ams.
- TLS: edge Railway (Let's Encrypt, `*.up.railway.app`); HSTS: NO configurable en el edge (CDN/proxy delante si se exige).
- Dominio: `https://feb-score-api-production.up.railway.app` (default Railway; usar custom domain + DNS si se exige dominio propio).

## 12. Automated CD (FASE 20)

- Workflow: `.github/workflows/deploy-production.yml`.
- Trigger: **`workflow_dispatch` manual + input `confirm`="deploy production"** (NO `push` auto-deploy a production).
- GitHub Environment `production` (creado). **required-reviewers protection BLOCKED por plan Free** ("billing plan supports required reviewers protection") → el gate manual se implementa via el input `confirm` + el step `Guard: manual confirmation`. Para approval true-style elevar el plan GitHub.
- Secrets (GitHub repo secrets, nunca en repo): `RAILWAY_TOKEN` (production PAT), `RAILWAY_SERVICE_NAME=feb-score-api`, `RAILWAY_PROD_DOMAIN=feb-score-api-production.up.railway.app`, `FEB_SCORE_PROD_SMOKE_KEY`.
- Flow CI: tests(479) → `railway up --service feb-score-api` → esperar `SUCCESS` → `/ready` 200 (schema_version=1) → smoke autenticado → POST sin key 401. Fail-fast (`exit 1`) si readiness/smoke/token fallan. `image_ref=${GITHUB_SHA}` (commit SHA como ref inmutable).
- **Production PAT**: debe crearse en Railway Dashboard → Settings → API Tokens (scoped a feb-score-production) y agregarse como GitHub secret `RAILWAY_TOKEN`. El CLI no puede mintarlo. Sin él, el workflow falla abierto (seguridad por default). El deploy real se ejecutó vía `railway up` (equivalente al workflow) → deployment actual `d0bc5e25` SUCCESS.

## 13. Security hardening (FASE 20)

- `/docs` y `/openapi.json` restringidos en production vía env `FEB_SCORE_DISABLE_DOCS=true` (default OFF → staging-safe). `docs_url`/`openapi_url` = None cuando el flag está activo.
- Auth: 401 sin key; 401 key inválida; 200 key válida. Key rotada (old 401).
- PG privado (SSH tunnel, sin TCP proxy público). Rate limit 120/min. Non-root (`USER feb`).

## 14. Plan/billing notes (FASE 20)

- Railway plan Hobby **limita a 3 buckets/project** → el dump lógico prod reutiliza el bucket `Postgres-PITR` con prefijo `prod-dumps/` (no se creó bucket dedicado; no se auto-upgradeó).
- External S3 (true DR) NO disponible → offsite real = bucket Railway S3-compatible (off-app). Bloqueado a external S3 hasta credentials reales.
- Alerting (email/Slack) NO expuesto vía CLI → Dashboard.

## 15. CD validation + auth-token-format (FASE 20.1 / 20.2)

- `RAILWAY_TOKEN` (production PAT) → GitHub Secret (crearse en Railway Dashboard → Settings → API Tokens; CLI no lo minte). Presente en el secret registry.
- `FEB_SCORE_PROD_SMOKE_KEY` → GitHub Secret = **el 64-hex production key crudo** (parte antes del `=` en `FEB_SCORE_API_KEYS`). NO incluye `;role` ni `=prod:admin`. El API (`src/feb_score/api/auth.py`) parsea `FEB_SCORE_API_KEYS` como entries `key=principal_id:role` (`;` separador) y hace lookup directo del `Bearer <key>` → el header porta SOLO el 64-hex; el role se deriva del entry env, nunca del request. Enviar `key=prod:admin` o `;prod:smoke` como Bearer → 401 (lookup miss). `staging_smoke.sh "BASE_URL" "$FEB_SCORE_PROD_SMOKE_KEY"` envía `Bearer ${API_KEY}` crudo.
- Fail-fast: el workflow verifica presencia no vacía de `RAILWAY_TOKEN`, `FEB_SCORE_PROD_SMOKE_KEY` y fail-fast `exit 1` antes de `railway up` (validado: run detenido en guard cuando el secret estaba vacío → prod untouched).
- `RAILWAY_SERVICE_NAME` (=`feb-score-api`) y `RAILWAY_PROD_DOMAIN` (=`feb-score-api-production.up.railway.app`) son identifiers públicos → fallback en el workflow (`${VAR:-literal}`); no son secret.
- GitHub Environment `production` con `protection_rules=[]` (plan Free) → no required-reviewers; el control humano es el input `confirm="deploy production"` + fail-fast guards (no auto-deploy desde push).
- Validación final prod (2026-08-13 cierre): `/health` 200, `/ready` 200 (`schema_version=1, database=ok, migrations=up_to_date`), `/docs` 404, POST no-key 401, deployment `d0bc5e25` SUCCESS. Smoke autenticado corre dentro del workflow con el secret.
- Staging intacto (FASE 20.2): `/health` 200, `/ready` 200, `/docs` 200 (no redeploy/hardening).

Ver `docs/FASE_20_2_CLEANUP_REPORT.md` y `docs/FASE_21_B2_REPORT.md`.

### FEB Source Connector (FASE 21.B1/B2)

- Fuente real FEB: `GET https://intrafeb.feb.es/LiveStats.API/api/v1/BoxScore/{match_id}` con `Authorization: Bearer <JWT>`.
- **FASE 24.2 (auto-token):** el JWT se obtiene automáticamente de la página pública `GET https://baloncestoenvivo.feb.es/partido/{match_id}` (input hidden `_ctl0:token`, ~24h de validez, reutilizable para todos los partidos de la ventana; cache en memoria). Ya NO hace falta provisionar/rotar `FEB_TOKEN` a mano; `FEB_TOKEN`/`--feb-token` sigue como override opcional. El token nunca se imprime, almacena ni serializa.
- `external_id` = match_id FEB. `competition_id` domain = `segunda-feb` (Feb `CompID` preservado en `source`).
- `scheduled_at` parseado de `dd-mm-yyyy - HH:MM` → ISO `+01:00` (offset B2 provisional; TZ real → B3).
- Idempotent: `command_id` UUIDv5(`season_code|competition_id|external_id`); `POST create_or_update_match` → 200/409.
- CLI: `python3 scripts/feb/ingest_match.py --fixture <json> --dry-run` (offline, NO exige token/API key); `--match-id` con auto-token (FASE 24.2) + `FEB_API_KEY` para POST real; `FEB_TOKEN` opcional como override.
- `scripts/feb/smoke_fetch_feb.py` (manual), no CI. Env: `FEB_TOKEN, FEB_MATCH_ID, FEB_SEASON_CODE` (req), `FEB_COMPETITION_ID`, `FEB_API_KEY`, `FEB_TARGET_API`.
- **Contract constraint:** `raw` sólo `boxscore_ref`/`teamstats_ref`; player stats NO se embeden (FASE 21.B3 persistence).

## 16. FEB Source Connector (FASE 21.B1)

- Connector: `scripts/feb/ingest_match.py` (Python stdlib only, read-only fetch → normalize → `POST /v1/commands/create_or_update_match`).
- Idempotent: `command_id` = UUIDv5 deterministic (`season_code|competition_id|external_id`); `external_id` preservado del source FEB → server-side dedup garantiza no-duplicado.
- Sources no-secret: API key via env `FEB_API_KEY` (raw 64-hex); nunca impresa. `FEB_SOURCE_URL`, `FEB_TARGET_API`, `FEB_COMPETITION_ID` vía env.
- No toca dominio/staging/prod ni la imagen API (es script standalone; no redeploy necesario).
- Estado: **merged `main`** (PR #2 → `92fa4a2`), CI 488 tests PASS. Ingesta real en vivo **PENDING** fuente FEB real (ver `docs/FASE_21_B1_REPORT.md`).

## 17. Auto-ingesta de temporada (FASE 25)

Para que el sistema siga ingiriendo solo cuando arranque la temporada **2026-2027**:

### Parámetros de temporada
- `FEB_SEASON_CODE` (env, no requerido): temporada activa; default `2025-2026`. En el
  calendario FEB se deriva el año `t` del código (`2026-2027` -> `t=2026`) y la URL
  del calendario se construye sola (`discover_matches._discovery_url`).
- El resto del pipeline (discover/ingest/backfill) valida contra `FEB_SEASON_CODE`.

### Orquestador `scripts/feb/run_auto_ingest.py`
- `--season` (o env `FEB_SEASON_CODE`), `--weekly` (sweep completo) o default
  **daily** (solo rondas activas = última jugada + siguientes 14 días).
- Ingiere vía `ingest_round.run_round` (BoxScore FEB auto-token -> POST
  `create_or_update_match` + `upsert_match_stats`, idempotente UUIDv5).
- Al final dispara el command server-side `backfill_catalog` (POST
  `/v1/commands/backfill_catalog`, rol `admin`) para refrescar nombres oficiales
  de jugadores/equipos sin exponer credenciales DB al runner.
- Stdlib only; corre en cualquier runner con python3. No requiere pip install.
- Env: `FEB_TARGET_API`, `FEB_API_KEY` (raw 64-hex, rol admin), `FEB_SEASON_CODE`,
  `FEB_GROUPS` (default ESTE,OESTE), `FEB_INGEST_MODE` (daily|weekly).

### Workflow `.github/workflows/auto-ingest.yml`
- `on: schedule`: daily 06:00 UTC (rondas activas) + weekly Sun 06:30 UTC (sweep completo).
- `workflow_dispatch` con inputs `mode` (daily|weekly) y `season`.
- **Secret nuevo requerido**: `FEB_TARGET_API` (URL pública del API, ej.
  `https://feb-score-api-production.up.railway.app`). La key de API REUTILIZA el
  secret ya existente `FEB_SCORE_PROD_SMOKE_KEY` (raw 64-hex `prod:admin`).
  Guard fail-fast: falla si `FEB_TARGET_API` falta o si la key no está configurada.

### Command `backfill_catalog` (server-side, FASE 25)
- `POST /v1/commands/backfill_catalog`, rol `admin`, contract
  `contracts/commands/backfill_catalog.v1.json`; payload `{season_code, entity:
  players|teams|both, dry_run}`.
- Reutiliza `CatalogBackfillService` (política determinista e idempotente, FASE 24.1)
  + resolvers oficiales: jugadores = FEB BoxScore (auto-token, FASE 24.2), equipos =
  calendario público FEB. Names nunca se inventan: sin conector FEB los jugadores se
  crean con `name NULL` (gap documentado).
- Corre dentro de la Unit of Work del CommandRunner (1 conexión compartida).
- El Dockerfile ahora incluye `scripts/feb` (los resolvers los importan en runtime).
- Autenticado con rol `admin`: la key de producción es `prod:admin` (válida).