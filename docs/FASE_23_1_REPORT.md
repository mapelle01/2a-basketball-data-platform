# FASE 23.1 — Season Player Aggregates Report

## Objetivo
Implementar la primera capa analítica de temporada para obtener las estadísticas acumuladas de cada jugador (Season Player Aggregates) de forma eficiente y sin impactar la ingesta ni el modelo de eventos. 

## Arquitectura Utilizada
Se ha optado por implementar un **Read Model** (`SeasonPlayerStats`) y una consulta de lectura agregada (`list_season_player_aggregates`) sobre las tablas de proyecciones existentes (`match_player_stats`).
Esto evita duplicar la ingesta o agregar campos computados durante la transacción de dominio, delegando el peso analítico al motor de la base de datos de lectura.
La extensión se incluyó de forma natural en `MatchStatsRepository` (interfaces y todas sus implementaciones: InMemory, Sqlite y PostgreSQL).

## Diseño del Agregado
La dataclass `SeasonPlayerStats` expone:
- `player_external_id`
- `season_code`
- `games_played` (Contado agrupando los `match_external_id`)
- `points`, `rebounds`, `assists`, `steals`, `blocks`, `turnovers`, `minutes` (Sumados)

Se han definido aserciones de validación básica (`__post_init__`) garantizando que no existen métricas negativas. 

## Query / Agregación (PostgreSQL y SQLite)
Debido a que `match_player_stats` proyecta los datos del BoxScore en columnas reales normalizadas, se ha utilizado la siguiente query SQL:
```sql
SELECT
  player_external_id,
  season_code,
  COUNT(match_external_id) AS games_played,
  SUM(points) AS points,
  SUM(rebounds) AS rebounds,
  SUM(assists) AS assists,
  SUM(steals) AS steals,
  SUM(blocks) AS blocks,
  SUM(turnovers) AS turnovers,
  SUM(minutes) AS minutes
FROM match_player_stats
WHERE season_code = %s
GROUP BY player_external_id, season_code
ORDER BY player_external_id
```

## Tests
Se añadió el fichero `tests/postgres/test_season_player_aggregates.py`. 
Los casos evaluados incluyen:
- **Caso 1:** Jugador con varios partidos.
- **Caso 2:** Jugador que no juega todos los partidos.
- **Caso 3:** Jugador cambiando de equipo durante la temporada.
- **Caso 4:** Aislamiento de diferentes temporadas.
- **Caso 5:** Campos ausentes/nulos manejados correctamente por base de datos (DEFAULT 0).
- **Caso 6:** Resultados deterministas y con ordenación estricta por `player_external_id`.
- **Caso 7:** Prueba PostgreSQL incluida vía `conftest.py` en la parametrización de bases de datos de la suite de test del backend.

**Resultados de la Suite:** `630 passed`

## Validación con Datos Reales (Producción)
Se implementó y versionó el script read-only `validate_season_2025_2026.py` para la comprobación exhaustiva y cálculo de consistencia matemática de la temporada `2025-2026`.

`PRODUCTION VALIDATION: BLOCKED — private Railway PostgreSQL not directly reachable from local environment`

**Causa técnica:** La base de datos de producción Railway utiliza red privada interna (`postgres.railway.internal`), la cual no es resoluble ni accesible directamente desde el entorno local de desarrollo (Mac) por políticas de seguridad (sin endpoint público TCP expuesto).

**Mecanismo de ejecución:** El script `validate_season_2025_2026.py` queda preparado para ejecutarse de forma 100% segura en un entorno que resuelva la red privada o mediante un task/one-off container en Railway:
```bash
FEB_SCORE_DATABASE_URL="<dsn>" python3 validate_season_2025_2026.py
```
Comprueba de forma estricta:
1. `games_played` vs `COUNT(*)` en `match_player_stats`.
2. Igualdad de sumas exactas para `points`, `rebounds`, `assists`, `steals`, `blocks`, `turnovers` y `minutes`.
3. Aislamiento de `season_code = '2025-2026'`.
4. Determinación de líderes individuales de la temporada.

## Decisiones Arquitectónicas y Limitaciones
- **Domain vs Persistence**: Se ha mantenido limpio el core; `SeasonPlayerStats` es meramente un read model. No se emiten eventos extra de actualización de temporada.
- **Eficiencia**: La agregación SQL es altamente rápida dado el índice primario (`match_external_id`, `player_external_id`) e índice por temporada (`player_external_id`, `season_code`), resolviendo la consulta on-the-fly (`GROUP BY`) sin necesidad de tablas intermedias.
