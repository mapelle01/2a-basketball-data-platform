# FASE 15 — Despliegue de producción y readiness operacional

**Estado inicial: READY — PRODUCTION CANDIDATE** — fecha: 2026-08-13
**Estado final: READY — PRODUCTION CANDIDATE (CI GitHub Actions VERDE)** — fecha: 2026-08-13

Resumen ejecutivo: verificación operacional **real** (proceso uvicorn real +
PostgreSQL real + HTTP real sobre TCP) de todos los aspectos del despliegue:
bootstrap desde cero, migraciones, `/health` + `/ready`, fail-fast de
configuración, E2E de los comandos, outbox supervivencia a crash,
apagado graceful (SIGTERM), seguridad del despliegue, observabilidad, carga y
concurrencia multi-replica. **50/50 checks del audit operacional PASS**
(`/tmp/feb_audit/f15_operational.py`). Se encontraron y corrigieron hallazgos
LOW dentro del alcance de esta fase. **Docker NO está disponible en este
entorno** (verificado: docker, docker-compose, podman, colima, nerdctl ausentes),
pero la condición externa quedó **RESUELTA** en GitHub Actions: el pipeline CI
(`.github/workflows/ci.yml`) ejecutó el `docker build` + compose + smoke **real**
y pasó **VERDE** (jobs `tests` y `docker` ✓). Regresión final del suite:
**473 tests, 0 FAIL / 0 XFAIL / 0 SKIP**, `pip check` limpio.

---

## Tabla de hallazgos

| ID | Severidad | Hallazgo | Evidencia | Fix | Estado |
|---|---|---|---|---|---|
| D-01 | LOW | `docker-compose.yml` permitía arrancar sin `POSTGRES_PASSWORD` (default `change-me`); `FEB_SCORE_API_KEYS` ya era requerida | §1 (auditoría de artefactos de despliegue) | `POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env (no default)` (fail-closed, coherente con la política de keys); `.env.example` + `test_deployment_artifacts.py` | **CORREGIDO** |
| D-02 | LOW | `config.py:84` leía y casteaba `FEB_SCORE_RATE_LIMIT_PER_MINUTE` **en tiempo de definición de clase** (`int(os.environ.get(...))`) → `ValueError` desnudo en import, sin nombre de variable; `server.py` hacía lo mismo con `FEB_SCORE_PORT` | §4 del audit (subproceso con `FEB_SCORE_RATE_LIMIT_PER_MINUTE=abc` → `ValueError: invalid literal` en import) | default estático + parseo perezoso vía `_env_int` en `settings_from_env`; `_port()` en `server.py`; ambos levantan `ConfigurationError` con el nombre de la variable en boot | **CORREGIDO** |
| D-03 | INFO | `ApiKeyAuthenticationProvider.from_env` se construye después de conectar+migrar la BD → con BD caída, un rol de key inválido queda enmascarado por el error de BD (fail-fast sigue ocurriendo en boot, nunca en tráfico) | §4 del audit (orden en `server.py`/`build_production_app`) | Documentado (orden de validación) | Documentado, no bloqueante |
| D-04 | INFO | Misma verificación de imagen Docker/compose `up` real no ejecutable aquí; handlers sincrónicos (psycopg bloqueante) corren en threadpool de Starlette — suficiente para carga de escritor único, cuello a considerar bajo alta concurrencia | §2/§11 del audit (25 concurrentes 200/200, 2 réplicas 200+409) | Pipeline CI (Docker) + documentación | **RESUELTO vía CI (verde)** |
| D-05 | HIGH | La imagen Docker **no incluía los contratos JSON-Schema** (`contracts/`): `load_schema` resuelve `CONTRACTS_ROOT = parents[3]/contracts` → `/app/contracts`, pero el Dockerfile solo copiaba `src/` → **todo comando devolvía HTTP 500** (`FileNotFoundError: /app/contracts/commands/create_or_update_match.v1.json`) en el contenedor | CI job `docker`, smoke del POST (500 + traceback en logs del contenedor) | `COPY contracts ./contracts` en el Dockerfile | **CORREGIDO y VERDE** |
| D-06 | LOW | Smoke del CI: `grep '"status": "ready"'` / `'"status": "accepted"'` no matcheaba el JSON compacto (`"status":"ready"`, sin espacio tras `:`) → el wait de readiness agotaba los 120s y el POST correcto fallaba el grep; indentación YAML rota en un edit | CI job `docker` | patrón `'"status": *"ready"'` / `'"status": *"accepted"'`; POST con `-w` + `tee` para exponer body y HTTP code; paso `Container diagnostics` con logs en fallo | **CORREGIDO y VERDE** |

