# FASE 20 — PRODUCTION HARDENING & AUTOMATED CD

## Status

**PASS — PRODUCTION HARDENED / AUTOMATED CD READY (con limitaciones documentadas)**

Production está deployed, verificada, endurecida (/docs deshabilitado via env flag), con backup/PITR real, restore drill, rollback, smoke, TLS y staging completamente intacto. El workflow `deploy-production.yml` está validado (YAML correcto) y reproduce el deploy real manual; el CD automático end-to-end con secret pendiente de creación manual de un production PAT (limitación real documentada, no simulada).

## Estado inicial (real)

- PRODUCTION DEPLOYED (FASE 19): project `feb-score-production`, environment `production`, service `feb-score-api` + `Postgres`, dominio `https://feb-score-api-production.up.railway.app`, deployment `14be6744` → `9340487a` (rollback), PITR enabled, pg_dump offsite, restore drill (RTO 7s), smoke/auth/TLS PASS.
- Staging (`pretty-motivaition`) intacto y verde.

## Changes reales (FASE 20)

- **CODE (pequeño, cubierto por tests)**: `src/feb_score/api/main.py` — gate env-gated de Swagger/OpenAPI: `FEB_SCORE_DISABLE_DOCS=true` desactiva `/docs` y `/openapi.json` (default OFF → behavior actual preservado; staging-safe). +2 tests en `tests/api/test_health_openapi.py`. CI: **479 passed**.
- **CONFIG/CI**: nuevo workflow `.github/workflows/deploy-production.yml` (manual `workflow_dispatch` + `confirm` input gate + GitHub Environment `production`; NO auto-deploy desde push; fail-fast si falta token o readiness/smoke falla; traceability por commit SHA).
- **GitHub Environment**: environment `production` creado (read-only check). required-reviewers protection: **BLOCKED por plan Free** ("billing plan supports required reviewers protection"). Gate manual mitigado via `confirm` input.
- **CONFIG prod**: var `FEB_SCORE_DISABLE_DOCS=true` seteada en `feb-score-api` (Railway).
- **INFA**: ningún recurso nuevo adicional (reuso prod PG/bucket existentes).

## Automated CD (P0)

| Ítem | Status | Evidencia |
|---|---|---|
| Workflow `deploy-production.yml` creado | PASS | `.github/workflows/deploy-production.yml`; YAML validado (pyyaml + GitHub lint al push) |
| Disparador manual (no auto desde push) | PASS | `on: workflow_dispatch` solo; `push:` no incluido |
| GitHub Environment `production` | PASS (env) / PARTIAL (approval) | env `production` creado; **required-reviewers BLOCKED (plan Free)** → mitigado por input `confirm` |
| Secrets vía GitHub Secrets, no en repo | PASS | workflow referencia `secrets.*` |
| build → registry → deploy | PASS (real) | `railway up --service feb-score-api` build + deploy; deployment `9340487a` / `d0bc5e25` SUCCESS |
| /health post-deploy | PASS | 200 |
| /ready post-deploy | PASS | 200 (`schema_version=1, database=ok, migrations=up_to_date`) |
| authenticated smoke | PASS | STAGING SMOKE OK (POST accepted + match_upserted, GET 200) |
| 401 without key | PASS | POST sin key → 401 |
| fail-fast si readiness/smoke falla | PASS (logic) | steps `exit 1` en readiness y en smoke |

**Nota real sobre ejecución end-to-end del workflow**: no se ejecutó el workflow `deploy-production` con secret real porque requiere un **GitHub secret `RAILWAY_TOKEN`** (production PAT de Railway) que **no puede mintiéndose desde CLI** (Railway tokens se crean en Dashboard → Settings → API Tokens). El deploy REAL productivo se ejecutó y verificó manualmente vía `railway up` (misma cadena de comandos que el workflow). El workflow está validado por sintaxis + lógica + deploy manual equivalente. → Estado: **CD validado; ejecución automática pendiente de production PAT** (no simulado).

## Rollback automation (P0)

- `deploymentRedeploy(id)` (GraphQL) usado en FASE 19 → `9340487a` SUCCESS.
- El workflow incluye `image_ref=${GITHUB_SHA}` para trazabilidad; el rollback a un SHA/commit anterior es reproducible con `deploymentRedeploy(deployment_id_of_commit_X)`.
- **No se ejecutó un rollback real innecesario** en FASE 20 (evidencia de FASE 19 preservada); el mecanismo está documentado y probado.

## Monitoring / alerting (P1)

| Ítem | Status | Evidencia |
|---|---|---|
| Logs | PASS | `railway logs --service feb-score-api` |
| Métricas | PASS | `railway metrics --service feb-score-api` (resource/HTTP) |
| restartPolicy | PASS | `restartPolicyType=ALWAYS` (railway.toml) |
| healthcheck | PASS | `healthcheckPath=/ready`, timeout 300s |
| Alerting (email/Slack/5xx) | BLOCKED (CLI) | Railway no expone alerting vía CLI; disponible vía Dashboard → documentado (no simulado) |
| `/metrics` Prometheus | N/A | no expuesto (404); no se instalará plataforma observability (regla: no over-engineering) |

## Security hardening (P1)

