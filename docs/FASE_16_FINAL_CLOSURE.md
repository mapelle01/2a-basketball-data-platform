# FASE 16 — CIERRE DEFINITIVO DEL PROYECTO

**Fecha:** 2026-08-13
**Repositorio:** `espanadeantes/feb-score` (rama `main`)
**Estado:** **READY — PRODUCTION CANDIDATE**
**CI GitHub Actions:** run `31703771421` → **VERDE** (ambos jobs).

> **Distinción explícita:** este documento declara **READY — PRODUCTION
> CANDIDATE**. **NO declara PRODUCTION DEPLOYED**: no existe evidencia de un
> despliegue real en un entorno de producción del cliente (sin DNS/VPS/secretos
> reales/URL de acceso). Los pasos para llegar a PRODUCTION DEPLOYED se listan
> en §"Pasos necesarios para producción real".

---

## 1. Objetivo del proyecto

Plataforma de datos deportivos (Core Engine) para competiciones de la Federación
Española de Baloncesto: recopilar, normalizar, almacenar y analizar información
oficial (partidos, plantillas, clasificaciones, correcciones, publicaciones),
con arquitectura hexagonal (Domain / Application / API / Infrastructure),
doble backend de persistencia (SQLite para desarrollo/tests, PostgreSQL como
backend de producción), API HTTP versionada con contratos JSON-Schema como
fuente única de verdad, seguridad por API keys con roles (editor/admin/system),
y despliegue contenedorizado (Docker + Compose).

## 2. Estado final

- **READY — PRODUCTION CANDIDATE**, verificado por:
  - Audit operacional FASE 15: **50/50 checks PASS** (proceso uvicorn real +
    PostgreSQL real + HTTP real sobre TCP).
  - Suite completa: **473 tests, 0 FAIL / 0 XFAIL / 0 SKIP**; `pip check` limpio.
  - CI GitHub Actions **VERDE**: `tests (Python 3.11)` y
    `docker image + compose (external condition)`.
  - Auditoría de arquitectura y fronteras (tests de arquitectura, sin
    dependencias de infra en dominio/application).
- No existen fallos reproducibles conocidos del dominio.
- Git: trabajo en `main`, commits empujados, `git status` limpio.

## 3. Arquitectura final

Capas (reglas de dependencia garantizadas por tests de arquitectura):

```
Domain          — lógica de negocio pura, sin dependencias internas.
Application     — importa Domain únicamente; handlers/repositorios = interfaces.
API             — FastAPI /v1; importa Application + Domain + carve-outs de
                  infraestructura (logging, errores de persistencia); nunca
                  repositorios concretos ni sqlite3/psycopg.
Infrastructure  — importa Application + Domain + port api.CommandGateway;
                  única capa que conoce SQLite (sqlite3) y PostgreSQL (psycopg).
```

- Frontera HTTP: `POST /v1/commands/{command_type}`, lecturas
  `GET /v1/{matches|players|teams|competitions|leaderboards|correction-proposals}/{id}`,
  `GET /v1/contracts/{command_type}`, `/health`, `/ready`, OpenAPI (`/docs`).
- Seguridad: autenticación por API key (`Authorization: Bearer`/`X-API-Key`);
  el rol se deriva de la key, nunca del body; AuthZ por comando
  (editor/admin/system). Sin CORS (API servidor-a-servidor).
- Consistencia: cada comando corre en UNA transacción (estado + eventos +
  idempotencia) vía CommandRunner; outbox (persistencia y dispatch separados,
  at-least-once).
- Configuración: fail-fast en boot (`ConfigurationError` con nombre de variable),
  sin credenciales por defecto; Postgres es el único backend de producción.
- Observabilidad: logs estructurados con `request_id`/`command_id`/`event_id`;
  sin secretos en logs.
- Despliegue: Docker multi-stage (`python:3.11-slim`, usuario no-root uid 1000,
  `HEALTHCHECK /health`, `ENTRYPOINT python -m feb_score.server`);
  Compose fail-closed (`POSTGRES_PASSWORD`/`FEB_SCORE_API_KEYS` requeridas).
- Versionado: API `APP_VERSION = 1.0.0` (`/v1`); contratos JSON-Schema
  versionados (`*.v1.json`, `$id` + `meta.version`).

## 4. Cobertura de tests / evidencia

- **473 tests, 0 FAIL / 0 XFAIL / 0 SKIP** (`python -m pytest -q`).
- Desglose por dominio: Domain, Application, Infrastructure, PostgreSQL, API,
  Contracts, Architecture, Production (readiness, observabilidad, rate limiting,
  shutdown graceful, despliegue, backup/restore).
- Audit operacional FASE 15: **50/50** (bootstrap, migraciones, `/health` +
  `/ready`, fail-fast de config, E2E real, outbox crash, SIGTERM, seguridad,
  observabilidad, carga 25 concurrentes 25/25, 2 réplicas 200+409).
- `pip check` limpio (sin dependencias rotas).

## 5. CI

