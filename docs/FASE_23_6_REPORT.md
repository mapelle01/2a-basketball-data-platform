# FASE 23.6 — API Hardening & Production Readiness (Endurecimiento de la API)

## Resumen

Fase de **endurecimiento** (no de expansión funcional) de la API de lectura de
analíticas de temporada (FASE 23.5): validación de entrada robusta, contract de
errores consistente, semántica HTTP correcta, determinismo, protección de
recursos, logs seguros, health/readiness, OpenAPI documentado, CORS auditado y
una migración de índices justificada. La arquitectura HTTP → Router →
Application service → Repository → PostgreSQL se mantiene intacta; no se mueve
lógica al router, no se introduce framework nuevo y no se toca la ingesta FEB.

## Auditoría inicial

Estado de partida (verificado): working tree limpio, HEAD `dde9722`
(`feat(23.5): add season analytics read API`), **794 tests passing**. Se
inspeccionaron `api/analytics.py`, `api/main.py`, `api/gateway.py`,
`api/errors.py`, `api/auth.py`, `api/middleware.py`, `infrastructure/wiring.py`,
`SeasonAnalyticsService`, los repositorios (SQLite + PostgreSQL), las migraciones
`001/002/003` (SQLite) y `001/002` (PostgreSQL), `config.py`, `server.py`,
logging, `/health`, `/ready`, OpenAPI, tests `tests/api/*` y la configuración
Railway.

### Ya correcto (sin cambios, solo verificado)

* **Error contract**: envelope único existente
  `{"error": {"code", "message", "details"}, "command_id": null}` en
  `api/errors.py` — superset del mínimo pedido por 23.6; no se creó un segundo
  sistema. Errores internos → 500 con message genérico, log interno, sin stack
  trace ni filtrado de SQL/DSN/secretos.
* **Semántica HTTP**: 200 con `{season_code, count: 0, items: []}` para
  temporada vacía (23.5 lo estableció; no se introdujo 404); 400 para
  parámetros inválidos; 500 genérico. Los 404 existentes (matches/players/
  teams/competitions/leaderboards/correction-proposals/commands/contracts) son
  recursos concretos — correcto.
* **Autenticación**: los endpoints de analytics son públicos por diseño
  (FASE 11/13, reads/contracts/health/ready públicos); exponen únicamente
  estadísticas públicas de partidos. No se añadieron API keys nuevas ni se
  cambió la política.
* **Logging**: `RequestContextMiddleware` loguea method, path, status, duration,
  request_id — nunca body, headers, credenciales ni secretos.
  `RequestLogger` inyecta el request_id activo. `X-Request-ID` se acepta del
  cliente (seguro: se usa como cadena de correlación) o se genera.
* **Observabilidad**: request_id + status + latency + endpoint ya cubiertos por
  el middleware; no se introdujo Prometheus/OpenTelemetry/Kafka (no existían).
* **Health/readiness**: `/health` = liveness (`{"status": "ok"}`);
  `/ready` = readiness no destructivo (conecta, verifica versión de esquema y
  migraciones al día); fallo de PostgreSQL → 503 `NOT_READY` con checks, sin
  stack trace. Correcto, no se reescribió.
* **Resource protection**: `MAX_LIMIT = 500`; `limit` ausente devuelve la
  temporada completa — la cardinalidad de una temporada está acotada por diseño
  (plantillas de jugadores, nº de equipos de la liga), por lo que `limit` solo
  es suficiente y no hay consultas ilimitadas por parámetro. `limit=999999999`
  y equivalentes → 400.
* **CORS**: no existe configuración (decidido en FASE 13: API server-to-server,
  sin clientes de navegador; habilitar CORS ampliaría la superficie de ataque
  sin consumidor). Se documenta la decisión; **no** se añadió
  `allow_origins=["*"]`. Añadir CORS solo cuando exista un frontend de
  navegador (recomendación abierta).
