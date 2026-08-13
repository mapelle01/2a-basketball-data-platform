# Architecture — feb_score

Documento de arquitectura del sistema tal y como está implementado tras FASE 13
(HTTP API + external application boundary + doble backend de persistencia
SQLite/PostgreSQL + seguridad, producción y despliegue). Describe la frontera
real, las garantías de consistencia, la política de configuración, la postura de
seguridad, el despliegue y el plan de evolución.

## 1. Capas y reglas de dependencia

```
Domain          — sin dependencias internas (lógica de negocio pura).
Application     — importa Domain únicamente. Handlers y repositorios son
                  interfaces; NO importan SQLite, PostgreSQL ni infraestructura.
API             — importa Application + Domain + únicamente los carve-outs de
                  infraestructura (logging, excepciones de persistencia).
                  Nunca importa repositorios concretos, sqlite3, psycopg ni
                  agregados.
                  Carve-out FASE 13: api/auth.py importa el value object Actor
                  (dominio) para mapear principal → Actor.
Infrastructure  — importa Application + Domain (+ el port abstracto
                  api.CommandGateway, implementado por wiring.py). Única capa
                  que conoce PostgreSQL (psycopg + persistence/postgres).
```

Garantizado por tests: `tests/architecture/test_domain_purity.py` y
`tests/architecture/test_architecture_boundaries.py`.

Fronteras verificadas:

| Regla | Archivo de test |
| --- | --- |
| Domain no importa fuera de su paquete | `test_architecture_boundaries.py` |
| Application no importa Infrastructure ni `sqlite3` | `test_architecture_boundaries.py` |
| Handlers sin `sqlite3` | `test_architecture_boundaries.py` |
| Infrastructure solo importa Application/Domain/port gateway | `test_architecture_boundaries.py` |
| API no importa infraestructura concreta ni agregados | `test_architecture_boundaries.py` |
| Sin SDKs externos (Kafka/Redis/HTTP-client/cloud) | `test_architecture_boundaries.py`, `test_dependencies.py` |

### 1.1 Frontera HTTP (FASE 11)

```
Cliente HTTP ──> api (FastAPI, /v1) ──> CommandGateway ──> CommandRunner ──> handlers
                                   └──> infra.persistence (SQLite) + event_store
```

* `src/feb_score/api/main.py` define la app: `POST /v1/commands/{command_type}`
  y lecturas mínimas `GET /v1/{matches|players|teams|competitions|leaderboards|
  correction-proposals}/{id}`, `GET /v1/contracts/{command_type}`, `/health`,
  `/ready`, OpenAPI (`/openapi.json`, `/docs`).
* `CommandGateway` (ABC en `api/gateway.py`) es el port que consume la API e
  implementa `SqliteGateway` y `PgGateway` (`infrastructure/wiring.py`, único
  composition root). `build_gateway()` selecciona el backend desde la
  configuración: si `FEB_SCORE_DATABASE_URL` está definido → PostgreSQL, si no →
  SQLite.
* La API NO re-valida payloads: los contratos JSON-Schema versionados siguen
  siendo la única fuente de verdad (validados por `contract_validated`).
* Cada comando corre en UNA transacción (estado + eventos + idempotencia) vía
  CommandRunner. La respuesta nunca marca eventos como entregados (outbox).

### 1.2 Seguridad y autenticación (FASE 13)

Postura de seguridad verificada por tests (`tests/api/test_security.py`,
`tests/production/`):

* **Autenticación**: todo `POST /v1/commands/{command_type}` exige una API key
  (`Authorization: Bearer <key>` o `X-API-Key`). El proveedor
  (`api/auth.py`, `ApiKeyAuthenticationProvider`) se configura SOLO desde el
  entorno (`FEB_SCORE_API_KEYS="key=principal_id:role;..."`), nunca en código.
  Anónimo → `401 UNAUTHENTICATED`.
* **Autorización**: la política `COMMAND_ROLES` asigna a cada comando un rol
  mínimo (`editor` / `admin`); jerarquía `system > admin > editor`. Principal
  insuficiente → `403 FORBIDDEN`. Lecturas, contratos, `/health` y `/ready` son
  públicos por diseño (API de servidor a servidor, sin clientes navegador).
