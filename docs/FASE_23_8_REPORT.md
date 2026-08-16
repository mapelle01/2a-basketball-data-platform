# FASE 23.8 — Railway Production Validation

## Resumen

Fase de **validación real de producción**: se enlazó el proyecto Railway
`feb-score-production` (entorno `production`), se accedió a la PostgreSQL real
mediante el **mecanismo oficial** de Railway CLI (`railway connect Postgres
--tunnel-only`, túnel SSH TCP), se ejecutó el validador read-only existente
`validate_season_analytics_production.py` y se obtuvo:

```
PRODUCTION VALIDATION: PASS
```

sobre los datos reales de la temporada `2025-2026`. No se modificaron datos,
no se aplicaron migraciones, no se expusieron credenciales y no se hizo bypass
de la red privada (se usó el túnel oficial). Se añadió **1 test** para cubrir
los dos hallazgos reales de producción que exigieron ajustar el validador
(alcance por competición del bloque MATCHES y tolerancia relativa del
round-trip de `minutes_per_game`).

## Estado de partida

Working tree limpio, HEAD `68e2398` (`test(23.7): validate season analytics
production readiness`), **844 tests passing**. Railway CLI 5.41.2 autenticado
(`espanadeantes@gmail.com`), proyecto sin enlazar (`railway status` → *No
linked project found*).

## FASE 1-2 — Inspección y servicios

* `railway list` → proyectos `feb-score-production` y `pretty-motivation`.
* `railway link --project feb-score-production` → entorno `production`,
  servicios `Postgres` y `feb-score-api`.
* `railway link --project feb-score-production --service feb-score-api` →
  `feb-score-api` **Online**, URL pública
  `https://feb-score-api-production.up.railway.app`.
* Variables (solo existencia, sin imprimir): `FEB_SCORE_DATABASE_URL` presente
  en el servicio `feb-score-api`; `DATABASE_URL` no. Base de datos destino del
  DSN: `railway`.

## FASE 3 — Acceso privado (mecanismo oficial)

* `railway run --service feb-score-api -- python3 …`: **no** resuelve
  `postgres.railway.internal` (gaierror) — solo inyecta variables en local.
  Se documenta el bloqueo de este mecanismo y **no** se intenta ningún hack.
* Mecanismo oficial disponible: `railway connect Postgres --tunnel-only -P
  54329` (túnel SSH TCP de Railway CLI al servicio `Postgres`). El validador se
  ejecuta en local contra la PostgreSQL real a través de ese túnel. El DSN se
  construye desde la salida del túnel sin volcarlo a la salida; no se imprimen
  credenciales.

## FASE 4 — Validación read-only (producción real)

`validate_season_analytics_production.py` para `season_code=2025-2026`
(READ-ONLY). Resultado: **PASS — los 6 bloques**.

| Bloque | Producción real | Resultado |
|---|---|---|
| MATCHES | 364 (`segunda-feb`), 0 dups, 26×14, 28 equipos/jornada, round 1..26 | PASS |
| PLAYER AGGREGATES | 449 jugadores, 8.230 filas; SUM(points/rebounds/assists/steals/blocks/turnovers/minutes) == raw | PASS |
| TEAM AGGREGATES | 28 equipos, 728 filas; games_played=728, wins=losses=364; SUMs == raw | PASS |
| LEADERBOARDS | 7 métricas jugador + 4 equipo; ranks 1..N, sin dups, determinismo, aislamiento, coherencia | PASS |
| METRICS | 449 + 28; round-trips per-game, win%, diff, div-by-zero | PASS |
| INTEGRIDAD | sin NULLs, sin round_number 0/null, sin contaminación de otras temporadas | PASS |

Datos reales confirmados: `match_player_stats` 8.230 filas, `match_team_stats`
728 filas, `matches` 364 de liga + 6 ajenas.

## Incidencias (hallazgos reales) y ajustes del validador

1. **`matches` con 370 filas (no 364)**: la tabla contiene 6 filas ajenas a la
   liga bajo `2025-2026` (`smoke-comp`=5, `feb-comp`=1) sin `match_team_stats`
   ni impacto en analíticas (artefactos de pruebas de ingesta). El bloque
   MATCHES ahora valida la competición autoritativa `segunda-feb` (la liga) y
   reporta las filas ajenas como **diagnóstico informativo** (`[DIAG] … 6 filas
   de otras competiciones`), no como blocker. No se modificó producción.
2. **`minutes_per_game` round-trip**: los minutos reales tienen decimales y el
   read model los calcula con `CAST(minutes AS REAL)` (precisión simple,
   `repositories.py:836`), por lo que `per_game × games_played` difiere del
   total en ~1e-7 relativo. El validador usa ahora **tolerancia relativa 1e-5**
   para todos los round-trips per-game (jugador y equipo). No es un bug de
   datos; es precisión de lectura documentada.

Estos dos ajustes son correcciones de precisión/alcance del **validador**
(justificadas por hallazgos reales), no cambios de contrato ni de
funcionalidad.

## FASE 5 — API smoke test

La imagen desplegada de `feb-score-api` es **anterior a FASE 23.5**: los 6
endpoints de analytics responden **404** en la URL pública y `/openapi.json`
404 (el despliegue sigue sirviendo la ingesta de comandos — visible en logs).
Por tanto el smoke test contra el despliegue público de esos endpoints **no es
posible** (no existen en la imagen desplegada).

