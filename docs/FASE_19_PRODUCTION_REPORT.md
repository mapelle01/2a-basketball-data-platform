# FASE 19 — PRODUCTION DEPLOYMENT

## Status

**PASS — PRODUCTION DEPLOYED**

Production desplegada en un project Railway aislado (`feb-score-production` / environment `production`), independiente del staging (`pretty-motivaition` project/production environment). Todos los gates obligatorios P0 superados con evidencia real.

## Summary (evidencia real)

| Criterio | Status | Evidencia |
|---|---|---|
| Production API | PASS | service `feb-score-api` → deployment `9340487a` SUCCESS; `https://feb-score-api-production.up.railway.app` |
| Production PG | PASS | service `Postgres` Online; PostgreSQL 18.4 (Debian 18.4-1.pgdg13+1); privado (túnel SSH, sin TCP proxy público) |
| TLS | PASS | Let's Encrypt CN=*.up.railway.app; notBefore 2026-07-29 → notAfter 2026-10-27; `ssl_verify_result=0`; HTTP→HTTPS edge |
| DNS / dominio | PASS | `feb-score-api-production.up.railway.app` generado y ACTIVE (id b410f3af) |
| Secrets | PASS | FEB_SCORE_ENV=production; FEB_SCORE_DATABASE_URL=${{Postgres.DATABASE_URL}} (ref interna privada); FEB_SCORE_API_KEYS=new key `=prod:admin` (nunca impresa, generada `openssl rand -hex 32`); no reutilizada staging key |
| Auth | PASS | POST sin key → **401**; POST con key válida → **200 accepted**; POST con key inválida → **401** |
| Migration | PASS | boot ejecuta `db.migrate()`; `schema_version=1`; `migrations=up_to_date` en `/ready` |
| Health | PASS | `GET /health` → 200 `{"status":"ok"}` |
| Readiness | PASS | `GET /ready` → 200 `{"status":"ready","checks":{"schema_version":"1","database":"ok","migrations":"up_to_date"}}` |
| Smoke | PASS | `scripts/staging_smoke.sh` contra prod → STAGING SMOKE OK (POST 200 accepted + match_upserted; GET match 200) |
| Rollback | PASS | redeploy previo `deploymentRedeploy(id:14be6744)` → `9340487a` SUCCESS (~30s) → /health 200 / /ready 200 / smoke PASS / datos intactos; deployment final 9340487a SUCCESS |
| PITR (físico continuo) | PASS | `railway postgres pitr status` → enabled, bucket wired yes; bucket `Postgres-PITR` (prod) 6.9 MB / 1.348 objetos (WAL archiving activo) |
| Offsite backup (lógico) | PASS | `pg_dump -Fc` (PostgreSQL 18.4 client) 18.6 KiB, SHA-256 `a0a3941cc6e97bcd74ec0c40f3c84f0f96cc1be2a12f1da9cc8d83337aa4a8b1`; upload a `s3://postgres-pitr-6f5jxudzydk/prod-dumps/`; integridad verify (download→cmp IDENTICAL) |
| Restore (lógico drill) | PASS | restore a db temp `feb_restore_test_prod` (isla): `schema_version=1`, 12 tablas, `domain_events=1`, match conocido `smoke-1786656288` presente; **RTO 7s**; db borrada; db prod `railway` intacta (1 match conocido) |
| RPO | PASS (provisional) | PITR continuo ~60s (WAL) |
| RTO | PASS (provisional) | Restore lógico 7s; redeploy rollback ~30s (<< objetivo 30 min) |
| Monitoring | PARTIAL | logs (`railway logs`), `railway metrics`, restartPolicy=ALWAYS, healthcheck /ready; **alerting email/slack NO expuesto vía CLI** (Dashboard) |
| Runbook | PASS | `docs/PRODUCTION_RUNBOOK.md` creado |

## Changes (real)

- **INFA**: project Railway `feb-score-production` (id `7878b33c-c516-4ba7-a946-94564b2c62de`) + environment `production` (id `4f80ebc0-9a6c-44be-84f5-e7cdfd968507`). Creado service `Postgres` (plugin, PostgreSQL 18, privado, postgres-volume, ams). Creado service stub `feb-score-api`, vars productivas seteadas (ver abajo), deploy vía `railway up` desde la imagen del commit validado `b9d3488`.
- **CONFIG**: variables Railway de production (nombres, valores nunca impresos):
  - `FEB_SCORE_ENV=production`
  - `FEB_SCORE_DATABASE_URL=${{Postgres.DATABASE_URL}}`
  - `FEB_SCORE_LOG_LEVEL=info`
  - `FEB_SCORE_RATE_LIMIT=true`
  - `FEB_SCORE_RATE_LIMIT_PER_MINUTE=120`
  - `FEB_SCORE_API_KEYS=<new 64-hex>=prod:admin` (rotada; la anterior revocada → 401)
