# FASE 23.3 — Season Leaderboards (Rankings de temporada)

## Resumen

Capa de lecturas / analítica construida sobre los agregados `SeasonPlayerStats`
(FASE 23.1) y `SeasonTeamStats` (FASE 23.2): rankings posicionales (1..N)
deterministas de jugadores (7 métricas) y de equipos (4 métricas).

Se corrigió el **bug raíz** que hacía fallar los 14 tests de 23.3: el backend
InMemory descartaba `season_code` al guardar y agregaba **todas** las
temporadas mezcladas. SQLite y PostgreSQL ya filtraban bien por temporada;
la corrección alinea InMemory con el resto de backends.

Ranking resuelto en **SQL** para PostgreSQL y SQLite (`ROW_NUMBER()` sobre
un CTE de agregación) y en **Python puro** para InMemory (implementación de
referencia compartida). El service valida la métrica y delega en el
repositorio.

## Arquitectura

```
Domain (sin SQL)
  domain/statistics/model.py        SeasonPlayerLeaderboardEntry,
                                    SeasonTeamLeaderboardEntry,
                                    PlayerLeaderboardMetric, TeamLeaderboardMetric
  domain/statistics/ranking.py      rank_player_entries / rank_team_entries
                                    (ranking posicional puro, referencia / InMemory)

Application
  use_cases/leaderboard_service.py  SeasonLeaderboardService: valida métrica y
                                    delega en MatchStatsRepository
  repositories/interfaces.py        + list_season_player_leaderboard(season, metric, limit)
                                    + list_season_team_leaderboard(season, metric, limit)

Infrastructure
  repositories/in_memory.py         ranking en Python (ranking.py)
  persistence/repositories.py       SQLite: ROW_NUMBER() en SQL
  persistence/postgres/repositories.py  PostgreSQL: ROW_NUMBER() en SQL
```

## Semántica de ranking

* **Posicional 1..N**: se ordena y se asignan rangos consecutivos; dos
  entradas con el mismo valor de métrica reciben rangos distintos (1, 2, 3 —
  nunca 1, 1, 3). Sin DENSE_RANK (diferido a una fase futura si la API lo pide).
* **Determinista**: toda métrica termina con tiebreaker `*_external_id` ASC.
* Jugadores (DESC, salvo turnovers ASC — menos pérdidas = mejor): points,
  rebounds, assists, steals, blocks, turnovers, games_played.
* Equipos:
  * classification  → wins DESC, losses ASC, point_difference DESC, id ASC
  * points_for      → DESC, id ASC
  * point_difference→ DESC, id ASC
  * win_percentage  → DESC, wins DESC, id ASC
* `point_difference` y `win_percentage` son **derivados** (no se almacenan):
  `win_percentage = wins / games_played` (0.0 si `games_played == 0`).

## Bug corregido (raíz de los 14 tests fallidos)

`InMemoryMatchStatsRepository.save_player_stats/save_team_stats` guardaba los
stats keyed por `match_external_id` **descartando `season_code`**, y
`list_season_player_aggregates/list_season_team_aggregates` agregaba todos los
buckets sin filtrar por temporada. Efecto observado:

* `test_team_ranking_season_isolation`: T1 `points_for` = 240 + 100 (fuga 2024-2025) = **340** (esperado 240).
* `test_team_leaderboard_games_played_invariant`: SUM(games_played) = 6 + 1 = **7** (esperado 6).
* Rankings de jugador: el partido de 999 pts de PA en 2024-2025 inflaba todas las métricas.

Fix: cada bucket de match registra su `season_code`; las agregaciones filtran
por la temporada solicitada. `list_player_stats_by_season` ahora filtra por
temporada (antes era un mock sin filtro).

## Tests

* `tests/domain/test_season_leaderboards.py` — **25 tests** (servicio sobre
  InMemory): 7 métricas de jugador, tiebreak determinista, limit, aislamiento
  de temporada, clasificación, tiebreaks por losses y por point_difference,
  points_for, point_difference, win_percentage, invariantes matemáticas
  (SUM(leaderboard.points) == SUM(aggregates.points); SUM(wins)/SUM(losses)),
  casos borde y errores de métrica.
* `tests/postgres/test_season_leaderboard_sql.py` — **42 tests** (parametrizados
  SQLite + PostgreSQL): el ranking resuelto en SQL coincide exactamente con la
  referencia Python para las 7 métricas de jugador y las 4 de equipo; rank
  posicional consecutivo; `limit` preserva rangos globales; aislamiento de
  temporada; consistencia matemática; errores de métrica; temporada vacía.

Suite completa: **717 passed, 0 failed** (`PYTHONPATH=.:src .venv/bin/pytest -q`).
Antes de la corrección: 661 passed / 14 failed.

## Validador de producción (READ-ONLY)

`validate_season_leaderboards_2025_2026.py` — conecta a PostgreSQL, solo lee.

Comprobaciones:
* Jugadores: nº de jugadores, líderes por puntos/rebotes/asistencias/robos/
  tapones/partidos, SUM(leaderboard.points) == SUM(aggregates.points),
  sin duplicados, ranks consecutivos 1..N, aislamiento 2025-2026.
* Equipos: nº de equipos, clasificación final completa,
  SUM(games_played) == **728** (364 partidos × 2 equipos),
  SUM(wins) == SUM(losses) == 364, sin duplicados, ranks consecutivos,
  aislamiento 2025-2026.
* No imprime contraseñas/tokens/DSN. No modifica ningún dato.

Resultado de ejecución:
* **PASS** verificado contra una base PostgreSQL local sintética equivalente
  (364 partidos, 300 jugadores, 28 equipos, sin empates): SUM(points) 68653 ==
  68653, SUM(games_played) = 728, SUM(wins) = SUM(losses) = 364.
* **Producción: BLOCKED** — PostgreSQL privado de Railway
  (`postgres.railway.internal`) no es alcanzable desde el entorno local sin el
  túnel `railway connect Postgres`, y el DSN no está disponible en el entorno
  local. No se intenta bypassear la red privada. El validador queda listo para
  ejecutarse dentro de la red de Railway o con el túnel + DSN.

## Commits

* `feat(23.3): add season leaderboards` — incluye el trabajo parcial previo
  (sin commitear) de 23.3 (modelos de leaderboard, servicio, tests de dominio)
  más la corrección InMemory, los backends SQL, los tests cross-backend y el
  validador de producción. Sin push.