---

## 1. Auditoría de artefactos de despliegue (estática)

Revisión de `Dockerfile`, `docker-compose.yml`, `.env.example`, `requirements.txt`,
`config.py`, `server.py`, `main.py`, `wiring.py`, `connection.py`, migraciones,
middleware y logging. Sin CI previo (no existe `.github/`). Dockerfile: multi-stage
`python:3.11-slim`, `USER feb` (uid 1000), `HEALTHCHECK` sobre `/health`,
`PYTHONPATH=/app/src`, `ENTRYPOINT python -m feb_score.server`, `EXPOSE 8000`.

Guards estáticos sin Docker (`tests/production/test_deployment_artifacts.py`,
5 tests, **PASS**): sin credencial por defecto conocida en compose, keys de API
requeridas, sin secretos en archivos de despliegue, Dockerfile no-root con
HEALTHCHECK + server, contrato de env de compose coherente con
`settings_from_env()`.

## 2. Docker

**No disponible** en este entorno (verificado: `docker`, `docker-compose`,
`podman`, `colima`, `nerdctl` → command not found). No se simula evidencia.
Condición externa: `.github/workflows/ci.yml` (job `docker`) ejecuta
`docker build` + fail-closed de `docker compose config` sin `.env` (debe fallar) y
con `.env` (debe validar) + `compose up` con smoke de `/health`, `/ready` y un
comando real. Reproducible localmente con `scripts/ci.sh`.

## 3. Bootstrap y migraciones (real, proceso uvicorn)

**PASS (11 checks)**: arranque desde esquema vacío → migrate crea
`matches`, `domain_events`, `schema_version`, `correction_proposals`; `/ready`
reporta `schema_version=1`, `database=ok`, `migrations=up_to_date`; reinicio con
migrate idempotente (sigue en v1); esquema con versión futura (999) → el proceso
**rehúsa arrancar** (`InfrastructureError`, exit != 0) — fail-closed.

## 4. Configuración fail-fast (real, subproceso)

**PASS (8 checks)**: production sin `FEB_SCORE_DATABASE_URL` /
`FEB_SCORE_API_KEYS` → `ConfigurationError` con nombre; `FEB_SCORE_ENV` inválido;
`FEB_SCORE_RATE_LIMIT_PER_MINUTE=abc` y `FEB_SCORE_PORT=abc` → `ConfigurationError`
**nombrando la variable** (fix D-02); rol de API key inválido → `ValueError` en
boot; los fallos **no filtran** el password del DSN ni las claves.

## 5. E2E real (HTTP → auth → gateway → dominio → outbox)

**PASS (14 checks)**: `create_or_update_match` → `match_upserted` (200), lectura
`SCHEDULED` v1, evento persistido y `delivered=1` (dispatch inline);
`finalize_match` sobre agregado ready → `match_validation_started` +
`match_validated` + `match_finalized`, lectura `FINALIZED` v2, los 3 eventos
entregados; **replay con el mismo `command_id` → `events:[]` sin duplicados**;
estado sobrevive a reinicio del proceso.

## 6. Outbox: supervivencia a crash antes del dispatch

**PASS (4 checks)**: se inserta un evento pendiente (simula commit-then-crash) →
un comando posterior dispara el dispatcher → el evento huérfano queda
`delivered=1`; cola de pendientes vuelve a 0.

## 7. Backup / restore / RPO / RTO

Sin implementación nueva (fuera de alcance): se reutiliza la evidencia y las
pruebas existentes de FASE 13 (`tests/production/test_prod_backup_restore.py`),
que verifican dump/restore del esquema de eventos con reconciliación. RPO/RTO
dependen del S3 del cliente (fecha/abastecedor externo); se documenta como deuda.

## 8. Apagado graceful (SIGTERM, proceso real)

