# FASE 14 — Auditoría de readiness de producción y verificación end-to-end

**Estado inicial: LISTO CON CONDICIONES (READY WITH CONDITIONS)** — fecha: 2026-08-13
**Estado final: READY — PRODUCTION CANDIDATE** — fecha: 2026-08-13 (cierre de condiciones)

Resumen ejecutivo: auditoría completa de producción sobre PostgreSQL real
(HTTP → AuthN → AuthZ → gateway → runner → dominio → repositorio → outbox).
Todas las secciones de verificación pasan con evidencia ejecutable. Se encontró
**un hallazgo HIGH (F-01)** — contradicción entre la política de autorización
`COMMAND_ROLES` y los enums `actor.role` de los JSON-Schemas en 4 comandos — y
**varios hallazgos LOW/informativo (F-02..F-06)**.

**Cierre de condiciones**: F-01 (HIGH) **RESUELTO** con modelo de roles
explícito en el dominio (single source of truth) + contratos alineados, con
pruebas nuevas y verificación E2E sobre PG. F-02 y F-04 (LOW, recomendados)
**IMPLEMENTADOS** con tests. F-05 (Docker) **no verificable** en este entorno
(no hay Docker), documentado con revisión estática y CI como seguimiento.
F-03 y F-06 **documentados como deuda no bloqueante** (sin implementación, por
directiva). Regresión final del suite: **464 tests, 0 FAIL / 0 XFAIL / 0 SKIP**
en el venv del proyecto (447 de la auditoría + 17 nuevos), `pip check` limpio.

---

## Cierre de hallazgos (resumen)

| ID | Severidad | Estado | Evidencia |
|---|---|---|---|
| F-01 | HIGH | **CERRADO** | `test_authz_f01.py` + re-ejecución de `01_e2e.py` (51/51) y `03_authz.py` (0 contradicciones) |
| F-02 | LOW | **CERRADO** | `test_command_lifecycle_records_carry_request_id` (request_id en command/event logs) |
| F-03 | LOW | Documentado (deuda no bloqueante) | §8 de este informe |
| F-04 | LOW | **CERRADO** | `dispatch_failed` + `test_publish_failure_logs_dispatch_failed_*`, `test_corrupt_event_logs_dispatch_failed_*` |
| F-05 | INFO | Documentado (limitación del entorno) | §3 de este informe + revisión estática |
| F-06 | INFO | Documentado (semántica por diseño) | §1 y Hallazgos |

---

## 1. Auditoría E2E — los 10 comandos por el pipeline completo

**51/51 PASS** (`/tmp/feb_audit/01_e2e.py`) sobre esquema PostgreSQL real único
(creado por `migrate()`, eliminado al final). Pipeline real: TestClient → auth →
gateway → `CommandRunner` → handler → dominio → repositorio PG → `domain_events`.

| Comando | Resultado | Verificado |
|---|---|---|
| create_or_update_match | 200 + `match_upserted`; estado SCHEDULED v1 en DB y en lectura | replay mismo `command_id` → 200 + eventos vacíos, sin duplicar fila ni evento |
| finalize_match | 200 + `match_validated`; FINALIZED v3 | evento persistido en outbox |
| propose_correction | 200 + `correction_proposed`; PROPOSED | propuesta visible por lectura |
| approve_correction | 200 + `correction_approved`; APPROVED; match v4 | historial de corrección = 1 |
| register_player_to_squad | 200 + `player_registered` | reflejado en lectura de player |
| compute_player_rating | 200 + `player_rating_computed` | fila en `ratings` |
| generate_standing_snapshot | 200 + `standing_snapshot_generated` | fila en `standing_snapshots` |
| generate_leaderboard | 200 + `leaderboard_generated` | fila en `leaderboards` |
| create_publication | 200 + `publication_created` | fila en `publications` |
| backfill_season | 200 + `season_backfill_started` + `season_backfill_completed` | — |

- **Idempotencia**: mismo `command_id` → 200 + `events: []`, sin duplicar estado ni eventos.
- **Reinicio**: nueva instancia de la app sobre el mismo esquema → replay idempotente, estado intacto.
- **AuthN/AuthZ/errores**: anónimo → 401; editor en `backfill_season` → 403; match inexistente → 404; payload inválido → 422; comando desconocido → 404.
- **Reutilización de `command_id` entre comandos distintos**: devuelve 200 + eventos vacíos (no-op silencioso), ver hallazgo F-06.
- **F-01 (cierre)**: el principal `system` hace `propose_correction` + `approve_correction` con atribución `role=system` → **200**, la propuesta queda **APPROVED** y el match incrementa versión (antes: 422 CONTRACT_VALIDATION).

