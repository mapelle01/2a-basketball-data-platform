# STAGING — FEB-SCORE v1.0.0 en Railway

> Estado: **DEPLOYED y VERIFICADO** en Railway (FASE 18.5) + **BACKUP/PITR operativo,
> backup lógico offsite real, restore drill (PITR 39s + lógico 6s) y rollback probados
> con evidencia real** (FASE 18.6/18.7) + **API key rotada (new PASS / old 401)** (FASE 18.7).
> PostgreSQL real = **18** (default actual del plugin Railway, no 16).
> Limitación documentada: backup on-demand y schedule diario vía CLI bloqueados por
> `OAUTH_INSUFFICIENT_GRANT` (permiso de la sesión OAuth); el PITR continuo
> (pgBackRest + WAL a bucket) y el `pg_dump -Fc` offsite a bucket Railway sí operan.
>
> Distinción de estados (FASE 18.1):
> - **READY** = preparado en código/documentación (este estado).
> - **PROVISIONED** = recurso real creado en Railway.
> - **DEPLOYED** = aplicación realmente desplegada.
> - **VERIFIED** = prueba real ejecutada con evidencia.

## 1. Qué es STAGING y qué NO es

- **Sí:** entorno real, reproducible, de una sola réplica, que valida que
  FEB-SCORE vive correctamente fuera de local/CI: HTTPS, PostgreSQL gestionado,
  secrets fuera de Git, migraciones, health/readiness, smoke test, backups.
- **No:** producción. Sin SLA, sin DNS/dominio externo necesario (Railway
  asigna `*.up.railway.app`), sin HA, sin autoscaling, sin multi-región, sin
  broker/Redis/Kafka/Kubernetes. RPO/RTO de staging son **provisionales**
  (RPO 24h / RTO 4h) y no son los objetivos de producción.

## 2. Arquitectura

```
Internet
   ↓
Railway HTTPS (dominio <servicio>.up.railway.app o custom)
   ↓
FEB-SCORE API v1.0.0 (1 réplica, no-root, imagen desde Dockerfile)
   ↓ (red privada railway.internal)
PostgreSQL 18 gestionado (privado, DATABASE_URL por referencia)
   ↓
Backups: PITR activo (pgBackRest → bucket Postgres-PITR) + WAL continuo; pg_dump lógico pendiente
Secrets: FEB_SCORE_DATABASE_URL, FEB_SCORE_API_KEYS (variables Railway)
Monitoring: logs + /health + /ready + restart ALWAYS
```

- **API**: Railway build desde `Dockerfile` (decision: no GHCR; el Dockerfile es
  el artefacto reproducible y Railway conserva el historial de deploys para
  rollback). Config en `railway.toml`.
- **PostgreSQL**: servicio Railway Postgres **18** (default del plugin `postgres-ssl:18`), privado. `DATABASE_URL` como variable-referencia `${{Postgres.DATABASE_URL}}` del servicio PG (red interna). PITR habilitado (FASE 18.6).
- **Tráfico**: HTTPS en el edge de Railway; HSTS no es configurable en el edge
  de Railway (limitación documentada; si se exige HSTS, anteponer CDN/proxy).
- **Secrets**: variables de servicio en Railway (nunca en Git; `.env` ignorado).
- **Readiness**: `railway.toml` → `healthcheckPath = "/ready"`; `/health` es la
  sonda liveness (Docker HEALTHCHECK). Railway solo consulta el healthcheck al
  activar un deploy (no monitoreo continuo).

## 3. Servicios y variables

| Servicio | Tipo | Detalle |
|---|---|---|
| `feb-score` | Deploy from Dockerfile | 1 réplica, puerto `${{PORT}}` (Railway inyecta `PORT`; `server.py` lo lee, `FEB_SCORE_PORT` gana) |
| `Postgres` | Railway Postgres 18 | privado, sin TCP proxy público, PITR activo |
| `feb-restore-drill` | (temporal) | servicio de restore drill, creado y borrado en FASE 18.6 |

Variables de servicio del API (en Railway, no en Git):

```
FEB_SCORE_ENV=production
FEB_SCORE_DATABASE_URL=${{DATABASE_URL}}   (referencia al servicio Postgres)
FEB_SCORE_API_KEYS=<key=principal:role;...>
FEB_SCORE_LOG_LEVEL=info
FEB_SCORE_RATE_LIMIT=true
FEB_SCORE_RATE_LIMIT_PER_MINUTE=120
```

`FEB_SCORE_API_KEYS` se genera con: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

## 4. PostgreSQL

- Versión **18** (default actual del plugin Railway `postgres-ssl:18`; **no 16** — documentado, no ocultado). CI usa 16 localmente; la API es agnóstica de la minor version.
- Base: la del servicio Railway (`railway` por defecto del template).
- **Roles**: usar el rol/credencial que expone `DATABASE_URL`. Railway Postgres
  no expone superuser por diseño en la app; no se usa superuser para la
  aplicación. Si se necesita, los dumps se hacen con el rol de la base.
