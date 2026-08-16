# FASE 23.5 — Read API / Season Analytics Endpoints (API de lectura de analíticas de temporada)

## Resumen

Exposición vía HTTP GET de los read models de analítica ya existentes
(agregados FASE 23.1, leaderboards FASE 23.3 y métricas FASE 23.4) bajo
`/v1/seasons/{season_code}/...`. Los routers son capas finas: solo validan
parámetros, delegan en `SeasonAnalyticsService` (composición de
`SeasonLeaderboardService` + `SeasonMetricsService` + `MatchStatsRepository`)
y devuelven un sobre de respuesta tipado. Sin SQL ni lógica de negocio en la
capa HTTP.

Seis endpoints públicos (sin API key, coherente con FASE 11/13: *reads,
contracts, health y ready son públicos por diseño*):

| Método | Ruta | Params | Descripción |
|---|---|---|---|
| GET | `/v1/seasons/{season_code}/players` | `limit` | Agregados de temporada por jugador |
| GET | `/v1/seasons/{season_code}/players/leaderboards` | `metric`, `limit` | Ranking de jugadores por métrica |
| GET | `/v1/seasons/{season_code}/players/metrics` | `limit` | Métricas per-game de jugador (23.4) |
| GET | `/v1/seasons/{season_code}/teams` | `limit` | Agregados de temporada por equipo |
| GET | `/v1/seasons/{season_code}/teams/leaderboards` | `metric`, `limit` | Clasificación / ranking de equipos |
| GET | `/v1/seasons/{season_code}/teams/metrics` | `limit` | Métricas per-game de equipo (23.4) |

Documentación automática en `/docs` (OpenAPI) vía `response_model`:
cada endpoint declara `SeasonResponse[<Item>]` (modelos Pydantic v2), tags
`analytics`, summary y description.

## Arquitectura

```
HTTP  ->  FastAPI router  ->  CommandGateway (api/gateway.py, ABC)
                                  |   _GatewayBase (infrastructure/wiring.py)
                                  |     valida SeasonCode + metric -> DTOs
                                  v
                  SeasonAnalyticsService (application/use_cases)
                                  |
            +---------------------+----------------------+
            v                     v                      v
   SeasonLeaderboardService   SeasonMetricsService   MatchStatsRepository
   (FASE 23.3)                (FASE 23.4)            (interfaces + 3 backends)
```

* `api/analytics.py` — `register_analytics_routes(app)`, `SeasonResponse[T]`
  (sobre `{"season_code", "count", "items"}`), 6 modelos de item, `MAX_LIMIT=500`.
* `api/gateway.py` — `CommandGateway` gana 6 métodos de lectura que devuelven
  `List[Dict[str, Any]]`.
* `infrastructure/wiring.py` — `_GatewayBase` construye
  `SeasonAnalyticsService(self._stats_repo)` e implementa los 6 métodos con
  builders DTO de módulo (`_player_aggregate_dto`, `_player_leaderboard_dto`,
  `_player_metrics_dto`, `_team_aggregate_dto`, `_team_leaderboard_dto`,
  `_team_metrics_dto`). Nada de esto existe en la capa HTTP.
* `application/use_cases/season_analytics_service.py` — composición; los 6
  métodos lanzan `ValueError` para métricas desconocidas (validación delegada
  en `SeasonLeaderboardService`).
* Interfaz y backends: `list_season_player_aggregates`,
  `list_season_team_aggregates`, `list_season_player_metrics` y
  `list_season_team_metrics` ganan `limit: Optional[int] = None`
  (interfaces.py + InMemory + SQLite `LIMIT ?` + PostgreSQL `LIMIT %s`).

## Contrato HTTP

* **Sobre de respuesta**: `{"season_code": "...", "count": N, "items": [...]}`.
  `count` refleja el número de elementos devueltos (puede ser menor que el
  total por `limit`).
* **Límites**: `limit` opcional, entero `1..MAX_LIMIT` (500). Sin offset ni
  cursor: la especificación prohíbe introducir una segunda estrategia de
  paginación.