- `.github/workflows/ci.yml`:
  - `tests (Python 3.11)` — instala deps, `pip check`, suite completa con
    servicio `postgres:16-alpine` (puerto 5433) y guard de 0 FAIL/XFAIL/SKIP.
  - `docker image + compose (external condition)` — `docker build`, fail-closed
    de `compose config` sin `.env` (debe fallar) y con `.env` (debe validar),
    `compose up` + smoke real (`/health`, `/ready`, POST comando real).
- Resultado: run `31703771421` **VERDE** (tests 1m11s; docker 49s).
- `scripts/ci.sh`: pipeline local reproducible (instalación, `pip check`, guards
  de despliegue, suite completa).

## 6. Docker

- Imagen `python:3.11-slim`, multi-stage, usuario no-root (`feb`, uid 1000),
  `PYTHONPATH=/app/src`, `HEALTHCHECK /health`, `EXPOSE 8000`.
- **Corrección D-05**: `COPY contracts ./contracts` — la imagen incluye los
  contratos JSON-Schema (`/app/contracts`), requisito de `load_schema`
  (`CONTRACTS_ROOT = parents[3]/contracts`).
- `docker-compose.yml`: servicio `db` (postgres:16-alpine) + `api` con
  healthcheck de dependencia; variables requeridas con `:?` (fail-closed).
- Smoke real en CI: POST `create_or_update_match` → `HTTP 200`,
  `{"status":"accepted","events":[{"event_type":"match_upserted"}]}`.

## 7. PostgreSQL

- Backend de producción (`FEB_SCORE_DATABASE_URL`); migraciones versionadas
  (`schema_version`, migraciones pendientes/futuras → `/ready` 503).
- Conectado a servicio real en CI y al servidor de tests (dsn
  `postgresql://postgres@127.0.0.1:5433/feb_test`).
- `/ready` reporta `schema_version=1, database=ok, migrations=up_to_date`.

## 8. Backup / restore

- `tests/production/test_prod_backup_restore.py`: round-trip SQLite y
  PostgreSQL real.
  - PG: `pg_dump`/`psql` sobre esquema dinámico (`prod_<hex>`): dump plain
    schema-scoped → `DROP SCHEMA CASCADE` → restore → relectura del agregado.
  - **Corrección (CI)**: los argumentos de `pg_dump`/`psql` se derivan del DSN
    (`FEB_SCORE_PG_DSN`) y la password se propaga con `PGPASSWORD` — el
    contenedor CI (`postgres:16-alpine`, SCRAM) exige auth; antes el test
    hardcodeaba `-h 127.0.0.1 -p 5433 -U postgres -d feb_test` sin password y
    `pg_dump` fallaba (`fe_sendauth: no password supplied`).
- Verificado **PASS** en CI (job `tests`).

## 9. Contratos

- `contracts/commands/*.v1.json` (10 comandos) y `contracts/events/*.v1.json`
  (18 eventos), JSON Schema Draft 2020-12, autocontenidos, versionados en
  `$id`/`meta.version`.
- Son la fuente única de verdad de validación de payloads; servidos en
  `GET /v1/contracts/{command_type}`.
- `contract_matrix.md`, `contract_versioning.md`, `validation_examples/`:
  diseño + ejemplos válidos/inválidos.

## 10. Correcciones críticas realizadas

| ID | Severidad | Problema | Fix |
|---|---|---|---|
| D-05 | HIGH | La imagen Docker no incluía `contracts/` → todo comando HTTP 500 en el contenedor (`FileNotFoundError: /app/contracts/commands/*.v1.json`) | `COPY contracts ./contracts` (Dockerfile) |
| D-06 | LOW | Smoke CI: `grep '"status": "ready"'` no matcheaba el JSON compacto (`"status":"ready"`); el wait agotaba 120s y enmascaraba el error real | `grep '"status": *"ready"'` / `'"status": *"accepted"'`; POST con `-w`+`tee`; paso `Container diagnostics` en fallo |
| — | LOW | Test PG backup: `pg_dump`/`psql` sin password contra servidor SCRAM (CI) → exit 1 | Conectividad derivada del DSN + `PGPASSWORD`; `_run()` expone stderr real |
| D-01/D-02 | LOW | Compose sin password por defecto; `FEB_SCORE_PORT`/`RATE_LIMIT_PER_MINUTE` casteo en import | `:?` fail-closed; parseo perezoso + `ConfigurationError` (FASE 15) |
| F-01/F-04 | LOW/HIGH | (FASE 14) modelado de roles AuthZ; dispatch_failed sin registrar | roles `role_meets`; `dispatch_failed` con `event_id`/`error` |

## 11. Deuda técnica conocida

- **D-03** (EXTERNA/observación): `ApiKeyAuthenticationProvider.from_env` se
  construye tras conectar+migrar la BD; con BD caída, una key inválida queda
  enmascarada por el error de BD (el fail-fast de boot sigue ocurriendo). No
  requiere cambio de código para el cierre.