- **Privacidad**: el template activa un TCP proxy público por defecto → para
  staging **desactivarlo** (solo acceso por red interna).
- `schema_version` esperado tras migrar: **1** (verificable en `/ready`).

## 5. Migraciones

- Comportamiento actual (FASE 18.1): `server.py` ejecuta `db.migrate()` en el
  boot. **Mantenido** para staging con 1 réplica: `railway.toml` fija
  `overlapSeconds = "0"`, así el deploy nuevo reemplaza al anterior sin
  solapamiento y nunca hay dos instancias migrando a la vez.
- Se preserva la guarda contra schema futuro (`postgres/connection.py`):
  un schema más nuevo que el binario aborta el boot.
- **Cuándo cambiar**: al pasar a N réplicas, mover las migraciones a un paso
  único (p. ej. `preDeployCommand` o job de release). Documentado, no
  implementado todavía (sin refactor innecesario).

## 6. Deployment (CD)

Pipeline (`deploy-staging.yml`, gated por secretos; Railway construye desde Dockerfile):

```
GitHub (tests + pip check) → railway up --service <api> → esperar /ready → smoke test
```

- **Disparador**: `workflow_dispatch` o push a la rama `staging`.
- **Guardas**: el job `deploy` solo corre si existe `RAILWAY_TOKEN`; sin acceso
  no puede desplegar nada.
- **Secrets de GitHub requeridos** (para cuando exista acceso):
  `RAILWAY_TOKEN`, `RAILWAY_SERVICE_NAME`, `RAILWAY_STAGING_DOMAIN`,
  `FEB_SCORE_SMOKE_KEY`.
- **Local**: `RAILWAY_TOKEN=... railway up --service feb-score-api` desde la raíz
  del repo (Railway usa `railway.toml`).

## 7. Health / Readiness

- `GET /health` → liveness (`{"status":"ok"}`). Usada por Docker HEALTHCHECK.
- `GET /ready` → readiness real: conecta a PostgreSQL y comprueba
  `schema_version == 1`; 200 `{"status":"ready"}` o 503 `NOT_READY`.
- Railway: `healthcheckPath = "/ready"`, timeout 300 s. Nota: Railway consulta
  desde el host `healthcheck.railway.app`; la app no filtra por Host, no requiere
  ajuste. Railway **no** monitoriza el healthcheck tras activar el deploy.

## 8. Smoke test

- `bash scripts/staging_smoke.sh <base_url> <api_key>` (sin secretos hardcodeados):
  1. `GET /health` → ok
  2. `GET /ready` → ready
  3. `POST /v1/commands/create_or_update_match` → 200, `status=accepted`, evento `match_upserted`
  4. `GET /v1/matches/<external_id>` → 200
- El workflow de CD lo ejecuta automáticamente con `FEB_SCORE_SMOKE_KEY`.

## 9. Rollback

- Railway conserva el historial de despliegues del servicio; **rollback =
  Redeploy de una versión anterior** (`deploymentRedeploy(id)` vía API GraphQL).
- Cada versión es reproducible desde Git (`vX.Y.Z` → `railway up`).
- Guarda de schema futuro protege el boot si se despliega un binario antiguo
  contra un schema más nuevo.
- **PROBADO con evidencia real (FASE 18.6)**: redeploy del deployment anterior
  (`7dbeda3b` → nuevo `755a4c77`) con `deploymentRedeploy(id)`; verificado
  deployment SUCCESS, `/health` 200, `/ready` 200 (`schema_version=1`,
  `database=ok`, `migrations=up_to_date`), datos intactos (matches de smoke y del
  restore drill → 200) y smoke autenticado PASS. Se restauró después el
  deployment original (`0f0c8310` → `f997d479`, SUCCESS) con el mismo proceso.
- **Nota**: entre ambos deployments el código es idéntico (el commit intermedio fue
  solo docs); la prueba valida el mecanismo de rollback, no un cambio de versiones.

## 10. Backups (estado REAL en Railway, FASE 18.6 + 18.7)

**PITR continuo OPERATIVO** (ejecutado con evidencia real — FASE 18.6):
- `railway postgres pitr enable` → bucket `Postgres-PITR` creado y cableado (región ams;
  S3 `postgres-pitr-kjuqowfazu`). Status: **enabled** / bucket wired: **yes**.
- Postgres recibió las vars `WAL_ARCHIVE_*`; **pgBackRest 2.59.0**: `stanza-create` OK,
  `backup command end: completed successfully` (primer full backup, 50s) con retención
  `--repo1-retention-full=4 --repo1-retention-diff=14` (~4 semanas de ventana), `expire` OK,
  WAL continuo `archive-push command end: completed successfully`. Bucket creciendo en tiempo
  real (6.8 MB / 1.363 objetos; objetos incrementándose con cada WAL).