* **`season_code`**: filtro, no recurso. `YYYY-YY` o `YYYY-YYYY` (valida
  `SeasonCode`). **Una temporada sin datos responde 200 con items vacíos** —
  no se usa 404 (coherente con 23.1–23.4, que devuelven listas vacías).
* **Métricas de leaderboard**:
  * Jugador: `points, rebounds, assists, steals, blocks, turnovers,
    games_played` (`PlayerLeaderboardMetric.ALL`).
  * Equipo: `classification, points_for, point_difference, win_percentage`
    (`TeamLeaderboardMetric.ALL`).
* **Códigos de error** (envelope `errors.py`): `400 INVALID_PARAMETER` para
  `season_code` inválido, métrica desconocida o `limit` fuera de rango;
  `limit` no entero → 422 de FastAPI → 400 por el handler global
  (`INVALID_BODY`, sigue siendo 400). `500 INTERNAL_ERROR` jamás filtra
  SQL/DSN/secretos (message genérico; el detalle solo va al log).
* **Orden**: determinista — agregados y métricas por id ASC; leaderboards por
  la métrica pedida (classification por wins DESC, losses ASC, point_difference
  DESC, id ASC). Aislamiento estricto por temporada.
* **`win_percentage`** en leaderboard de equipo es fracción 0..1 (23.3, ranking)
  mientras que en team metrics es porcentaje 0..100 (23.4): semánticas de 23.3/
  23.4 intactas.

## Tests

* `tests/api/test_analytics.py` — **29 tests** sobre SQLite (HTTP → gateway →
  servicio → repositorio → SQL): envelope/schema exactos por endpoint,
  rankings con orden y ranks correctos, valores per-game (incl. jugador de un
  solo partido, point_difference_per_game negativo, win_percentage 50.0),
  `limit` (2, 1), temporada vacía → 200 items vacíos, aislamiento de temporada
  (2025-2026 no contamina con datos 2024-2025 y viceversa), errores 400
  (`INVALID_PARAMETER`: season_code inválido, métrica desconocida jugador y
  equipo, limit 0 y 99999), **500 sin fuga de secretos** (RuntimeError con DSN
  simulado → message genérico sin `postgresql` ni `secret`) y **endpoints
  públicos sin API key**.
* `tests/postgres/test_season_analytics_api.py` — **4 tests parametrizados**
  (fixture `backend`: SQLite + PostgreSQL, mismo dataset determinista):
  prueba integrada representativa de cada grupo de endpoints con resultados
  idénticos en ambos backends (players, player leaderboards + métrica inválida,
  player metrics, teams + classification + team metrics, aislamiento).

Suite completa: **794 passed, 0 failed** (`PYTHONPATH=.:src .venv/bin/pytest -q`)
— 761 previos (FASE 23.4) + 33 nuevos, sin regresiones.

## Validación de producción (READ-ONLY)

El plan era validar los endpoints contra PostgreSQL de producción solo lectura.
**Resultado: BLOCKED** — mismo motivo que FASE 23.3 y 23.4: el PostgreSQL
privado de Railway (`postgres.railway.internal`) no es alcanzable desde el
entorno local sin el túnel `railway connect Postgres`, y `DATABASE_URL` no está
disponible en el entorno local (`/tmp/feb_env.sh` no lo define). No se intenta
bypassear la red privada. La validación en caliente queda pendiente de
ejecutarse dentro de la red de Railway o con el túnel + DSN. Sí se verificó el
mismo conjunto de consultas contra PostgreSQL local sintético
(`127.0.0.1:5433`, dataset 364 partidos/300 jugadores/28 equipos) con
resultados correctos e idénticos a SQLite (pruebas parametrizadas de
`tests/postgres/test_season_analytics_api.py`).

## Commits

* `feat(23.5): add season analytics read API` — 6 endpoints GET públicos,
  `SeasonAnalyticsService`, `limit` en interfaz + 3 backends, 6 métodos en
  `CommandGateway`/`_GatewayBase` con builders DTO, 33 tests (HTTP SQLite +
  integración SQLite/PostgreSQL) y este informe. Sin push.