- **D-04** (EXTERNA/futura): handlers sincrónicos (psycopg bloqueante) en
  threadpool de Starlette y rate limiter en memoria por proceso — suficiente
  para carga de escritor único y 1 réplica; revisar/reescalar bajo concurrencia
  medida y flotas multi-instancia.
- **Idempotencia parcial** (FUTURA): `register_player_to_squad`,
  `create_publication` y `backfill_season` no usan `IdempotencyRepository`
  (documentado en `ARCHITECTURE.md` §11). No bloquea el cierre.

## 12. Deuda externa

- **Backup/restore operativo real con S3 del cliente (RPO/RTO)**: requiere
  credenciales y entorno del cliente; sin cambios de código para el cierre.
- **Broker real** (Kafka/RabbitMQ) en sustitución del outbox-lite: cuando exista
  un consumidor real (el `EventPublisher`/`Logger` son el seam de intercambio).
- **OAuth/SSO** en sustitución de API keys: el ABC `AuthenticationProvider` es
  el seam.
- **Store compartido para rate limiting** si la flota escala a >1 instancia.

## 13. Riesgos residuales

1. **No hay despliegue real**: el sistema está verificado en CI (contenedor) y
   local, no en infraestructura del cliente (DNS, TLS, secretos, entorno).
2. **Rate limiting single-process**: protegerse de abuse requiere store
   compartido si se escala horizontalmente (D-04).
3. **Outbox-lite (sin broker)**: la entrega a consumidores externos reales
   requiere conector Kafka/RabbitMQ (el outbox persiste y reintenta; no hay
   pérdida).
4. **RPO/RTO**: no verificados contra el SLA real del cliente (depende de la
   operativa S3 de backup).
5. **Contratos `$id` con dominio `example.com`**: los `$id` de los contratos
   usan un dominio de ejemplo; en producción real deben apuntar a la URL
   canónica (no afecta validación).

## 14. Pasos necesarios para producción real (PRODUCTION DEPLOYED)

1. Entorno con Docker real del cliente (VPS/cluster) y secretos:
   `FEB_SCORE_DATABASE_URL`, `POSTGRES_PASSWORD`, `FEB_SCORE_API_KEYS` desde un
   gestor de secretos.
2. Proveer PostgreSQL gestionado o contenedor con volumen persistente y
   política de backup S3 (RPO/RTO del cliente).
3. Terminar TLS en el proxy (HTTPS), DNS y puerta de red (la API no termina TLS
   por sí misma; documentado sin CORS por diseño).
4. Ejecutar `docker compose up -d --build` y validar `/health` + `/ready` +
   un comando real (smoke del CI).
5. Establecer monitoreo/alerta sobre los logs estructurados
   (`http_request`, `command_failed`, `dispatch_failed`).
6. Mantener la cadena CI/CD: el pipeline actual (`.github/workflows/ci.yml`) es
   el gate de cada cambio.

## 15. Criterio explícito de cierre

- Suite completa **473/473 PASS**, 0 FAIL/XFAIL/SKIP.
- CI GitHub Actions **VERDE** en ambos jobs (tests + docker).
- Docker/compose validados con smoke real (build, fail-closed, up, comando).
- PostgreSQL y backup/restore **PASS** (incluido round-trip PG en CI).
- Contratos y arquitectura documentados y coherentes con el código.
- No existen fallos reproducibles conocidos; deuda restante solo externa/futura.
- `git status` limpio, todo empujado a `main`, tag `v1.0.0`.

Cumplido → **FASE 16 COMPLETADA — FEB-SCORE READY FOR PRODUCTION CANDIDATE**.

---

## Checklist final (cerrado)

- [x] Domain — lógica pura, sin dependencias; tests de arquitectura
- [x] Application — handlers/interfaces; no importa infraestructura
- [x] Infrastructure — SQLite + PostgreSQL + outbox + logging + wiring
- [x] PostgreSQL — backend producción, migraciones, round-trip backup/restore PASS
- [x] API — FastAPI /v1, authN/authZ, /health, /ready, contratos, OpenAPI
- [x] Contracts — 10 commands + 18 events JSON-Schema v1, fuente única de verdad
- [x] Tests — 473/473 PASS, 0 FAIL/XFAIL/SKIP, pip check limpio
- [x] Architecture — fronteras garantizadas por tests; docs coherentes
- [x] Docker — imagen multi-stage no-root + contracts; build PASS en CI
- [x] CI — GitHub Actions VERDE (tests + docker); scripts/ci.sh reproducible
- [x] Backup/restore — SQLite + PostgreSQL round-trip PASS (CI incluido)
- [x] Documentation — README, ARCHITECTURE, FASE_13/14/15/16, PROJECT_CONTEXT

### Elementos externos pendientes (no bloqueantes)

- [ ] Despliegue real del cliente (infraestructura, DNS/TLS, secretos)
- [ ] Backup/restore operativo S3 con RPO/RTO del cliente
- [ ] Broker real (Kafka/RabbitMQ) para consumidores externos
- [ ] OAuth/SSO y store compartido de rate limiting si escala a flota