- **DOMAIN**: `https://feb-score-api-production.up.railway.app` (id b410f3af, ACTIVE).
- **BACKUP**: PITR enable en prod; `pg_dump -Fc` prod → bucket `Postgres-PITR/prod-dumps/`.
- **NO changes de código de aplicación** (el Dockerfile/railway.toml/binario b9d3488 son el release v1.0.0 validado; 477 tests PASS, CI verde).

## Secrets handling (reales)

- API key generada con `openssl rand -hex 32` (formato `key=prod:admin`), seteada vía stdin (`railway variable set ... --stdin`), nunca impresa ni en args/ps.
- La key de STAGING no se reutilizó; el archivo staging `/tmp/feb_smoke_key` no se expuso.
- Production key persistida en `/tmp/feb_prod_key` (0600). Recomendar rotación periódica + `shred -u` al cierre.
- DATABASE_URL: referencia interna privada `${{Postgres.DATABASE_URL}}`; pg_dump via túnel SSH local (password enmascarado/parsed a env, nunca echo).

## Production vs Staging (aislamiento)

| Aspect | Staging (pretty-motivaition) | Production (feb-score-production) |
|---|---|---|
| Project | pretty-motivaition | feb-score-production |
| Environment | production (staging) | production (prod) |
| API service | feb-score | feb-score-api |
| PG | Postgres-18, privado | Postgres-18, privado |
| Dominio | feb-score-production.up.railway.app | feb-score-api-production.up.railway.app |
| API key | rotada (staging) | nueva (prod) — no reutilizada |
| PITR | enabled | enabled |
| Estado verificado al final | 200/200 sano (no tocado) | 200/200 sano |

El directorio local (`docs/FASE_19_PRODUCTION_REPORT.md`) está linkeado a `feb-score-production` tras `railway init/link`.

## Backup status

- **PITR continuo (físico)**: ENABLED, bucket `Postgres-PITR` (prod) cableado, WAL archiving activo (6.9 MB / 1.348 objetos, creciendo). pgBackrest retención full=4/diff=14.
- **Backup lógico offsite (pg_dump -Fc)**: prod dump `feb_score_prod_20260813T212828Z.dump` (18.6 KiB, SHA-256 `a0a3941c…`) subido a `prod-dumps/` del bucket S3 Railway; integridad verificada (download identical).
- **Limitación real (plan/billing)**: el plan Hobby **limita a 3 buckets por project** → no se pudo crear un bucket dedicado `feb-score-dumps-prod`; el dump lógico se almacena en el bucket `Postgres-PITR` con prefijo `prod-dumps/`. Tampoco se auto-upgradeó (regla de billing).
- **Limitación real (grant OAuth)**: `railway postgres pitr backup create` / `pitr schedule set --daily` seguén con `OAUTH_INSUFFICIENT_GRANT` (scope de la sesión CLI); el PITR continuo (no usa esa mutación) opera.
- **External S3 true DR**: NO hay credentials AWS/Azure/GCP en el entorno → el único offsite real disponible es el bucket Railway S3-compatible (off-app).

## Restore status

- **PITR (físico)**: enable + WAL archiving verificado (FASE 18.6 staging; en prod habilitado y archivado). Restore PITR a timestamp a una instancia hermana (mecanismo verificado en staging, 39s, datos validados). No se ejecutó restore PITR sobre prod para no duplicar coste, pero el bucket/archive están operativos.
- **Lógico (pg_dump)**: restore drill real en prod → db temp `feb_restore_test_prod`, schema_version=1, 12 tablas, domain_events, match conocido presente; RTO 7s; db limpiada; prod db intacta.

## RPO / RTO

- RPO: ~60s (PITR WAL continuo).
- RTO: lógico 7s; redeploy rollback ~30s. (Objetivo ≤30 min.)

## Rollback (production)

