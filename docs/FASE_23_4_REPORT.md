# FASE 23.4 — Advanced Season Metrics (Métricas avanzadas de temporada)

## Resumen

Capa de métricas derivadas construida sobre los agregados `SeasonPlayerStats`
(FASE 23.1) y `SeasonTeamStats` (FASE 23.2), que convierte los totales de
temporada en **medias por partido** listas para consumidores:

* **Jugadores (7 métricas por partido)** — points, rebounds, assists, steals,
  blocks, turnovers y minutes por partido, a partir de los totales de la
  temporada.
* **Equipos (12 métricas por partido)** — points, points_against,
  point_difference (puede ser negativo), win_percentage (porcentaje 0..100),
  field_goals_made/attempted, three_points_made/attempted,
  free_throws_made/attempted, turnovers y rebounds por partido.

El cálculo se resuelve en **SQL** para PostgreSQL y SQLite (división con guarda
`CASE WHEN games_played > 0`, sin redondeo) y en **Python puro** para InMemory
(`domain/statistics/metrics.py`, implementación de referencia compartida). El
service es una capa fina que delega en el repositorio.

### Fuera de alcance: métrica de eficiencia (FIBA PIR / PER)

No se deriva **ninguna** métrica de eficiencia: `match_player_stats` solo
contiene points, rebounds, assists, steals, blocks, turnovers y minutes — una
métrica tipo FIBA PIR requiere `FGA/FGM`, `FTA/FTM`, faltas y faltas recibidas,
que no existen en los datos. Documentado en el docstring de
`SeasonPlayerMetrics`; no se inventan aproximaciones.

## Arquitectura

```
Domain (sin SQL)
  domain/statistics/model.py        SeasonPlayerMetrics, SeasonTeamMetrics
                                    (read models con validación en __post_init__)
  domain/statistics/metrics.py      player_metrics / team_metrics / _safe_div
                                    (derivación pura, referencia / InMemory)

Application
  use_cases/season_metrics_service.py  SeasonMetricsService: delega en
                                       MatchStatsRepository
  repositories/interfaces.py        + list_season_player_metrics(season_code)
                                    + list_season_team_metrics(season_code)

Infrastructure
  repositories/in_memory.py         métricas en Python (metrics.py)
  persistence/repositories.py       SQLite: división segura en SQL
  persistence/postgres/repositories.py  PostgreSQL: división segura en SQL
```

## Semántica de métricas

* **Per-game = total / games_played**, con división segura: `0.0` cuando
  `games_played <= 0` (nunca DivisiónByZero). Sin redondeo: valores float a
  precisión completa, tanto en Python como en SQL (`CAST(... AS REAL)`).
* **win_percentage (equipo) = wins / games_played × 100** → porcentaje 0..100.
  ⚠️ Distinto del `SeasonTeamLeaderboardEntry.win_percentage` de FASE 23.3
  (fracción 0..1 usada para ranking). Documentado en `SeasonTeamMetrics`.
* **point_difference_per_game = (points_for − points_against) / games_played**:
  puede ser negativo; es el único per-game de equipo sin restricción de signo
  en la validación del modelo.
* **wins/losses** se derivan por partido (`points_for > points_against` →
  win; `<` → loss), igual que en 23.2.
* **Determinista**: orden por `player_external_id` / `team_external_id` ASC.
* **Aislamiento de temporada**: cada consulta filtra estrictamente por
  `season_code`.
* **El read model repite los totales** (points, rebounds, games_played, etc.)
  para que sea autocontenido y permita la validación cruzada
  `per_game × games_played ≈ total`.

## Modelos y validación

* `SeasonPlayerMetrics`: `games_played >= 0`, totales y per-game no negativos,
  per-game finitos.
* `SeasonTeamMetrics`: mismos controles; `point_difference_per_game` **sí**
  puede ser negativo; `win_percentage` y el resto de per-game no negativos y
  finitos.

## Tests

* `tests/domain/test_season_metrics.py` — **28 tests** (servicio sobre
  InMemory + referencia): 12 de jugador (points/rebounds/assists/steals/
  blocks/turnovers/minutes per-game, games_played, totales repetidos, jugador
  de un partido, división segura con `games_played=0`, aislamiento de
  temporada, orden determinista, precisión completa sin redondeo, temporada
  vacía) y 12 de equipo (points, points_against, point_difference negativo,
  win_percentage como porcentaje 0..100, wins/losses derivados, games_played,
  field_goals/three_points/free_throws/turnovers/rebounds per-game,
  aislamiento + orden, temporada vacía + división segura), más validación de
  modelo (rechazo de negativos, admisión de point_difference negativo).
* `tests/postgres/test_season_metric_sql.py` — **16 tests** (parametrizados
  SQLite + PostgreSQL): las métricas resueltas en SQL coinciden exactamente con
  la referencia Python (InMemory), valores conocidos, win_percentage como
  porcentaje, invariantes de consistencia
  (`per_game × gp ≈ total`; SUM(games_played) == 2×partidos;
  SUM(wins) == SUM(losses) == partidos), aislamiento de temporada y temporada
  vacía.

Suite completa: **761 passed, 0 failed** (`PYTHONPATH=.:src .venv/bin/pytest -q`)
— 717 previos (FASE 23.3) + 44 nuevos, sin regresiones.

## Validador de producción (READ-ONLY)

`validate_season_metrics_2025_2026.py` — conecta a PostgreSQL, solo lee, no
imprime secretos.

Comprobaciones:
* **Jugadores**: nº de jugadores, líderes por cada métrica per-game,
  round-trip `per_game × games_played == total` (tolerancia float),
  per-game finitos y no negativos, SUM(games_played) == filas raw de
  `match_player_stats`, SUM(points) == SUM(raw.points), sin duplicados, orden
  determinista, aislamiento 2025-2026.
* **Equipos**: nº de equipos == 28, SUM(games_played) == **728** (364 partidos
  × 2 equipos), SUM(wins) == SUM(losses) == **364**, round-trip de
  points/points_against/point_difference per-game, win_percentage ≈
  wins/gp×100, per-game finitos, SUM(points_for)/SUM(points_against) == raw,
  aislamiento 2025-2026.

Resultado de ejecución:
* **PASS** verificado contra una base PostgreSQL local sintética equivalente
  (364 partidos, 300 jugadores, 28 equipos, sin empates): SUM(games_played)
  = 728, SUM(wins) = SUM(losses) = 364, SUM(points) jugador y de equipo
  consistentes con los totales raw, round-trips exactos.
* **Producción: BLOCKED** — mismo motivo que FASE 23.3: el PostgreSQL privado
  de Railway (`postgres.railway.internal`) no es alcanzable desde el entorno
  local sin el túnel `railway connect Postgres` y el DSN no está disponible en
  el entorno local. No se intenta bypassear la red privada. El validador queda
  listo para ejecutarse dentro de la red de Railway o con el túnel + DSN.

## Commits

* `feat(23.4): add advanced season metrics` — modelos, métricas de referencia,
  interfaz + 3 backends (InMemory/SQLite/PostgreSQL), servicio, 44 tests,
  validador READ-ONLY y este informe. Sin push.