* **El rol NO se confía al cliente** (fix de un fallo real auditado): el envelope
  ya no lleva `actor`; los handlers de propuesta/aprobación de corrección derivan
  el rol exclusivamente del principal autenticado
  (`Actor(id=payload...id, role=command.actor.role)`). Una petición con un rol
  falso en el payload nunca escala privilegios.
* **Rate limiting**: `api/middleware.py` `RateLimiter` (ventana fija en memoria,
  por principal o IP) sobre los comandos → `429 RATE_LIMITED` + `Retry-After`.
  Contador de un solo proceso (documentado): una flota multi-instancia necesita
  un store compartido (fuera de alcance).
* **Cabeceras de seguridad** (cada una con razón documentada en el código):
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Cache-Control: no-store`. **Sin CORS**: la API no tiene clientes de navegador.
* **Limitación de cuerpo** (413), IDs de correlación `X-Request-ID`/`request_id`,
  y los errores NUNCA filtran trazas, SQL, credenciales ni la URL de la BD
  (verificado en `tests/production/test_prod_observability.py`).

### 1.3 Observabilidad (FASE 13)

* `RequestLogger` inyecta `request_id` en cada registro del request;
  `command_id` en el ciclo de vida del comando (`command_started` /
  `command_completed` / `command_failed` / `dispatch_completed`).
* Cada request se registra como `http_request` (método, path, status,
  duration_ms) SIN body ni credenciales.
* `LoggingPublisher` (outbox, FASE 13): en producción, los eventos salen del
  outbox hacia un publisher que los loguea y marca entregados tras éxito — la
  semántica de outbox se conserva y el transporte puede sustituirse después.

## 2. Persistencia SQLite

* **Un comando = una transacción**: `SqliteUnitOfWork` instala una conexión en un
  `ContextVar`; el agregado, sus eventos (outbox) y la idempotencia se escriben en
  la MISMA transacción. Éxito → `COMMIT`; error → `ROLLBACK` completo.
* **Fuente de verdad**: cada tabla guarda columnas clave normalizadas + un blob
  `data` JSON serializado por `application/persistence/serialization.py`. La
  serialización es la única fuente de verdad; las columnas solo dan lookups.
* **Integridad**: migración v2 añade `CHECK (json_valid(data))`, `status IN (...)` y
  `home_team_id <> away_team_id` en `matches`, además de la columna `version`.
* **Foreign keys**: deliberadamente NO declaradas. El dominio trabaja con IDs
  externos que pueden llegar por separado (p. ej. `competition_id` de un partido
  cuyo torneo aún no se ha importado); un FK rompería el flujo collector.

### Concurrencia

* WAL (journal_mode) permite lecturas concurrentes durante escrituras.
* Escritores se serializan con `BEGIN IMMEDIATE` + `busy_timeout`.
* **Concurrencia optimista**: toda mutación de dominio incrementa `version`
  (`upsert`, `finalize`, `apply_correction`). `SqliteMatchRepository.save` solo
  aplica un UPDATE cuando la versión almacenada es exactamente
  `match.version - 1`; si no, lanza `StaleVersionError` y la escritura se
  descarta. Nunca hay "lost update" silencioso.

### Limitación (documentada)

SQLite es **single-writer**. Dos escritores simultáneos sobre el mismo fichero se
serializan; con carga muy alta de escritura es el cuello de botella. Para
escalar escritura se migraría a PostgreSQL (ver §8). Hasta entonces esta
limitación es aceptada y verificada por tests (`tests/sqlite/test_concurrency.py`).

## 2.1 Persistencia PostgreSQL (FASE 12)

Backend alternativo tras las MISMAS interfaces que SQLite: mismo UoW, mismos
repositorios, mismo outbox/dispatcher, mismas garantías. Implementado en
`infrastructure/persistence/postgres/` (psycopg3, única capa que conoce
PostgreSQL; verificado por `tests/architecture/test_architecture_boundaries.py`).

* **Configuración**: `Settings.database_url` (env `FEB_SCORE_DATABASE_URL`). Sin
  credenciales hardcodeadas; `PgDatabase(dsn, schema=...)` inyectable en tests.
* **Conexiones**: `connect()` autocommit (semántica standalone tipo SQLite) y
  `connect_txn()` autocommit=FALSE (transacciones explícitas). Sesión `UTC` +
  `dict_row`.
* **Aislamiento por esquema**: un `PgDatabase` con `schema` fija
  `search_path` (vía `psycopg.sql.Identifier`); los tests usan un esquema único
  por caso. `migrate()` crea el esquema si no existe antes de crear tablas
  (Postgres resuelve los nombres sin calificar al PRIMER esquema existente del
  path).
* **Fuente de verdad**: `data JSONB` (igual que el blob `data` de SQLite),
  columnas clave normalizadas para lookups, CHECKs que reflejan invariantes del
  dominio (`status IN (...)`, `home <> away`).
* **Transacciones**: `PgUnitOfWork` instala la conexión en un `ContextVar`
  (espejo de `SqliteUnitOfWork`): estado + eventos (outbox) + idempotencia
  COMMIT juntos, ROLLBACK completo ante error.
* **Concurrencia optimista**: `PgMatchRepository.save` = `UPDATE ... WHERE
  external_id AND version = match.version - 1`; `rowcount == 0` →
  `StaleVersionError`. `translate_pg_error` mapea `SerializationFailure` (40001)
  y `DeadlockDetected` (40P01) a la taxonomía de infraestructura; el API responde
  409 CONFLICT para ambos (reintentable).
* **Migraciones**: versionadas en `schema_version`, una transacción por
  migración, reproducibles (los SQL idempotentes de la migración inicial).
* **Outbox**: `domain_events.payload JSONB` + `delivered BOOLEAN`,
  `ON CONFLICT DO NOTHING`, `payload::text` para el `reconstruct_event` común.

Diferencia clave: **concurrencia de escritura real**. Bajo READ COMMITTED dos
escritores concurrentes pueden colisionar; la columna `version` + el guard del
UPDATE garantizan que nunca hay "lost update" y que el perdedor recibe
`StaleVersionError`/409 (verificado por la suite de contratos compartida
`tests/postgres/test_contracts_shared.py`, ejecutada contra ambos backends).

## 3. Garantías ante caídas

| Escenario | Estado | Eventos (outbox) | Idempotencia | Recuperación |
| --- | --- | --- | --- | --- |
| Crash ANTES del COMMIT | intacto (rollback) | no hay | no hay | reenviar el comando |
| Crash DESPUÉS del COMMIT, antes del dispatch | persistido | pendientes (delivered=0) | registrada | dispatch en el arranque |
| Crash DURANTE el dispatch (publish ok, mark no) | persistido | redelivery (at-least-once) | registrada | consumer idempotente deduplica |
| Dispatch falla (publish error) | persistido | pendientes | registrada | reintento posterior |

Ver `tests/sqlite/test_data_loss_scenarios.py` y `test_dispatcher_hardening.py`.

## 4. Outbox-lite y dispatch

* Los eventos se persisten en `domain_events` dentro de la transacción del comando.
* `SyncEventDispatcher` publica tras el COMMIT; marca `delivered` SOLO tras éxito.
* At-least-once: un evento puede entregarse dos veces → el consumidor debe ser
  idempotente (`IdempotentConsumer` deduplica por `event_id`).
* Orden estable: `ORDER BY produced_at, event_id`.

## 5. Entrypoint: CommandRunner

`Infrastructure/application_service.py::CommandRunner` es la única frontera para
invocar la lógica desde fuera (CLI/API/worker):

1. Abre UNA transacción (estado + eventos + idempotencia).
2. Registra `command_started` / `command_completed` / `command_failed` con
   metadatos (nombre del comando, nº de eventos, tipo de error).
3. Tras el COMMIT, dispara el dispatch.

## 6. Observabilidad

* `infrastructure/logging.py`: abstracción `Logger` (interfaz para una futura
  plataforma externa), backend `StdLogger` (Python logging, `key=value`) y
  `RecordingLogger` para tests.
* Eventos de log: `command_started`, `command_completed`, `command_failed`,
  `event_published`, `event_publish_failed`, `dispatch_completed`.

## 7. Configuración

* Único parámetro crítico: la ruta de la BD, INYECTADA (`SqliteDatabase(path)`).
* Sin secretos en el código.
* Ajustes de tuning en `infrastructure/config.py::Settings` con override por
  entorno: `FEB_SCORE_DB`, `FEB_SCORE_BUSY_TIMEOUT`, `FEB_SCORE_DISPATCH_BATCH`.
* Timestamps: `datetime.utcnow()` (tz-naive UTC), convención deliberada y única.

## 8. Migraciones y backup

* Migraciones numeradas en `infrastructure/persistence/migrations/` con
  `PRAGMA user_version` (SQLite) / tabla `schema_version` (PostgreSQL): versiones
  estrictamente crecientes, aplicadas una sola vez, cada una en su propia
  transacción (fallo parcial → rollback y versión intacta).
* **Guardia de versión futura (FASE 13)**: `migrate()` rechaza una BD cuya
  versión supera el máximo soportado (`InfrastructureError`) en ambos backends —
  una BD escrita por una versión NUEVA no se salta ni se degrada a ciegas.
* Migraciones destructivas (v2, v3+): backup automático
  `<db>.pre-migrate-<v>.sqlite3` antes de aplicarlas.
* Backup/restore online: `SqliteDatabase.backup()` / `restore()` (API backup de
  SQLite, segura con WAL). Restaura TODO, incluidas `domain_events` pendientes.
  PostgreSQL: `pg_dump`/`psql` probados en `tests/production/test_prod_backup_restore.py`.

## 9. Dependencias

* Runtime: `jsonschema`, `fastapi`, `uvicorn[standard]`, `psycopg[binary]` →
  `requirements.txt`. `jsonschema` se declara UNA sola vez (runtime); no se
  duplica en dev.
* Dev: `pytest`, `hypothesis`, `httpx` → `requirements-dev.txt`.
* Sin brokers ni SDKs cloud (verificado por tests). `httpx` solo en dev
  (cliente de tests); la app no hace llamadas HTTP salientes.

## 10. Deuda técnica / decisiones documentadas

* `CreatePublicationHandler` escribe por INSERT OR REPLACE (replay overwrite,
  no duplica) — desviación documentada del repo in-memory.
* `ratings` no tiene UNIQUE (semántica del repo in-memory preservada; la
  idempotencia la garantiza la tabla `idempotency`).
* Sin FK en SQLite (política de IDs externos, ver §2).
* Timestamps naive-UTC: correcto mientras la fuente sea UTC; revisar si se
  introducen zonas horarias.
* Idempotencia HTTP por `command_id`: los handlers de
  `register_player_to_squad`, `create_publication` y `backfill_season` no tienen
  `IdempotencyRepository` (semántica previa de FASE 10); documentado como límite.
* Los handlers de dominio suelen convertir rechazos en eventos
  (`ValidationFailed`), por lo que el mapeo 422 de `DomainError` es defensivo
  (probado por inyección vía gateway en tests/api).
* **Sin pool de conexiones** (FASE 13): un worker Uvicorn con conexiones
  psycopg de vida corta (cierre en `finally`); escalar por réplicas, no por
  workers en el mismo contenedor. Un pool se añadiría solo ante carga medida.
* **Rate limiter en memoria** (FASE 13): contador de un solo proceso; una flota
  multi-instancia necesita un store compartido (fuera de alcance).
* **Sin CORS** (FASE 13): API servidor-a-servidor sin clientes de navegador;
  añadir CORS solo cuando exista un cliente browser.

## 11. Plan de evolución

**Completado:** PostgreSQL (FASE 12), AuthN/AuthZ + producción (FASE 13), roles
y observabilidad con cierre de auditoría (FASE 14), readiness operacional +
pipeline CI verificado en GitHub Actions (FASE 15). Estado: **READY —
PRODUCTION CANDIDATE** (FASE 16).

Pendiente (fuera de FASE 13):

1. **Idempotencia para todos los comandos**: añadir `IdempotencyRepository` a
   `register_player_to_squad`, `create_publication` y `backfill_season`.
2. **Broker real** (Kafka/RabbitMQ): sustituir el outbox-lite por un conector;
   el `EventPublisher` (p. ej. `LoggingPublisher`) y la `Logger` ya son la
   interfaz de intercambio.
3. **OAuth/SSO**: sustituir `ApiKeyAuthenticationProvider` por el proveedor que
   se necesite (el ABC `AuthenticationProvider` es el seam).
4. **Store compartido para rate limiting** si la flota escala a múltiples
   instancias.

## 12. Ejecución de tests

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q          # suite completa (473 tests)
PYTHONPATH=src python3 -m pytest -q \
    --ignore=tests/api --ignore=tests/postgres --ignore=tests/production \
    # suite sin HTTP/PostgreSQL (python del sistema) — 287 tests
```