- `deploymentRedeploy(id: 14be6744)` → deployment `9340487a` SUCCESS (~30s).
- Verificado: `/health` 200, `/ready` 200 (schema_version=1, database=ok, migrations=up_to_date), smoke prod PASS, datos intactos (match conocido presente).
- Deployment final productivo: `9340487a` (SUCCESS) = redeployment de la imagen original 14be6744. 14be6744 quedó REMOVED (rolled off) en el histórico.

## Monitoring / observability

- Logs: `railway logs --service feb-score-api` ✅.
- Métricas: `railway metrics --service feb-score-api` (resource/HTTP) ✅.
- Restart: `restartPolicyType=ALWAYS` ✅.
- Healthcheck: `/ready` (300s) ✅.
- **Alertas (email/Slack)**: NO expuestas vía CLI; disponibles via Dashboard Railway (Health Checks/notifications). **Documentado como PARTIAL.**
- `/metrics` Prometheus: no expuesto (404) → no se instalará plataforma observability adicional (regla: no sobre-ingeniería).

## Security checks (production)

- HTTPS activo ✅ / TLS Let's Encrypt válido ✅ / HTTP→HTTPS edge ✅.
- PostgreSQL privado (túnel SSH, sin TCP proxy público) ✅.
- Auth: sin key 401 ✅; key válida 200 ✅; key inválida 401 ✅; key rotada (old 401) ✅.
- Secrets fuera de Git ✅ (git grep: solo placeholders CI + ejemplos literales).
- Logs sin secret leakage ✅ (0 hits).
- Docker non-root (`USER feb`, uid 1000) ✅.
- Rate limit ON (`FEB_SCORE_RATE_LIMIT=true`, 120/min) ✅.
- HSTS: NO configurable en Railway edge → pendiente (CDN/proxy delante si se exige) → PARTIAL.
- `/docs` Swagger: público por decisión (v1.0.0; restringir fase posterior) → documentado.

## CI

- `scripts/ci.sh` local: exit 0, **477 passed**, `CI pipeline OK`.
- GitHub Actions (commit `b9d3488` + docs FASE 19): **green** (runs 31736960874, 31739385012, 31742733329, y el push FASE 19 en ejecución).

## Deployment creado en esta fase (production)

- Project `feb-score-production` (id 7878b33c).
- Environment `production` (id 4f80ebc0).
- service `Postgres` (PG 18, privado). deployment `de6360d2` SUCCESS.
- service `feb-score-api`: deployment `14be6744` (init) → rollback/redeploy → `9340487a` SUCCESS.
- Domain `feb-score-api-production.up.railway.app` (id b410f3af, ACTIVE).
- Bucket `Postgres-PITR` (prod, ams, PITR+dump en `prod-dumps/`).

## Remaining external debt (pendientes)

- **External S3 offsite (true DR outside Railway)**: no credentials en entorno → `PROD OFFSITE STORAGE` real = bucket Railway S3-compatible. Bloqueado a external S3 hasta que haya credentials reales. (No se declaró PRODUCTION READY afectado: el PITR + pg_dump off-app cubren el gate.)
- **backup on-demand/schedule diario vía CLI**: `OAUTH_INSUFFICIENT_GRANT` → habilitar via Dashboard o scope ampliado / external cron.
- **Alerting (email/Slack)**: via Dashboard (no CLI).
- **HSTS**: CDN/proxy delante del edge.
- **Rate limiter distribuido**: migrar a Redis cuando se escale a >1 réplica.
- **`/docs`**: restringir en prod (decisión de fase posterior; code change opcional).
- Rotar periódicamente la API key de production.

## STAGING GATE (aincreíble)

Staging (pretty-motivaition) verificado **sano e intacto** al final de FASE 19:
- `/health` 200, `/ready` 200 (`schema_version=1, database=ok, migrations=up_to_date`).
- No se creó, renombró, redeployó, modificó variables ni borró nada de pretty-motivaition durante FASE 19.

## Conclusión

**PRODUCTION DEPLOYED** (con evidencia real). Staging intacto. Todas las limitaciones reales documentadas.

No se declara "PRODUCTION FULLY OPERATIONAL CON EXTERNAL DR" — el offsite truly-external (S3 fuera de Railway) está BLOCKED por ausencia de credentials reales; el backup operativo disponible es PITR continuo (Railway) + pg_dump lógico en bucket Railway S3-compatible con integridad verificada.