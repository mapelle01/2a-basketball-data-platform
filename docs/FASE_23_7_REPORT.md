# FASE 23.7 — Production Validation & Readiness (Validación de Producción y Readiness)

## Resumen

Fase de **validación** (no de expansión funcional) de toda la superficie de
analíticas de temporada (FASE 23.1-23.6): un único validador **read-only**
`validate_season_analytics_production.py` cubre integridad de partidos,
agregados de jugador/equipo, leaderboards, métricas per-game e integridad
general para `2025-2026`, con cruces contra las tablas crudas y aislamiento de
temporada. Se verifican además el comportamiento de los índices season-first
(23.6) con `EXPLAIN` en PostgreSQL local. La validación contra Railway queda
**BLOCKED** documentado (mismo escenario que 23.3/23.4/23.5/23.6): no hay
proyecto enlazado ni DSN local y la red privada de Railway no es accesible desde
el Mac. No se salta la red privada, no se exponen puertos, no se copian
credenciales y no se imprimen secretos.

## Estado de partida (auditoría)

Working tree limpio, HEAD `25a41ad` (`feat(23.6): harden season analytics read
API`), **840 tests passing**. Se inspeccionaron los validadores previos
(`validate_season_2025_2026.py`, `validate_season_leaderboards_2025_2026.py`,
`validate_season_metrics_2025_2026.py`, `validate_season_team_aggregates.py`),
el esquema de `matches`/`match_player_stats`/`match_team_stats` (migraciones
SQLite y PostgreSQL), `SeasonAnalyticsService`, los 6 métodos de lectura del
repositorio y las whitelists de métricas del dominio.

### Hallazgos de la auditoría

* El dominio **no persiste el grupo ESTE/OESTE**: `competition_id` es
  `segunda-feb` para ambos grupos y no existe columna de grupo en `matches`.
  El `round_number` tampoco es una columna normalizada: vive en
  `data->>'round_number'` (JSONB en PostgreSQL).
* Consecuencia: el validador no puede (ni debe) afirmar "7 partidos ESTE + 7
  partidos OESTE" por jornada. Verifica el **equivalente estructural**
  infalsificable: 26 jornadas × exactamente 14 partidos, 28 apariciones de
  equipo distintas por jornada (ningún equipo juega dos veces en la misma
  jornada) y 28 equipos × exactamente 26 partidos. Esto es exactamente lo que
  implica la hipótesis de dos grupos de 14 que no se cruzan, y queda documentado
  como limitación.
* Los agregados de jugador cruzan `SUM(games_played)` y cada columna de stats
  contra `match_player_stats`; los de equipo cruzan `SUM(games_played)=728`,
  `SUM(wins)=SUM(losses)=364` y cada columna de `TeamStats` contra
  `match_team_stats`. Las 7 métricas de jugador y las 11 de equipo se validan
  con round-trip `per_game × games_played ≈ total`, `win_percentage`,
  `point_difference` y guarda de división por cero.
* Los leaderboards se validan para **todas** las métricas soportadas
  (`PlayerLeaderboardMetric.ALL` = 7, `TeamLeaderboardMetric.ALL` = 4): rango
  1..N sin huecos, sin duplicados, determinismo (dos ejecuciones idénticas),
  aislamiento de temporada y coherencia con los agregados.

## Cambios realizados

### 1. `validate_season_analytics_production.py` (nuevo, read-only)

Validador único y ejecutable de la superficie completa. Seis bloques con
PASS/FAIL por bloque y veredicto final (exit 0 = PASS, 1 = FAIL,
2 = BLOCKED):

1. **MATCHES**: total == 364, `external_id` distintos == 364 (0 duplicados),
   `round_number` en 1..26 sin NULL/0, 26 jornadas × 14 partidos, 28 equipos
   distintos por jornada.
2. **PLAYER AGGREGATES**: jugadores distintos, `SUM(games_played)` == filas
   crudas, `SUM` de points/rebounds/assists/steals/blocks/turnovers/minutes ==
   `SUM` crudo de `match_player_stats`, sin duplicados, sin fugas de otra
   temporada, orden determinista.
3. **TEAM AGGREGATES**: `SUM(games_played)=728`, `SUM(wins)=SUM(losses)=364`,
   `SUM` de cada columna de `TeamStats` == `SUM` crudo de `match_team_stats`,
   28 equipos × 26 partidos, sin duplicados, sin fugas, orden determinista.
4. **LEADERBOARDS**: las 7 + 4 métricas (rango 1..N, sin dups, determinismo,
   aislamiento, coherencia con agregados).
5. **METRICS**: round-trip per-game de todas las métricas, `win_percentage`
   (% = wins/gp·100), `point_difference`, guarda `games_played == 0`.
6. **INTEGRIDAD**: sin NULLs inesperados, sin `season_code` vacío, filas de
   otras temporadas aisladas de las agregaciones.

Propiedades operativas: **READ-ONLY** (solo SELECT), conexión vía
`FEB_SCORE_DATABASE_URL` o `DATABASE_URL`, **nunca imprime credenciales/DSN**
(incluido el fallo BLOCKED, que explica la causa y cómo ejecutarlo dentro de la
red de Railway sin revelar secretos). En fallo de conexión devuelve BLOCKED en
lugar de FAIL.

### 2. `tests/postgres/test_season_analytics_validator.py` (nuevo, 4 tests)

Cubre el validador con los **mismos datos de producción-equivalente** (364
partidos / 26 jornadas / 28 equipos / 300 jugadores / fila de aislamiento
`2024-2025`):