- **Restore drill REAL ejecutado**: dato de prueba `restore-drill-test-<ts>` creado vía API →
  `railway postgres pitr restore --service Postgres --at <now> --new-service-name feb-restore-drill`
  → servicio temporal **Online** en 39s (RTO observado) → validado: `schema_version=1`,
  12 tablas, `domain_events`, el dato de prueba presente con su evento, `restore-comp`/`SCHEDULED`.
  Servicio temporal **borrado** después (cleanup).

**Backup lógico offsite REAL** (FASE 18.7):
- `pg_dump -Fc` desde cliente PostgreSQL 18.4 (Homebrew) vía túnel SSH
  (`railway connect Postgres --tunnel-only --ssh -P 15432`) → `railway/db railway`.
- Upload a bucket Railway S3-compatible `feb-score-dumps` (`feb_score_<ts>.dump`, 18.5 KiB).
- **INTEGRIDAD verificada**: SHA-256 `30e020fb2c8d8001f138c1ae622a55083803331418d4f785d3759363755d9eb9`, idéntico tras
  download de vuelta del bucket (`cmp` IDENTICAL). 12 tablas + `schema_version=1` + `domain_events`.
- **Restore lógico REAL**: `pg_restore` a base temporal `feb_restore_test` (isla, no toca db staging) →
  `schema_version=1`, 12 tablas, `domain_events=4`, datos conocidos presentes; RTO observado 6s. DB borrada tras validar; db staging `railway` intacta (4 matches, datos conocidos).
- **Limitación real (grant OAuth)**: `pitr backup create` (on-demand) y `pitr schedule set --daily`
  fallan con `OAUTH_INSUFFICIENT_GRANT` incluso tras re-login. El PITR continuo SÍ opera.
  Pendiente: on-demand/schedule via Dashboard o credencial con más grants; y cron `pg_dump`
  lógico diario a un bucket *externo* (ninguna credential S3 externa real disponible → bloqueado).

## 11. Seguridad

- HTTPS: edge de Railway (automático). HSTS: no configurable en el edge → pendiente
  (LOW, F-2/F-6 de FASE 17; si se exige, CDN/proxy delante).
- PostgreSQL no público: sin TCP proxy público ni dominio público; acceso exclusivo vía
  túnel SSH (`railway connect --ssh`) o desde la app por referencia interna.
- Secrets fuera de Git: verificado (`git grep` limpio de staging secrets; `.env` ignorado;
  placeholders de CI como `ci-password`/`ci-key` son para tests, no staging).
- Contenedor no-root (`USER feb` en Dockerfile, uid 1000).
- `/docs` (Swagger) expuesto: **decisión de staging** (público, como documentado en FASE 17).
- Rate limiting activo: in-memory, 1 réplica (`FEB_SCORE_RATE_LIMIT=true`, 120/min).
- **Rotación de API key REAL (FASE 18.7)**: nueva key generada con `openssl rand -hex 32` y
  aplicada a `FEB_SCORE_API_KEYS` (rol `smoke:admin`); deployment `c72440b9` SUCCESS;
  nueva key → smoke OK, key anterior → **401**. Key persistida en `/tmp/feb_smoke_key` (0600).

## 12. Troubleshooting

- `/ready` nunca 200 tras deploy → revisar `FEB_SCORE_DATABASE_URL` (referencia
  correcta), credenciales, y que la migración haya corrido (`schema_version=1`).
- Healthcheck falla con `service unavailable` → confirmar que la app escucha en
  `${{PORT}}` (FEB_SCORE_PORT no debe estar fijo a un valor distinto) y que
  `/ready` responde 200 en la ruta correcta.
- Boot falla por schema futuro → binario más antiguo que la base; volver a
  desplegar la versión correcta (`/ready` y guarda en `connection.py`).
- Smoke `create_or_update_match` devuelve 401 → `FEB_SCORE_API_KEYS` no incluye
  la clave de smoke o el rol es insuficiente para el comando.
- Logs: `railway logs` (API) y pestaña Deployments del servicio.

## 13. Checklist de provisión (FASE 18.7 — todos los ítems reales)

API desplegada · PostgreSQL accesible · migrations ejecutadas · /health OK ·
/ready OK · schema_version=1 · TLS funcionando · API key en secret ·
DATABASE_URL en secret · smoke test real (accepted + match_upserted) · logs
accesibles · container restart policy `ALWAYS` · rollback probado (18.6) ·
backup/PITR generado (18.6/18.7) · restore probado (PITR 39s + lógico 6s) ·
API key rotada (new PASS / old 401) · documentación del entorno.

> Hecho en 18.5/18.6/18.7: todo lo anterior salvo "container restart probado" (no
> necesario: `restartPolicyType=ALWAYS` y sin restarts observados) y la capa
> `pg_dump` lógico **diaria a un bucket externo** (pendiente: backup on-demand/schedule
> vía CLI bloqueado por `OAUTH_INSUFFICIENT_GRANT`; el PITR continuo + pg_dump offsite
> en bucket Railway están operativos).