* **Paginación**: solo `limit`. `offset` NO se implementa: el tamaño de una
  temporada está acotado (≤ 300 jugadores / 28 equipos), el ranking global en
  leaderboards se mantiene con `ROW_NUMBER()` sobre la temporada completa
  aunque se limite el resultado, y una segunda estrategia de paginación no
  aporta valor hoy. Un `offset` no soportado se ignora (determinista).

## Cambios realizados

### 1. Migración de índices `analytics_indexes` (justificado)

Los seis endpoints de analytics filtran **exclusivamente por `season_code`**
(`WHERE season_code = ?` + GROUP BY/ORDER BY id de entidad). Los índices
existentes (`idx_player_stats_season(player_external_id, season_code)` y
`idx_team_stats_match(match_external_id)`) no sirven una búsqueda season-first:
cada request recorrería las tablas completas según crezcan las temporadas.
Se añaden índices season-first, **idempotentes (`IF NOT EXISTS`), no
destructivos y compatibles con PostgreSQL**:

* `migrations/004_analytics_indexes.sql` (SQLite) → `idx_player_stats_season_scan
  (season_code, player_external_id)` y `idx_team_stats_season_scan
  (season_code, team_external_id)`.
* `postgres/migrations/003_analytics_indexes.sql` (espejo).

Se registran en `MIGRATIONS` (SQLite v4, PostgreSQL v3); la comprobación de
readiness (`_expected_schema_version = len(MIGRATIONS)`) se propaga
automáticamente. Verificado: migración aplica en fresh install y sobre una base
v3 en sitio; re-migrar es no-op (test).

### 2. OpenAPI — valores permitidos de `metric`

Los dos parámetros `metric` documentan ahora su `enum` de valores permitidos
(jugador: points/rebounds/assists/steals/blocks/turnovers/games_played; equipo:
classification/points_for/point_difference/win_percentage). Constantes de
documentación en `api/analytics.py` con un **drift test** que las mantiene en
sincronía con la whitelist autoritativa del dominio
(`PlayerLeaderboardMetric.ALL` / `TeamLeaderboardMetric.ALL`), que sigue siendo
la única que rechaza peticiones (el router nunca importa lógica de dominio —
boundary de arquitectura preservado).

## Validaciones

* **season_code**: la ruta no matchea un segmento vacío → 404 controlado
  (envelope `HTTP_ERROR`, nunca 500); formato inválido, caracteres inesperados y
  longitud excesiva → 400 `INVALID_PARAMETER` (regex `^[0-9]{4}-[0-9]{2,4}$` de
  `SeasonCode`, que acota longitud ≤ 9 y no se convierte en 500).
* **limit**: `0`, `-1`, `501`, `999999999` → 400 `INVALID_PARAMETER`;
  no numérico (`abc`, `1.5`, `10e2`) → 400 `INVALID_BODY` (422 de FastAPI mapeado
  por el handler global); ausente → 200 con la temporada completa; `1..500` →
  200. Comportamiento determinista.
* **metric**: desconocida (jugador y equipo) → 400 `INVALID_PARAMETER` antes de
  llegar a SQL (el lookup de whitelist en el repositorio lanza `ValueError`; no
  hay interpolación de SQL con input del cliente).
* **Determinismo**: todos los endpoints `ORDER BY` id ASC (agregados/métricas) o
  métrica + id ASC (leaderboards); dos peticiones idénticas devuelven cuerpos
  idénticos (test).
* **Leaderboards**: `ROW_NUMBER()` sobre la temporada completa → el `rank`
  global se mantiene con `limit` (test: top-2 devuelve ranks [1,2], coherentes
  con el ranking completo).
* **Performance**: consultas con filtro de temporada, `GROUP BY`, `ORDER BY`,
  CTE + `ROW_NUMBER()` para leaderboards, sin cartesianos; cubiertas por los
  nuevos índices season-first. Tests cross-backend verifican queries válidas,
  filtro de temporada, orden y límites en SQLite y PostgreSQL local.

## Seguridad

Tests explícitos de no-secret-leakage:
* Error interno (gateway lanza `RuntimeError` con DSN `postgresql://user:secret…`
  y token) → 500 con message genérico; ninguno de los secretos aparece en la
  respuesta.