* **PASS** sobre dataset íntegro (todos los bloques, `failures == []`).
* **FAIL** si se elimina un partido (`matches total` reportado).
* **FAIL** si un `round_number` se pone a 0.
* `validate_production()` sin `DATABASE_URL` → error limpio (exit 1).

Los bloques se ejecutan a través de las funciones reales del validador, no de
re-implementaciones: si el validador dejara de gatear una inconsistencia, el
test lo detecta.

## Validaciones

* **Ejecución local end-to-end** sobre PostgreSQL sintético
  (`feb_analytics_valid`, 127.0.0.1:5433, misma forma de producción:
  364 partidos, 728 filas de equipo, 7.800 filas de jugador, fila de
  aislamiento): **los 6 bloques PASS**.
* **Aislamiento de temporada**: la fila `2024-2025` (points=9999) queda fuera
  de agregados/leaderboards/métricas de `2025-2026` (verificado por el
  validador y por los tests).
* **Performance (EXPLAIN)**: las consultas de agregados y leaderboards usan
  `WHERE season_code` + `GROUP BY`/`ROW_NUMBER`. A escala sintética (728/7.800
  filas) el planner elige correctamente `Seq Scan` (el índice no es
  selectivo); forzando `enable_seqscan=off` se confirma que el plan usa
  `Bitmap Index Scan on idx_team_stats_season_scan / idx_player_stats_season_scan`
  (`Index Cond: season_code`). Los índices season-first de 23.6 están
  disponibles y son usados al crecer el volumen.
* **Sin N+1**: todos los bloques ejecutan una consulta por agregado/raw;
  ninguna repetición por entidad.
* **Determinismo**: agregados y métricas `ORDER BY id ASC`; leaderboards
  ordenados por métrica + id; dos ejecuciones del validador producen el mismo
  resultado (los bloques de leaderboards lo comprueban explícitamente).

## Seguridad

* Validador **read-only**: ninguna instrucción DML/DDL sobre la base de datos
  destino.
* **Nunca imprime** password, token, API key, DSN completo ni headers de
  autorización. El bloque BLOCKED documenta la causa sin filtrar el DSN.
* Las conexiones usan únicamente las variables `FEB_SCORE_DATABASE_URL` /
  `DATABASE_URL` del entorno; no se persisten credenciales.
* No se toca la ingesta FEB, la API de comandos ni la política de autenticación.

## Tests

* `tests/postgres/test_season_analytics_validator.py` — **4 tests nuevos**
  (PASS sobre dataset íntegro, FAIL por partido eliminado, FAIL por
  `round_number` nulo/0, y sin DSN → error limpio).

Suite completa: **844 passed, 0 failed** (840 previos + 4 nuevos), sin
regresiones; boundary de arquitectura intacto.

## Producción

```
PRODUCTION VALIDATION: BLOCKED
```

`railway status` → *No linked project found*; `FEB_SCORE_DATABASE_URL` /
`DATABASE_URL` no están en el entorno local; `postgres.railway.internal` no es
resoluble desde el Mac fuera de la red privada de Railway. No se intenta
exponer PostgreSQL, abrir puertos, copiar credenciales ni saltarse la red
privada. El mismo validador se ejecuta con éxito contra PostgreSQL local
sintético con la forma exacta de producción, y el mecanismo queda listo para
ejecutarlo dentro de Railway (comando one-off o `railway connect Postgres` +
DSN) — documentado en el propio script.

No se realizó smoke test contra una URL pública de la API: el proyecto no está
enlazado ni publicado desde el entorno local, por lo que no existe una URL
pública conocida que verificar (mismo estado que 23.5/23.6).

## Limitaciones

* **Grupo ESTE/OESTE no persistido**: el dominio no almacena el grupo de cada
  partido. El validador verifica el equivalente estructural (26×14, 28 equipos
  por jornada, 28 equipos × 26 partidos) pero no puede afirmar el reparto
  exacto 7-7 por grupo. Si el producto necesitara rankings por grupo, habría
  que persistir el grupo en la ingesta.
* **`round_number` en JSONB**: cualquier consulta de integridad de jornadas
  depende de `data->>'round_number'`; una normalización de la columna
  simplificaría futuros checks e índices.
* **Validación en caliente de producción pendiente**: ejecutar
  `validate_season_analytics_production.py` dentro de la red de Railway cuando
  el proyecto esté enlazado.
* **`feb_analytics_valid` es sintético**: los totales absolutos del informe
  (7.800 filas de jugador, etc.) son del dataset local; los invariantes
  relacionales son idénticos a los de producción, pero los números de
  producción solo podrán confirmarse con la ejecución en caliente.

## Recomendaciones

1. Enlazar el proyecto Railway y ejecutar el validador en caliente (one-off
   dentro de la red o túnel `railway connect Postgres` + DSN) — mismo
   mecanismo que 23.3/23.4/23.5/23.6.
2. Si se añade ranking por grupo ESTE/OESTE, persistir el grupo en la ingesta
   y ampliar el bloque MATCHES para validar el reparto 7-7 por jornada.
3. Considerar normalizar `round_number` como columna indexable si las
   consultas por jornada crecen.
4. Mantener el validador como parte del runbook de release (read-only,
   ejecutable sin secretos).

## Commits

* `test(23.7): validate season analytics production readiness` —
  `validate_season_analytics_production.py`, `tests/postgres/
  test_season_analytics_validator.py` (4 tests) y este informe. Sin push.

Los documentos de cierre previos (`FINAL_PROJECT_AUDIT.md`, `FINAL_CLOSURE.md`)
no se modifican: registran el hito técnico alcanzado en su momento (527/527,
validación de producción PASS de aquel alcance) y no contienen afirmaciones que
estas fases de hardening incremental contradigan.