## 2. Configuración / secretos — PASS

- Sin secretos commiteados: `.env.example` solo placeholders (`CHANGE_ME`); no existe `.env`; credenciales solo por env (`FEB_SCORE_DATABASE_URL`, `FEB_SCORE_API_KEYS`).
- `Settings.validate()` falla en arranque si `production` no define DSN PostgreSQL ni API keys (nunca cae a SQLite en producción).
- Tests que lo blindan: `test_prod_config.py` (los errores de config no imprimen el password de la DSN ni las claves), `test_prod_observability.py` (no hay secretos en logs).

## 3. Docker / despliegue — NO VERIFICABLE (limitación del entorno; F-05)

`docker`, `docker-compose` y `podman` no están instalados en este entorno
(verificado de nuevo en el cierre: `command not found`). **Lo que no se pudo
ejecutar**: `docker build`, `docker compose config`, `docker compose build`,
`docker compose up` + smoke de health/readiness del contenedor sobre
`postgres:16-alpine`. Esto debe verificarse en un entorno con Docker (CI).

Revisión estática del `Dockerfile` y `docker-compose.yml` (correctos sobre papel):
- Multi-stage (builder instala deps; runtime solo app + deps), usuario no-root (`uid 1000`), `HEALTHCHECK` sobre `/health`, `PYTHONPATH=/app/src`, `ENTRYPOINT python -m feb_score.server`.
- Compose: `postgres:16-alpine` + API con healthcheck de dependencia; `FEB_SCORE_ENV=production`; `FEB_SCORE_API_KEYS` obligatoria (`:?`); single worker por diseño (dispatcher inline, rate limiter en memoria) con escala por réplicas.
- **Contrato de entorno verificado estáticamente**: todas las variables que usa `docker-compose.yml` (`FEB_SCORE_DATABASE_URL`, `FEB_SCORE_API_KEYS`, `FEB_SCORE_LOG_LEVEL`, `FEB_SCORE_RATE_LIMIT`, `FEB_SCORE_RATE_LIMIT_PER_MINUTE`) existen y son leídas en `infrastructure/config.py` y consumidas por `server.py` (`build_production_app`), que aplica `migrate()` en el arranque.
- **Acción pendiente (no bloqueante)**: añadir un job de CI que ejecute `docker build` + `docker compose config` (+ up/smoke) para cubrir F-05 de forma automatizada. **RESUELTO en FASE 15**: `.github/workflows/ci.yml` (job `docker`) ejecutado **VERDE** en GitHub Actions — ver `FASE_15_REPORT.md` §12.

## 4. Auditoría de base de datos — concurrencia — PASS

`/tmp/feb_audit/02_db_audit.py` — dos réplicas (conexiones/gateways independientes sobre el mismo esquema) finalizan el mismo match concurrentemente (barrera):

- Un request gana (200), el otro → **409**.
- **Un solo** evento `MatchValidated` persistido (sin duplicados).
- Sin lost update: match FINALIZED, version 2 (la versión exacta del ganador).

## 5. Outbox — casos A–D — PASS

Mismo script, sobre PG real:
- **A**: el evento se persiste atómicamente con el estado (`delivered=false`) en el commit del comando.
- **B**: un publisher que falla en el primer evento deja TODO pendiente (no entrega parcial); el reintento entrega todo, cada evento una vez.
- **C**: re-entrega del mismo evento (at-least-once) → el consumidor `IdempotentConsumer` entrega exactamente una vez.
- **D**: crash antes del dispatch → evento queda pendiente; un proceso nuevo lo entrega y lo marca `delivered`.

## 6. Matriz de autorización — PASS (0/40) — F-01 CERRADO

`/tmp/feb_audit/03_authz.py` — 10 comandos × {anon, editor, admin, system}, 40 combinaciones sobre HTTP:

- **Puerta AuthZ correcta en 40/40**: anónimo → 401 en todos; role insuficiente → 403 en todos (editor en `approve_correction`/`create_publication`/`backfill_season`); roles suficientes pasan. 0 escapes.
- **Contradicciones contrato/AuthZ: 0** (antes del cierre: 4). Los 4 comandos ahora aceptan `system` y los roles válidos del principal:
  - `approve_correction`: `actor.role` y `approved_by.role` → `["admin","editor","system"]`
  - `register_player_to_squad` y `create_publication`: `actor.role` → `["admin","editor","system"]`
  - `backfill_season`: `actor.role` → `["admin","editor","system"]`
  - `propose_correction`: `proposed_by.role` → `["admin","editor","system"]` (misma clase de bug latente: un `system` haciendo propose con atribución `role=system` daba 422)

**Cómo se resolvió F-01 (modelo explícito, sin bypass, fail-closed intacto)**:
1. El **dominio** es ahora la única fuente de verdad del modelo de roles: `ROLE_LEVELS` + `role_meets(role, minimum)` en `domain/value_objects.py` (`system ≥ admin ≥ editor`).
2. `api/auth.py` importa esa jerarquía (carve-out ya documentado por la arquitectura) y elimina su copia duplicada; `is_authorized` usa `role_meets`.
3. El guard del dominio en `CorrectionProposal` (`ensure_can_be_approved_by` / `reject`) pasa de `role == "admin"` a `role_meets(role, "admin")`: aprueba/rechaza todo principal de nivel admin o superior (admin **y** system); un editor sigue rechazado (tests existentes intactos).
4. Los enums de los contratos admiten el conjunto de roles válidos del principal. **No cambió la política de autorización** (`COMMAND_ROLES` sigue siendo la única puerta) y **el rol sigue derivado del principal autenticado** (el envelope con `actor` forjado → 400; claims de rol en el payload se ignoran → 403 si el principal no alcanza).

## 7. Endurecimiento de seguridad — PASS

