# FASE 13 — Informe de preparación para producción

**Estado: LISTO (READY)** — fecha: 2026-08-13

Resumen ejecutivo: el sistema queda preparado para un despliegue real sobre
PostgreSQL + API HTTP. La auditoría confirmó y se corrigió un fallo de seguridad
real (rol del actor confiado al cliente), se añadió autenticación/autorización
basada en credenciales, rate limiting, endurecimiento de configuraciones y
conexiones, guardias de migración, backup/restore, observabilidad con correlación
`request_id`/`command_id`, entrypoint de producción con shutdown controlado, y
una matriz de tests de producción. Regresión final: **447 tests (venv) + 285
tests (python del sistema) = 732, 0 FAIL / 0 XFAIL**.

---

## 1. Resumen de la auditoría previa

Frente a los requisitos de producción, la auditoría encontró:

1. **Fallo de seguridad real**: el `Actor` del envelope y del payload eran
   declarados por el cliente y confiados. `approve_correction` construía
   `approver = Actor(**payload["approved_by"])`, así que un cliente podía enviar
   `role: "admin"` y aprobar correcciones (el dominio exige
   `approver.role == "admin"`).
2. Config sin entorno/log level, sin validación de arranque, sin guardias de
   versión de esquema en `migrate()`.
3. Observabilidad sin correlación de request (sin `request_id`/`command_id`).
4. Sin despliegue reproducible (no existían Dockerfile/compose/.env).
5. Backups de SQLite ya existían; para PostgreSQL había que verificar `pg_dump`.

## 2. Decisión de arquitectura de autenticación

**El cliente jamás declara su rol.** El envelope HTTP ya no lleva `actor`. La
identidad se establece por credencial real (API key) en `api/auth.py`, el rol
pertenece al principal autenticado, y el `Actor` de dominio se deriva de él
(`Principal.to_actor`). Swap posterior a OAuth/SSO vía el ABC
`AuthenticationProvider` sin tocar rutas ni gateway.

## 3. Autenticación (AuthN)

- Todo `POST /v1/commands/{command_type}` exige `Authorization: Bearer <key>` o
  `X-API-Key`. Anónimo → `401 UNAUTHENTICATED`.
- Claves SOLO por entorno: `FEB_SCORE_API_KEYS="key=principal_id:role;..."`.
  Errores de parseo fallan al arrancar (`from_env`), nunca en runtime.
- Lecturas, contratos, `/health`, `/ready`, `/docs`, `/openapi` son públicos por
  diseño (API de servidor a servidor; sin clientes de navegador).

## 4. Autorización (AuthZ)

- Política `COMMAND_ROLES` por comando (rol mínimo). Jerarquía
  `system > admin > editor`:
  - `editor`: create_or_update_match, finalize_match, propose_correction,
    register_player_to_squad, generate_standing_snapshot, generate_leaderboard,
    compute_player_rating.
  - `admin`: approve_correction, create_publication, backfill_season.
- Principal insuficiente → `403 FORBIDDEN` (antes del gateway).
- Comando desconocido → `404` (la autorización nunca lo concede).
- **Fix del fallo auditado**: `propose_correction` / `approve_correction`
  construyen el Actor con `role=command.actor.role` (del principal), conservando
  solo el `id` del payload para la atribución. Un rol falso en el payload no
  escala privilegios (verificado en `tests/api/test_security.py` y
  `tests/production`).

## 5. Rate limiting

- `api/middleware.py::RateLimiter`: ventana fija en memoria (por principal si
  está autenticado, por IP si no) sobre los comandos → `429 RATE_LIMITED` +
  `Retry-After`. Lecturas no limitadas.
- Habilitado por defecto en producción (`FEB_SCORE_RATE_LIMIT`,
  `FEB_SCORE_RATE_LIMIT_PER_MINUTE`, default 120/min).
- Límite documentado: contador de un solo proceso; una flota multi-instancia
  necesita un store compartido (fuera de alcance).

## 6. Configuración y validación

- `Settings` ampliado: `env` (FEB_SCORE_ENV), `log_level` (FEB_SCORE_LOG_LEVEL),
  `api_keys` (FEB_SCORE_API_KEYS), timeouts PostgreSQL, flags de rate limit.
