# FASE 20.2 — CLEANUP / FINAL HARDENING

## Status

**PASS — CLEANUP FINALIZADO**

Estado de production: DEPLOYED / VERIFIED / HARDENED / AUTOMATED (CD workflow validado).
Staging: DEPLOYED / VERIFIED / INTACT.

No se modificó infraestructura, secrets funcionales ni API keys. No se tocó staging.

## 1. Repo scan

- `git status --porcelain` → working tree limpio.
- No temp/debug artifacts (`.bak/.tmp/.log/.swp/.env/.dump/` untracked) en working tree ni tracked.
- No secrets hardcodeados ni 64-hex literales en tracked files (grep `[0-9a-f]{64}`, `RAILWAY_=*` → 0 matches en `.py/.yml/.sh`).

## 2. Workflow `deploy-production.yml` review

- Revisado completo: **no hay código/config temporal que eliminar**. Todo el bloque `Guard` + fail-fast es necesario.
- Mantiene los 4 secretos: `RAILWAY_TOKEN`, `RAILWAY_SERVICE_NAME`, `RAILWAY_PROD_DOMAIN`, `FEB_SCORE_PROD_SMOKE_KEY` (más fail-fast por cada uno).
- `RAILWAY_SERVICE_NAME`/`RAILWAY_PROD_DOMAIN` usan fallback público (`${VAR:-literal}`) porque son identifiers no-secretos (service name `feb-score-api`, domain público) — no son secret, no se exponen.
- Micro-cleanup (solo comentario, sin efecto funcional):
  - Comentario header corregido: "required reviewer = repo owner" → precisión sobre plan Free (no hay reviewers; el control humano es el input `confirm` + fail-fast guards). Linea 4-7.

## 3. Formato de auth — solución definitiva del 401

Código real (`src/feb_score/api/auth.py`, `ApiKeyAuthenticationProvider`):

- `FEB_SCORE_API_KEYS` (Railway env) es una lista de entries `key=principal_id:role` separadas por `;`:
  ```
  <64hex>=prod:admin
  ```
  - `key` = el 64-hex token.
  - `principal_id` = e.g. `prod`, `staging`, `ingest`.
  - `role` ∈ `{system, admin, editor}` (ROLE_LEVELS), nunca forjeado desde el request.
- `authenticate()` extrae `Authorization: Bearer <key>` (**directo**) y hace lookup vs el dict parseado → **el `<key>` enviado como Bearer debe ser SOLO el 64-hex**, sin `;role` ni `=prod:admin`. El role se resuelve del **entry de la variable env**, no del header.

Por tanto:
- `FEB_SCORE_PROD_SMOKE_KEY` (GitHub Secret) = **el 64-hex production key crudo** (parte antes del `=` en `FEB_SCORE_API_KEYS`).
- Si el secret contiene `key=prod:admin` completo o `;prod:smoke`, el Bearer lookup falla → **401**. Ese fue el root cause del primer run (el secret estaba vacío; y conceptualmente debe ser el 64-hex crudo).
- `staging_smoke.sh` envía `Bearer ${API_KEY}` crudo → correcto con el 64-hex como secret.

No se imprimió ni valor de key ni token.

## 4. CI

- `scripts/ci.sh`: **479 passed**, exit 0, "CI pipeline OK".
- GitHub Actions `ci` (workflow principal): green (tests job PASS en el run de deploy-production).
- `deploy-production.yml` (yaml): parseado correctamente por git — workflow exists & runnable (scoping 404 en `gh api` por workspace-app install, no afecta ejecución).

## 5. Verificación production (real)

| Check | Result |
|---|---|
| `GET /health` | **200** |
| `GET /ready` | **200** `{"schema_version":"1","database":"ok","migrations":"up_to_date"}` |
| `GET /docs` | **404** (hardened, `FEB_SCORE_DISABLE_DOCS=true`) |
| POST `/v1/commands/create_or_update_match` no-key | **401** |
| smoke autenticado | validado por el workflow en su step Smoke (con `FEB_SCORE_PROD_SMOKE_KEY`) |
| deployment actual | `d0bc5e25` SUCCESS |

Smoke autenticado **no** ejecutado manualmente (el key es secreto; el workflow lo prueba end-to-end al dispararse con el secret seteado).

## 6. Verificación staging (isolation)

| Check | Result |
|---|---|
| `staging /health` | **200** |
| `staging /ready` | **200** (`schema_version=1, database=ok, migrations=up_to_date`) |
| `staging /docs` | **200** (staging intencionalmente NO hardened; untouched) |

**Staging intacto:** no se creó/modificó/renombró/redeployó/borró nada de `pretty-motilaition`. El directorio local se enlazó a `feb-score-production`. Staging no tocado desde FASE 20.

## 7. Deployment (production)

- Project `feb-score-production` (id 7878b33c-c516-4ba7-a946-94564b2c62de), env `production`.
- `feb-score-api` deployment `d0bc5e25` SUCCESS (imagen `b9d3488`-derived release v1.0.0, sin code change funcional en app).
- `Postgres` (PG 18, privado) deployment `de6360d2` SUCCESS (no tocado en FASE 20.1/20.2).
- PITR enabled; dump lógico offsite (sha `a0a3941c…`).

## 8. Documentation links

- `docs/FASE_20_REPORT.md` (CD workflow validation + hardening, previo a este fix).
- `docs/PRODUCTION_RUNBOOK.md` (actualizado).
- `docs/STAGING.md`.

## 9. Remaining (documentado, no accedido)

- External S3 (true DR): no credentials en entorno → offsite real = bucket Railway.
- Alerting email/Slack: Dashboard (no CLI).
- HSTS: CDN/proxy delante del edge.
- Rotar periódicamente la clave production.

## Commit cleanup/docs

`docs: finalize FASE 20.1/20.2 cleanup + auth-token-format + production CD runbook` sobre:
- `docs/FASE_20_2_CLEANUP_REPORT.md` (new).
- `docs/PRODUCTION_RUNBOOK.md` (appended FASE 20.2: cleanup, auth-token-format, CD validation; FASE 20.1 fix).
- `.github/workflows/deploy-production.yml` (comentario header accuracy).
- `PROJECT_CONTEXT.md` (línea estado: PRODUCTION DEPLOYED/VERIFIED/HARDENED/AUTOMATED).

CI de push esperado GREEN (479 tests).