**PASS (7 checks)**: SIGTERM → logs de apagado graceful ("Application shutdown
complete", "Finished server process"), **sin traceback**, **0 conexiones
restantes** en `pg_stat_activity` (la app no mantiene pools ni workers; cada
conexión se cierra en `finally`); SIGTERM con request en vuelo → request completa
(200) o cierre limpio, sin crash. Nota: uvicorn termina con el código de la señal
(rc=-15), comportamiento estándar (143 en Docker) tras el apagado ordenado.

## 9. Seguridad del despliegue

**PASS (5 checks de `test_deployment_artifacts.py` + 2 checks de fuga de
secretos)**: no hay credencial por defecto en compose (fix D-01), keys requeridas,
sin secretos en el repo, boot con error no filtra DSN/keys; headers de seguridad
en todas las respuestas (X-Content-Type-Options, X-Frame-Options, Cache-Control).

## 10. Observabilidad

Cubierto por tests existentes (`tests/production/test_prod_observability.py`) +
evidencia del audit: logs de request con `request_id`, `http_request` con
duración, `event_published`, `dispatch_failed`, `app_shutdown`.

## 11. Carga y concurrencia multi-replica (real)

**PASS (5 checks)**: **25 comandos concurrentes sobre HTTP → 25/25 200**, 25 filas
persistidas (sin lost updates), conteo de conexiones sano; **2 réplicas sobre el
mismo match** → **200 + 409** (conflicto de versión), **exactamente 1**
`MatchValidated`. Observación (D-04): los handlers son síncronos (psycopg
bloqueante) y corren en el threadpool de Starlette; suficiente para carga de
escritor único, a reconsiderar con store compartido / async si la concurrencia
crece. (Durante la depuración del audit se detectó que un pipe de logs sin drenar
bloquea uvicorn — comportamiento estándar de logging síncrono; en Docker el
logging driver drena stdout/stderr.)

## 12. CI pipeline (reproducible)

- `.github/workflows/ci.yml`: job `test` (instala, `pip check`, suite completa con
  servicio PostgreSQL, guard de 0 FAIL/XFAIL/SKIP) + job `docker` (build +
  fail-closed de compose + `up` con smoke real).
- `scripts/ci.sh`: pipeline local reproducible (instalación, `pip check`, guards de
  despliegue, suite completa).
- **Ejecución del CI en este entorno** (2026-08-13):
  - `bash scripts/ci.sh` → **OK**: `pip check` limpio, guards de despliegue 6/6,
    suite completa **473 passed**.
  - Job `docker` ejecutado en modo estático (Docker ausente):
    `/tmp/feb_audit/f15_docker_static.py` → **18/18 PASS** replicando las
    aserciones del workflow (Dockerfile: base, no-root uid 1000, HEALTHCHECK
    `/health`, ENTRYPOINT `feb_score.server`, EXPOSE 8000; compose sin `.env` →
    falla fail-closed con mensaje claro; compose con contrato → valida, `api`
    depende de `db` healthy, secrets embebidos correctamente). Esto **no
    sustituye** el `docker build`/`compose up` real.
- **Ejecución real en GitHub Actions** (repo `espanadeantes/feb-score`, rama
  `main`, 2026-08-13) — **VERDE**:
  - Job `tests (Python 3.11)`: **✓** — 473 tests, 0 FAIL (incluido el round-trip
    de backup PG, ver §7).
  - Job `docker image + compose (external condition)`: **✓** — `docker build` OK,
    fail-closed de compose OK, `compose up` con smoke real: `/health` y `/ready`
    → 200, POST `create_or_update_match` → `HTTP 200`
    `{"status":"accepted","events":[{"event_type":"match_upserted"}]}`.
  - Hallazgos del propio CI (corregidos, D-05/D-06): los contratos no viajaban en
    la imagen (500 en comandos) y el smoke usaba grep con espacio que no matcheaba
    el JSON compacto.

## 13. Suite final

**473 passed, 0 FAIL / 0 XFAIL / 0 SKIP** (`.venv/bin/python -m pytest -q`;
464 de cierre de FASE 14 + 9 nuevos de esta fase: 2 de config, 1 de rollback de
migración PG, 5 de artefactos de despliegue, 1 de guard de import). `pip check`
limpio.

---

## Deuda restante (no bloqueante)

- **Backup/restore operativo real con S3** del cliente (RPO/RTO) — externo.
- **Observación D-03**: rol de key inválido se valida tras conectar la BD.
- **Observación D-04**: modelo sync (threadpool) — revisar bajo alta concurrencia.

## Decisión final

**READY — PRODUCTION CANDIDATE (CI GitHub Actions VERDE).**
Todo lo verificable localmente (bootstrap, migraciones, configuración, E2E real,
outbox/crash, apagado graceful, seguridad, observabilidad, carga, concurrencia)
pasa con evidencia ejecutable (50/50) y sin regresiones (473/473). Los hallazgos
LOW detectados se corrigieron con test reproducible. La condición externa de
verificación real de Docker/Compose quedó **RESUELTA**: el pipeline CI en GitHub
Actions ejecutó `docker build` + `compose up` + smoke real con **resultado VERDE**
en ambos jobs. No se avanza a FASE 16 sin decisión explícita del cliente.