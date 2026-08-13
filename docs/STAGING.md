# STAGING — FEB-SCORE v1.0.0 en Railway

> Estado: **PREPARADO (código/documentación) — NO provisionado ni desplegado.**
> FASE 18.1 terminó BLOCKED por falta de acceso a Railway. Este documento es el
> runbook que se ejecutará cuando exista acceso real. Nada aquí sustituye a la
> evidencia real de un despliegue verificado.
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
PostgreSQL 16 gestionado (privado, DATABASE_URL por referencia)
   ↓
Backups: volumen Railway + pg_dump lógico (S3/bucket) + PITR (opcional)
Secrets: FEB_SCORE_DATABASE_URL, FEB_SCORE_API_KEYS (variables Railway)
Monitoring: logs + /health + /ready + restart ALWAYS
```

- **API**: Railway build desde `Dockerfile` (decision: no GHCR; el Dockerfile es
  el artefacto reproducible y Railway conserva el historial de deploys para
  rollback). Config en `railway.toml`.
- **PostgreSQL**: servicio Railway Postgres 16, privado. `DATABASE_URL` como
  variable-referencia `${{DATABASE_URL}}` del servicio PG (red interna).
- **Tráfico**: HTTPS en el edge de Railway; HSTS no es configurable en el edge
  de Railway (limitación documentada; si se exige HSTS, anteponer CDN/proxy).
- **Secrets**: variables de servicio en Railway (nunca en Git; `.env` ignorado).
- **Readiness**: `railway.toml` → `healthcheckPath = "/ready"`; `/health` es la
  sonda liveness (Docker HEALTHCHECK). Railway solo consulta el healthcheck al
  activar un deploy (no monitoreo continuo).

## 3. Servicios y variables

| Servicio | Tipo | Detalle |
|---|---|---|
| `feb-score-api` | Deploy from Dockerfile | 1 réplica, puerto `${{PORT}}` (Railway inyecta `PORT`; `server.py` lo lee, `FEB_SCORE_PORT` gana) |
| `postgres` | Railway Postgres 16 | privado, sin TCP proxy público |

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

- Versión 16 (coherente con CI y `docker-compose.yml`).
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
  Redeploy de una versión anterior** (dashboard o `railway redeploy <deployment_id>`).
- Cada versión es reproducible desde Git (`vX.Y.Z` → `railway up`).
- Guarda de schema futuro protege el boot si se despliega un binario antiguo
  contra un schema más nuevo.
- **Probar en staging** (checklist): desplegar vN+1 y volver a vN verificando
  `/ready` y datos intactos.

## 10. Backups (estado real de Railway, verificado en docs)

Railway Postgres ofrece (documentado oficialmente):
- **Volume backups** (snapshots): schedules Daily (retención 6 días), Weekly
  (1 mes), Monthly (3 meses) + manuales. Restauran al mismo servicio. **No
  están activos por defecto: hay que habilitarlos.**
- **PITR** (pgBackRest, WAL continuo a bucket): ventana ~4 semanas; restore a
  un servicio hermano nuevo en cualquier timestamp. Se habilita desde la pestaña
  Backups.
- **Dumps lógicos `pg_dump`**: la única capa portable y que sobrevive a borrar
  el proyecto; recomendado un cron service que suba el dump a un bucket
  (S3-compatible) → offsite.

Plan para staging (provisional, a ejecutar al provisionar):
- Habilitar volume backup **Daily** (retención 6 días) + **Weekly** (1 mes).
- Cron `pg_dump -Fc` diario a un Railway storage bucket (o S3 externo) cifrado.
- **Restore drill** periódico a base scratch + integrity check (`schema_version`,
  conteos) — **sin esto no hay "backup operativo"**.
- RPO 24h / RTO 4h **provisionales**; marcar en el checklist qué se cumplió
  realmente (PITR reduce RPO a minutos si se habilita).

## 11. Seguridad

- HTTPS: edge de Railway (automático). HSTS: no configurable en el edge → pendiente
  (LOW, F-2/F-6 de FASE 17; si se exige, CDN/proxy delante).
- PostgreSQL no público: desactivar TCP proxy público del template.
- Secrets fuera de Git: verificado (`git grep` limpio; `.env` ignorado;
  placeholders `CHANGE_ME`).
- Contenedor no-root (`USER feb` en Dockerfile).
- `/docs` (Swagger) expuesto: **decisión pendiente** (F-2, LOW) — restringir o
  desactivar en staging es viable solo con cambio de código; no se ha hecho para
  no tocar producción en esta fase.
- Rate limiting: in-memory, 1 réplica → correcto.

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

## 13. Checklist de provisión (para ejecutar con acceso real)

API desplegada · PostgreSQL accesible · migrations ejecutadas · /health OK ·
/ready OK · schema_version=1 · TLS funcionando · API key en secret ·
DATABASE_URL en secret · smoke test real (accepted + match_upserted) · logs
accesibles · container restart probado · rollback probado · backup generado ·
restore probado · documentación del entorno.