* El header `Authorization` (Bearer + X-API-Key) nunca aparece en los registros
  del `RecordingLogger`.
* `/ready` con dependencia caída → 503 `NOT_READY`, sin stack trace; un fallo
  catastrófico de `readiness` → 500 genérico sin DSN.
* OpenAPI: ningún property de los schemas contiene nombres de credenciales
  (password/secret/token/api_key/dsn/authorization).
* Limitación por petición (POST commands) y headers de seguridad
  (`nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store`) ya existentes
  — intactos.

## Tests

* `tests/api/test_hardening.py` — **40 tests nuevos**: matriz de validación
  (season_code vacío/inválido/largo/caracteres inesperados; limit 0/-1/501/
  999999999/no numérico/ausente/1; metric inválida jugador y equipo),
  determinismo (6 endpoints, dos peticiones → mismo cuerpo), ranking global bajo
  `limit`, no duplicación/estabilidad con `limit`, `offset` no soportado se
  ignora, no-secret-leakage en respuesta y logs, estructura de logs segura,
  `X-Request-ID` echo + generación, `/health`, `/ready` OK y con fallo (503/500
  sin fugas), OpenAPI (6 endpoints con `SeasonResponse_*Item_`, `enum` de
  `metric` alineado con el dominio, sin modelos de credenciales).
* `tests/postgres/test_season_analytics_indexes.py` — **6 tests**
  (parametrizados SQLite + PostgreSQL): los índices existen tras migrar,
  re-migrar es idempotente, y las 6 consultas mantienen filtro de temporada,
  orden y límites con los índices activos.

Suite completa: **840 passed, 0 failed**
(`PYTHONPATH=.:src .venv/bin/pytest -q`) — 794 previos + 46 nuevos, sin
regresiones (boundary de arquitectura intacto).

## Producción

`railway status` → *No linked project found* y el DSN no está disponible en el
entorno local (`DATABASE_URL`/`FEB_SCORE_DATABASE_URL` ausentes). Además,
`postgres.railway.internal` no es resoluble desde el Mac fuera de la red privada
de Railway.

```
PRODUCTION VALIDATION: BLOCKED
```

No se intenta exponer PostgreSQL, abrir puertos, copiar credenciales ni saltarse
la red privada. Las consultas idénticas sí se validaron contra PostgreSQL local
sintético (`127.0.0.1:5433`) con resultados correctos e idénticos a SQLite
(tests parametrizados).

## Limitaciones

* **`limit` ausente = temporada completa**: decisión deliberada (consumidores
  de dashboard/roster necesitan la lista completa; la cardinalidad está acotada).
  Si una temporada superara ~miles de jugadores, reevaluar offset/cursor.
* **`X-Request-ID` aceptado sin límite de longitud**: se usa solo como cadena de
  correlación; el tamaño del header lo acota el servidor.
* **Rate limiting**: en memoria y por proceso (documentado en FASE 13); para un
  despliegue multi-instancia haría falta un store compartido (fuera de alcance).
* **`season_code` vacío** responde 404 (la ruta no matchea segmento vacío),
  no 400 — controlado y determinista, pero documentado para consumidores.
* **CORS**: sin configuración hasta que exista un cliente de navegador.

## Recomendaciones

1. Habilitar CORS con lista blanca de orígenes (nunca `*`) cuando exista el
   frontend.
2. Validar en caliente contra Railway desde dentro de la red o con
   `railway connect Postgres` + DSN (mismo escenario que 23.3/23.4/23.5).
3. Considerar rate limit compartido (Redis) si el despliegue pasa a
   multi-instancia.
4. Si el volumen crece, evaluar offset/cursor con claves estables para paginar
   los agregados (los leaderboards ya preservan ranking global).

## Commits

* `feat(23.6): harden season analytics read API` — migración de índices
  season-first (SQLite #4 / PostgreSQL #3), enum de `metric` en OpenAPI, 46
  tests (validación, determinismo, seguridad/logs, health/readiness, OpenAPI,
  índices cross-backend) y este informe. Sin push.