`/tmp/feb_audit/04_sec_obs_load.py`:
- Headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store`.
- **Sin CORS** (API server-to-server, sin clientes de navegador — decisión documentada).
- `X-Request-ID` eco; envelope con `actor` forjado → **400** (el rol jamás lo declara el cliente).
- Body > 1 MiB → **413**; rate limit → **429 + Retry-After**.
- Lecturas/`/health`/`/ready`/contratos/`/docs` públicos por diseño; comandos autenticados.

## 8. Observabilidad / trazabilidad — PASS (14/14) — F-02 CERRADO

- `http_request` log con `request_id`; `command_started/completed` con `command_id`; `event_published` con `event_id` + `aggregate_id`. Sin secretos en logs (verificado con captura de todos los registros).
- **F-02 resuelto**: el `request_id` activo se publica en un contextvar de la infraestructura (`infrastructure/logging.py`: `set_request_id`/`reset_request_id`/`current_request_id`); el `CommandRunner` y el dispatcher lo etiquetan en `command_started`/`command_completed`/`command_failed`/`dispatch_completed`/`event_published`. La cadena queda completa: **HTTP request → request_id → command_id → command logs → event logs → aggregate**.
- **F-04 resuelto**: cualquier fallo de dispatch (publisher o fila de evento corrupta/no-procesable) se registra como **`dispatch_failed`** de nivel error con `event_id`, `event_type`, `error` (clase), `error_message` y `request_id`; el evento queda **pendiente** (at-least-once) y dispatch se detiene (nunca se salta ni se marca entregado).
- **F-03 (documentado, deuda no bloqueante)**: el rate limiter es en memoria y por réplica. Es correcto para una instancia única (el despliegue recomendado escala por réplicas de un solo worker). Para escala horizontal multi-réplica con límite global por principal, habrá que externalizarlo (Redis/DB). Decidido: **no implementar ahora**; documentar + CI como seguimiento.

## 9. Backup / restore / DR — PASS (RPO/RTO honestos)

`/tmp/feb_audit/05_backup_corrupt.py` — `pg_dump -F c` → restore en **base de datos nueva** → estado/eventos/idempotencia idénticos. Fidelidad total.

**RPO/RTO honestos**: NO hay scheduler de backup ni PITR/WAL configurado en compose. RPO = tiempo transcurrido desde el último `pg_dump` manual; RTO = tiempo de restore (~0.03s medido para 3 matches + 3 eventos + schema). Para producción real es necesario un backup periódico automatizado y definir el objetivo de recovery.

## 10. Integridad de datos / corrupción — PASS (3/3)

Mismo script:
- Evento pendiente corrompido (payload JSON válido pero no-envelope) → `dispatch()` registra **`dispatch_failed`** (error clasificado, con `event_id`/`event_type`) y el evento sigue **pendiente** (nunca se salta en silencio ni se marca entregado). Antes del cierre la excepción se propagaba sin registro (F-04).
- Agregado corrompido (`data` JSON no-envelope) → la lectura lanza **`CorruptedRecordError`** (falla ruidosa, nunca sirve basura).

## 11. Smoke de carga — PASS

30 comandos `create_or_update_match` concurrentes (30 hilos, cada uno con su cliente): **30/30 → 200**, 30 filas en `matches`, sin 409/500. (En cargas mayores en producción considerar el rate limiter por réplica, ver F-03.)

## 12. Auditoría del contrato de API — PASS

- `GET /v1/contracts/{command_type}` sirve el JSON-Schema versionado (v1); `GET /openapi.json`, `/docs`, `/health`, `/ready` responden 200.
- Comando desconocido (POST) → 404; sin `payload` → 400; payload inválido → 422; sobre el límite → 413.
- Semántica de códigos coherente con `api/errors.py` (401/403/404/409/413/422/429).
- Matriz de roles completa en §6 (F-01 cerrado: 0 contradicciones contrato/AuthZ).

## 13. Auditoría de arquitectura — PASS

- `tests/architecture`: **14/14** (límites de capas, imports prohibidos, carve-out documentado de `api/auth.py` → `domain.value_objects`).
- `grep` exhaustivo: **0 imports** de `infrastructure`/`api`/`sqlite3`/`psycopg`/`fastapi` en `domain` y `application`.
- `pkgutil.walk_packages`: **todos los módulos de `feb_score` importan limpiamente** (sin imports circulares); los módulos modificados en el cierre (auth, middleware, application_service, event_dispatcher, logging, value_objects, correction/model, server) importan correctamente.
- Http no conoce PostgreSQL; SQLite y PG implementan la misma interfaz.
- El contextvar de `request_id` vive en `infrastructure/logging.py` (capa de infraestructura): `api` lo usa hacia abajo, sin dependencias hacia arriba.

## 14. Informe del suite de tests

| Ejecución | Resultado |
|---|---|
| venv completa (auditoría original) | **447 passed, 0 failed, 0 xfail, 0 skipped** |
| venv completa (cierre de condiciones) | **464 passed, 0 failed, 0 xfail, 0 skipped** (447 + 17 nuevos: 14 `test_authz_f01` + 2 `test_observability` + 1 `test_prod_observability`) |
| `pip check` | No broken requirements |

- El subconjunto "python del sistema" (285) está **contenido** en el run del venv (447 → 464); en el cierre no se pudo repetir con un intérprete del sistema (ese intérprete con deps ya no está disponible en el entorno), por lo que la cifra autoritativa es el run completo del venv del proyecto.
- El run del cierre se ejecutó con PostgreSQL alcanzable (backend sqlite + postgres del fixture compartido): **0 skips** confirmados.

## 15. Dependencias — PASS

- Runtime (`requirements.txt`): `jsonschema`, `fastapi`, `uvicorn[standard]`, `psycopg[binary]`.
- Dev (`requirements-dev.txt`): `pytest`, `hypothesis`, `httpx` (separado del runtime).
- Todos los imports de terceros en `src` están declarados; `pydantic`/`starlette` son transitivos de fastapi/uvicorn. Sin dependencias muertas.

## 16. Checklist final

| # | Sección | Resultado | Evidencia |
|---|---|---|---|
| 1 | E2E 10 comandos | PASS (**51/51**) | `01_e2e.py` |
| 2 | Config/secretos | PASS | grep + `test_prod_config` |
| 3 | Docker/deploy | **NO VERIFICABLE** (entorno sin Docker; revisión estática + CI pendiente) | inspección estática |
| 4 | Concurrencia 409 | PASS | `02_db_audit.py` |
| 5 | Outbox A–D | PASS (8/8) | `02_db_audit.py` |
| 6 | Matriz AuthZ | PASS (0/40) — **F-01 CERRADO** (0 contradicciones) | `03_authz.py` |
| 7 | Seguridad | PASS (7/7) | `04_sec_obs_load.py` |
| 8 | Observabilidad | PASS (**14/14**) — F-02 CERRADO, F-04 CERRADO, F-03 documentado | `04_sec_obs_load.py` |
| 9 | Backup/DR | PASS + RPO/RTO honesto | `05_backup_corrupt.py` |
| 10 | Corrupción | PASS (3/3) | `05_backup_corrupt.py` |
| 11 | Load smoke | PASS (30/30) | `04_sec_obs_load.py` |
| 12 | Contrato API | PASS | probes §12 |
| 13 | Arquitectura | PASS (14/14 + scan) | `tests/architecture` |
| 14 | Suite de tests | PASS (**464**, 0 FAIL/XFAIL/SKIP) | pytest |
| 15 | Dependencias | PASS | requirements vs imports |

## Hallazgos (estado final)

| ID | Severidad | Descripción | Estado |
|---|---|---|---|
| F-01 | **HIGH** | Contradicción AuthZ vs `actor.role` de los contratos en `approve_correction`, `register_player_to_squad`, `create_publication`, `backfill_season` | **CERRADO**: modelo de roles explícito en el dominio (`ROLE_LEVELS`/`role_meets`), guard de dominio admin-nivel, contratos con conjunto de roles válido, `COMMAND_ROLES` intacto; tests + E2E PG |
| F-02 | LOW | `request_id` no propagado a los logs de comando | **CERRADO**: contextvar en `infrastructure/logging.py`, runner/dispatcher etiquetan todos los records; test de correlación completa |
| F-03 | LOW | Rate limiter en memoria no compartido entre réplicas | Documentado como deuda no bloqueante (correcto single-instance; externalizar con Redis/DB al escalar >1 réplica). No implementado por directiva |
| F-04 | LOW | Excepción de dispatch no registrada como `dispatch_failed` | **CERRADO**: `dispatch_failed` con `event_id`/`event_type`/`error`/`request_id`; evento pendiente (at-least-once); tests de publisher-fallido y fila corrupta |
| F-05 | INFO | Docker/build/compose sin verificar | Documentado: entorno sin Docker (comandos no ejecutables); revisión estática OK (multi-stage, no-root, healthcheck, contrato de env verificado contra `config.py`/`server.py`); pendiente CI con Docker |
| F-06 | INFO | Idempotency key global entre tipos de comando (reuso → 200 + eventos vacíos) | Documentado: semántica global de `command_id` por diseño; no es pérdida de datos |

## 17. Decisión

## **READY — PRODUCTION CANDIDATE**

Todas las condiciones de la auditoría FASE 14 quedaron cerradas o documentadas:

1. **F-01 (HIGH) — RESUELTO**: el principal `system` es ahora un rol válido y
   explícito del modelo, alineado entre dominio, autorización y contratos; la
   automatización (backfill/ingest/publicación/aprobación) funciona sobre PG sin
   falsos 422. Sin escaladas: el rol nunca lo declara el cliente (envelope →
   400; claims en payload → ignoradas, fail-closed). 0 contradicciones
   contrato/AuthZ (matriz 40/40).
2. **F-02 y F-04 (LOW) — IMPLEMENTADOS**: traza completa
   request_id → command_id → command logs → event logs, y `dispatch_failed`
   alertable con el evento pendiente.
3. **F-05 — LIMITACIÓN DEL ENTORNO**: Docker no está disponible aquí; la imagen
   y el compose se revisaron estáticamente (correctos) y su verificación
   ejecutable queda como acción de CI (no bloquea; documentado).
4. **F-03 — DEUDA NO BLOQUEANTE**: rate limiter por réplica es correcto para el
   despliegue objetivo (réplicas de 1 worker); externalizar al escalar >1.
5. **F-06 — DOCUMENTADO**: semántica global de `command_id` (no-op 200 en reuso
   entre tipos) por diseño.

Regresión final: **464 tests, 0 FAIL / 0 XFAIL / 0 SKIP**, PostgreSQL real
(sqlite + postgres), `pip check` limpio, arquitectura 14/14, sin imports
prohibidos, todos los módulos importan limpiamente. Sistema verificado de
extremo a extremo (transaccionalidad, idempotencia, outbox, concurrencia,
seguridad, backup/restore, corrupción, carga).

**Acciones de seguimiento para el despliegue (no bloqueantes)**: job de CI con
Docker (build + compose + smoke), backup periódico automatizado + objetivo de
RPO/RTO, y decidir el alcance de la externalización del rate limiter si se
despliega multi-réplica.