- `Settings.validate()` falla rápido al arrancar: entorno/log level inválidos,
  ints no positivos, y en `production` exige `database_url` + `api_keys`
  (SQLite NUNCA es backend de producción).
- Los errores de config no filtran contraseñas ni claves (test dedicado).

## 7. Endurecimiento de PostgreSQL

- `PgDatabase._connect`: `connect_timeout` y `SET statement_timeout` (una query
  desbocada no retiene lock/conexión indefinidamente). El `search_path` dado en
  el DSN se preserva (se usa `SET`, no el parámetro `options`).
- Sin pool: conexiones de vida corta cerradas en `finally`; escalar por réplicas
  (ver §13).

## 8. Guardias de migración (versión futura)

- `migrate()` (SQLite `PRAGMA user_version` y PostgreSQL `schema_version`)
  rechaza una BD con versión superior al máximo soportado con
  `InfrastructureError`: una BD escrita por una versión NUEVA no se salta ni se
  degrada. Cubierto en `tests/production/test_prod_migration_guards.py`.

## 9. Backup y restore

- SQLite: `backup()`/`restore()` (API online, segura con WAL) probados en round
  trip real.
- PostgreSQL: smoke test real con `pg_dump` (plain, scoped por esquema) + `psql`
  → se destruye el esquema y se restaura, verificado leyendo el match
  (`tests/production/test_prod_backup_restore.py`).

## 10. Outbox en producción

- `LoggingPublisher`: en producción los eventos salen del outbox hacia un
  publisher que los registra y marca entregados tras éxito — se conserva la
  semántica de outbox (entrega solo tras éxito) y el transporte es sustituible.
- El entrypoint conecta `SyncEventDispatcher(db, LoggingPublisher, logger)` al
  gateway; los tests siguen sin dispatcher para conservar los asserts de outbox.

## 11. Observabilidad

- `request_id`: generado/ecogido (`X-Request-ID`), eco en la respuesta, e
  inyectado en cada registro del request (`RequestLogger`).
- Ciclo de vida de comando con `command_id`: `command_started` /
  `command_completed` (events) / `command_failed` / `dispatch_completed`.
- Resumen `http_request` por request (método, path, status, duration_ms) SIN
  body ni credenciales; fallos como `http_request_failed` / rechazos (413/429).
- `gateway_ready` registra el backend en el arranque. Verificado que las claves
  y la ruta de la BD nunca aparecen en logs.

## 12. Health vs Readiness

- `/health` = liveness (proceso vivo). `/ready` = readiness: conecta, comprueba
  esquema y compara la versión de migraciones con la esperada.
  - `database: ok`, `migrations: up_to_date` → 200 `ready`.
  - migraciones pendientes (`< esperada`) → 503.
  - esquema futuro/desconocido (`> esperada`) → 503.
  - BD no alcanzable → 503 (`database: error: ...`, sin detalles internos).
  - `/ready` es no destructivo y no autenticado.

## 13. Despliegue

- Entrypoint `feb_score/server.py` (composition root): env → `validate()` → BD →
  `migrate()` → gateway (con dispatcher de producción) → auth → rate limiter →
  app → Uvicorn.
- `Dockerfile` (multi-stage, usuario no-root, healthcheck `/health`),
  `docker-compose.yml` (Postgres 16 + api, healthcheck de dependencia),
  `.env.example` con todos los overrides documentados.
- **Un worker por contenedor** (el dispatcher es síncrono e inline; el rate
  limiter es en memoria): la flota escala por réplicas.

## 14. Shutdown controlado

- `create_app` registra un lifespan que loguea `app_startup`/`app_shutdown`;
  Uvicorn termina requests en vuelo antes de apagarse.
- No hay workers en background ni pool: no puede perderse una transacción ni
  quedar conexiones abiertas. Verificado: tras shutdown la BD sigue usable y los
  datos están intactos (`tests/production/test_prod_shutdown.py`).

## 15. Clasificación de errores