| Ítem | Status | Evidencia |
|---|---|---|
| `/docs` restringido en production | PASS | `FEB_SCORE_DISABLE_DOCS=true` → `/docs` 404, `/openapi.json` 404 |
| HTTPS | PASS | edge Railway |
| TLS válido | PASS | Let's Encrypt `*.up.railway.app` hasta 2026-10-27 |
| HTTP→HTTPS | PASS | edge Railway |
| HSTS | PARTIAL | no configurable en Railway edge → CDN/proxy delante si se exige |
| PostgreSQL privado | PASS | túnel SSH, sin TCP proxy público |
| Auth 401 sin key / key válida 200 | PASS | verificado |
| Secrets fuera de Git | PASS | `git grep` → solo placeholders CI + ejemplos |
| Logs sin secret leakage | PASS | 0 hits |
| non-root | PASS | `USER feb` (uid 1000) |
| rate limit | PASS | 120/min |
| `/docs` público en staging | N/A (decisión) | staging no redeployado → `/docs` staging sigue 200 (intencional) |

## Backup / DR (P1)

- PITR prod continuo: **ENABLED**, bucket `Postgres-PITR` (prod) 7.9 MB / 1.380 objetos (WAL archivado tras write). ✅
- pg_dump prod offsite: `feb_score_prod_20260813T212828Z.dump` (18.6 KiB, SHA `a0a3941c…`) en `prod-dumps/`; integridad verify. ✅
- Restore drill prod: RTO 7s, schema_version=1, 12 tablas, match conocido; db borrada, prod intacta. ✅
- Plan Hobby **limita a 3 buckets/project** → no se pudo crear bucket dedicado prod; el dump lógico reutiliza `Postgres-PITR/prod-dumps/`. No se auto-upgradeó (regla billing).
- External S3 (true DR outside Railway): **BLOCKED** — no hay credentials AWS/Azure/GCP en el entorno (no se inventaron). Offsite real = bucket Railway S3-compatible (off-app).

## Escalabilidad (P2 — NO cambiado)

- No se añadió Redis, Kafka, broker, multi-réplica, CDN, WAF ni microservicios (regla FASE 19).
- 1 API replica + 1 PG + PITR + offsite. ← FUTURE: escalar a N réplicas (migraciones externalizadas), Redis rate-limit, multi-región, CDN, /metrics Prometheus, external S3.

## Validación final

1. `scripts/ci.sh` → **479 passed**, exit 0, CI pipeline OK.
2. GitHub Actions: workflow `ci` green (4bda25d success); `deploy-production` syntax valid (el run del 9b160d3 falló por YAML roto → fixed 4bda25d).
3. Production actual: `/health` 200, `/ready` 200, `/docs` 404, smoke PASS, POST sin key 401.
4. Staging actual: `/health` 200, `/ready` 200, `/docs` 200 (intacto, no redeployado).

## Staging isolation check

- Pretty-motilaition (staging) verificado sano e **intacto** al final de FASE 20: `/health` 200, `/ready` 200.
- No se creó, modificó, redeployó, renombró ni borró ningún recurso de `pretty-motilaition` durante FASE 20. El directorio local se enlazó a `feb-score-production` con `railway init`; `railway up`/`variable set`/`postgres pitr` se ejecutaron contra el project `feb-score-production` (id 7878b33c), NUNCA contra pretty-motilaition.

## Deployment final (production)

- Project `feb-score-production` (id 7878b33c), env `production` (id 4f80ebc0).
- `Postgres` (PG 18, privado): deployment `de6360d2` SUCCESS.
- `feb-score-api`: `14be6744` → rollback `9340487a` → hardening redeploy `d0bc5e25` SUCCESS (último). `/docs` 404, `/health` 200.
- Dominio `feb-score-api-production.up.railway.app` (id b410f3af, ACTIVE), TLS válido.
- Bucket `Postgres-PITR` (prod, ams): PITR + `prod-dumps/`.

## Commit final

- `9b160d3` `feat: gate /docs+openapi behind FEB_SCORE_DISABLE_DOCS (prod hardening) + production CD workflow`
- `4bda25d` `fix: quote workflow step name with colon (valid YAML)` (el 9b160d3 falló en deploy-production por YAML roto → fixed)
- HEAD actual: `4bda25d`.

## Remaining external debt

- **Production PAT → GitHub secret `RAILWAY_TOKEN`**: debe crearse en Railway Dashboard (Settings → API Tokens, scoped a feb-score-production) y agregarse como repo secret → habilita el CD automático del workflow. (Bloqueado: CLI no mintea tokens.)
- **External S3 offsite (true DR)**: falta credentials AWS/Azure/GCP → usar bucket Railway (off-app) como se hizo.
- **Alerting**: via Dashboard (no CLI).
- **HSTS**: CDN/proxy delante del edge.
- **Rate limiter distribuido / multi-réplica**: futuro (Redis).
- Rotación periódica de API keys.

## Conclusión

**PRODUCTION DEPLOYED / HARDENED / AUTOMATED CD READY (limitado)**

- Production operativa, isolada del staging, con backup/PITR/restore/rollback/smoke reales.
- CD automatizado validado (workflow) y deploy real probado; gating manual vía `confirm` input (required-reviewers blocked por plan Free).
- Staging intacto.

Declarado `PRODUCTION HARDENED / AUTOMATED CD READY` condicionado a: crear el production PAT → GitHub secret `RAILWAY_TOKEN` (lo que desbloquea el deploy automático del workflow end-to-end). Hasta entonces el deploy es reproducible manualmente (proven) y el workflow está validado; la ejecución automática del workflow pendiente de ese secret manual. No se declara "fully automated + external DR" (falta external S3 y el secret).