Validación suplementaria: los 6 endpoints se probaron a nivel HTTP con el
código del working tree contra **los datos reales de producción** a través del
túnel oficial (solo GET, sin migración, sin auth de producción):

* `/v1/seasons/2025-2026/players` → **200**, count=449, envelope correcto.
* `/v1/seasons/2025-2026/players/leaderboards?metric=points` → **200**, rank 1..N.
* `/v1/seasons/2025-2026/players/leaderboards?metric=games_played` → **200**.
* `/v1/seasons/2025-2026/players/metrics` → **200**, 449 items.
* `/v1/seasons/2025-2026/teams` → **200**, count=28.
* `/v1/seasons/2025-2026/teams/leaderboards?metric=classification|points_for|point_difference|win_percentage` → **200**, ranks 1..N.
* `/v1/seasons/2025-2026/teams/metrics` → **200**, 28 items.
* Errores controlados: `metric=bogus`/`metric=wins`/`metric=points_per_game` →
  **400 INVALID_PARAMETER**; `limit=0`/`limit=501` → **400 INVALID_PARAMETER**;
  `limit=abc` → **400 INVALID_BODY**; `season 2099-2100` y `2024-2025` → **200**
  con `count=0` (temporada vacía, sin stack traces ni secretos).
* `metric=wins` (usado como ejemplo en el enunciado) no es una métrica
  soportada de leaderboard de equipo (el conjunto es
  classification/points_for/point_difference/win_percentage) → 400 controlado,
  documentado.

Solo GET; ningún POST/PUT/PATCH/DELETE.

## FASE 6 — Health / Readiness (despliegue público)

* `GET /health` → **200** `{"status":"ok"}`.
* `GET /ready` → **200**
  `{"status":"ready","checks":{"schema_version":"2","database":"ok","migrations":"up_to_date"}}`.

Hallazgo: el despliegue espera schema **v2** y la base está en v2 — coherente.
El código HEAD espera v3: PostgreSQL de producción **no tiene aplicada la
migración `003_analytics_indexes`** (índices season-first de 23.6). La
migración es aditiva y no destructiva, pero **no se aplicó** en esta fase
(validación); queda como paso previo a desplegar el código HEAD. Sin
credenciales en las respuestas.

## FASE 7 — Resultado

```
PRODUCTION VALIDATION: PASS
```

Basado en la ejecución real del validador contra la PostgreSQL real de Railway
(túnel oficial). No se convirtió ningún BLOCKED/FAIL en PASS con datos
sintéticos: los PASS provienen de datos reales (364 partidos, 8.230 player
stats, 728 team stats, 449 jugadores, 28 equipos).

## Seguridad

* Conexión solo mediante `railway connect --tunnel-only` (mecanismo oficial);
  el DSN se construyó desde la salida del túnel sin volcarlo. Nunca se
  imprimieron `DATABASE_URL`/`FEB_SCORE_DATABASE_URL`, passwords, tokens, API
  keys ni Authorization headers.
* Validador 100% read-only; únicamente GET en HTTP.
* No se modificaron datos de producción; no se aplicaron migraciones; no se
  alteró configuración; no se crearon proyecto/base de datos.
* El túnel se cerró al terminar.

## Tests

* `tests/postgres/test_season_analytics_validator.py`: **+1 test** —
  `test_validator_ignores_stray_competition_rows_and_rounds_minutes` (filas
  ajenas de otra competición bajo la misma temporada no rompen el bloque
  MATCHES; minutos fraccionarios pasan el round-trip con tolerancia relativa).

Suite completa: **845 passed, 0 failed** (844 previos + 1 nuevo), sin
regresiones.

## Limitaciones

* **Despliegue desactualizado**: la imagen pública de `feb-score-api` no
  incluye los endpoints de analytics (404). La validación HTTP se hizo contra
  datos reales a través del túnel con el código del working tree; el smoke test
  contra el despliegue público queda pendiente de una nueva deploy.
* **Migración 003 no aplicada en producción** (schema v2): los índices
  season-first aún no existen en la base real; no afectan a la corrección de
  los resultados (validados con Seq Scan) pero sí al rendimiento al crecer el
  volumen. Aplicar `003` es no destructivo.
* **6 filas ajenas en `matches`** (`smoke-comp`=5, `feb-comp`=1): pendientes de
  limpieza en producción; no se modificaron (fuera de alcance de esta fase).
* **Grupo ESTE/OESTE no persistido**: el validador verifica el equivalente
  estructural (26×14, 28 equipos por jornada), no un reparto 7-7 por grupo
  (limitación ya documentada en 23.7).

## Recomendaciones

1. Desplegar el código HEAD (23.5-23.8) sobre el servicio `feb-score-api` y
   **aplicar previamente la migración aditiva `003_analytics_indexes`**
   (índices season-first); tras ello re-ejecutar `/ready` (esperado schema v3)
   y el smoke test de los 6 endpoints contra la URL pública.
2. Limpiar las 6 filas ajenas de `matches` en producción (fuera de esta fase).
3. Mantener el validador en el runbook de release; el mecanismo
   `railway connect Postgres --tunnel-only` queda verificado como vía oficial
   de validación.

## Commits

* `test(23.8): validate season analytics against production` — ajustes del
  validador (alcance por competición + tolerancia relativa de per-game), test
  nuevo, `docs/FASE_23_8_REPORT.md` y addenda documental en
  `FINAL_PROJECT_AUDIT.md` / `FINAL_CLOSURE.md`. Sin push.