- Envelope estable: `{"error": {code, message, details}, "command_id": ...}`.
- 400 JSON inválido / campo desconocido; 401 no autenticado; 403 rol
  insuficiente; 404 comando/entidad/contrato desconocido; 409 conflicto
  (StaleVersion/Serialization); 413 payload demasiado grande; 422 validación de
  contrato/dominio; 429 rate limit; 503 infraestructura; 500 error inesperado
  (logueado, sin stack al cliente).

## 16. Auditoría de dependencias

- `requirements.txt`: `jsonschema`, `fastapi`, `uvicorn[standard]`,
  `psycopg[binary]`. `requirements-dev.txt`: `pytest`, `hypothesis`, `httpx`.
- Eliminada la duplicación de `jsonschema` en dev (se declara una sola vez como
  runtime); test actualizado para garantizar que no se re-duplique.

## 17. Auditoría de arquitectura

- Carve-out documentado y testeado: `api/auth.py` importa el value object
  `Actor` del dominio (frontera identidad HTTP↔dominio). El resto de reglas se
  mantienen (API sin repositorios/sqlite3/psycopg/agregados; solo Infrastructure
  conoce PostgreSQL). `server.py` es el composition root, fuera de `api/`.

## 18. Matriz de tests de producción

`tests/production/` (36 tests):
config (validación, secretos, parseo de claves), rate limiting (429, por
principal/IP, no limita lecturas, disabled), guardias de migración (sqlite+pg),
readiness (pending/future/unreachable), observabilidad (correlación,
no-secretos, status de errores, backend), backup/restore (sqlite + pg_dump),
shutdown y `build_production_app` (sqlite y postgres real).

## 19. Regresión completa

- venv (suite completa, incl. HTTP + PostgreSQL): **447 passed, 0 failed, 0
  xfail, 0 skipped**.
- python del sistema (sin HTTP/PostgreSQL): **285 passed, 0 failed**.
- Total: 732 tests verdes.

## 20. Decisiones y límites documentados

- Sin pool de conexiones; un worker por contenedor; escalar por réplicas.
- Rate limiter en memoria (no compartido entre instancias).
- Sin CORS: no hay clientes de navegador; añadir solo si aparece uno.
- Idempotencia por `command_id` sigue sin cubrir para
  `register_player_to_squad`, `create_publication`, `backfill_season`
  (límite previo, documentado en ARCHITECTURE.md §10).
- Los handlers de dominio convierten rechazos en eventos; el 422 de `DomainError`
  es defensivo (probado por inyección).

## 21. Verificación final

| Aspecto | Estado |
| --- | --- |
| Seguridad: rol del cliente (fallo auditado) | Corregido + testeado |
| AuthN / AuthZ (401/403) | Implementado + testeado |
| Rate limiting (429) | Implementado + testeado |
| Config validada (production exige DB+keys) | Implementado + testeado |
| Endurecimiento PostgreSQL (timeouts) | Implementado + testeado |
| Guardias de migración (versión futura) | Implementado + testeado |
| Backup/restore (SQLite + pg) | Implementado + testeado |
| Outbox en producción (LoggingPublisher) | Implementado + testeado |
| Observabilidad (request_id/command_id) | Implementado + testeado |
| Health vs Readiness (pending/future) | Implementado + testeado |
| Despliegue (entrypoint/Docker/compose/.env) | Implementado |
| Shutdown controlado | Implementado + testeado |
| Clasificación de errores 401/403/429 | Implementado + testeado |
| Auditoría de dependencias | Completa (jsonschema dedup) |
| Auditoría de arquitectura | Completa (carve-out auth) |
| Matriz de tests de producción | 36 tests |
| Regresión 0 FAIL / 0 XFAIL | 447 venv + 285 system = 732 |
| Documentación | ARCHITECTURE.md actualizado a FASE 13 |

### DECISION: **READY**

feb_score puede desplegarse en producción (PostgreSQL + API HTTP). Los pasos de
despliegue reales y las mejoras futuras están documentados en
`docs/ARCHITECTURE.md` §11 (idempotencia universal, broker real, OAuth/SSO,
rate limiting compartido). No se avanza a FASE 14 automáticamente.
