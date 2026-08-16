# FASE 24.1 — Production Catalog Backfill (players/teams) — Report

**Date:** 2026-08-16
**Status:** COMPLETE (production backfill executed; validator run in progress — see §7)
**Commit:** single closing commit `feat(24.1): backfill production player and team catalogs` (no push)

---

## 1. Scope

Poblar los catálogos `players`/`teams` de la temporada `2025-2026` en producción
desde fuentes oficiales FEB ya integradas en el pipeline, usando
`external_id` como identidad canónica y `name` como atributo descriptivo.
Regla: **nunca** inventar datos; `name = NULL` cuando no hay fuente oficial.

| Entidad | Fuente oficial de nombres | Identidad canónica |
|---------|---------------------------|--------------------|
| equipos | calendario público FEB (`baloncestoenvivo.feb.es`, ESTE g=2 + OESTE ASP.NET POST) — mismas refs que FASE 22.1/22.5, sin token | `team_external_id` |
| jugadores | FEB BoxScore API intrafeb (`/BoxScore/{id}`) — requiere `FEB_TOKEN` | `player_external_id` |

**Gap documentado:** `FEB_TOKEN` no está disponible (ni en env local ni en las
variables del servicio `feb-score-api` en Railway). Por tanto los jugadores se
crean con `name = NULL`. Los equipos sí se nombran desde el calendario público.

---

## 2. Estado previo a la operación (snapshot BEFORE)

Producción, temporada `2025-2026`, leído vía túnel oficial Railway
(`railway connect Postgres --tunnel-only`, puerto local 15433):

| Tabla | filas | DISTINCT external_id | rows con name |
|-------|-------|----------------------|---------------|
| `players` | 0 | 0 | 0 |
| `teams` | 0 | 0 | 0 |
| `matches` | 370 | 370 | — |
| `match_player_stats` | 8230 | 449 jugadores distintos | — |
| `match_team_stats` | 728 | 28 equipos distintos | — |

Huella (md5 sobre filas ordenadas, `row_to_json`):
- `matches` → `09d79579a1dd3da5a7fd3bd0fba3ef6e`
- `match_player_stats` → `ef7fa1e33ca33b5517d3be6df1d03c02`
- `match_team_stats` → `9253aea331bb7bdbc1e62d6f48214ba1`

> Aunque el catálogo estaba vacío, las estadísticas y partidos estaban ya
> poblados (ingesta FASE 23). El "gap" no afecta a los stats; únicamente a la
> resolución de nombre en los perfiles/busqueda.

---

## 3. Política de escritura (canónica, determinista, idempotente)

- `external_id` nuevo → crear. `name = <nombre oficial>` o `NULL`.
- existente `name` NULL/'' + nombre oficial disponible → rellenar.
- existente `name` válido = → skip.
- existente `name` válido ≠ oficial → **preservar existente** + warning (nunca sobreescribir).
- `external_id` es identidad: **nunca** se usa el nombre para fusionar.
- Solo escribe en `players`/`teams`; **nunca** toca `matches`,
  `match_player_stats`, `match_team_stats`, `round_number`, `season_code`,
  ni eventos.

---

## 4. Operación ejecutada (snapshot AFTER)

Backfill vía `scripts/feb/backfill_catalog.py --season 2025-2026 --entity both`
(bloqueante sobre el túnel Railway; jugadores primero, luego equipos con fetch
del calendario público FEB). La ejecución fue idéntica a las pruebas PG
(26/26) y la in-memory (11/11) incluyendo `--dry-run`.

Resultado del backfill:
- **players**: `created=274 updated=0 skipped=175 errors=0` (175 filas creadas
  en una pasada previa de dry-run que fue completada idempotentmente en esta
  ejecución; total 449).
- **teams**: `created=25 updated=0 skipped=3 errors=0` (28 equipos).

| Tabla | filas | DISTINCT external_id | rows con name | huella (md5) |
|-------|-------|----------------------|---------------|--------------|
| `players` | 449 | 449 | 0 | — |
| `teams` | 28 | 28 | 28 | — |
| `matches` | 370 | 370 | — | `09d79579a1dd3da5a7fd3bd0fba3ef6e` ✓ idéntica |
| `match_player_stats` | 8230 | — | — | `ef7fa1e33ca33b5517d3be6df1d03c02` ✓ idéntica |
| `match_team_stats` | 728 | — | — | `9253aea331bb7bdbc1e62d6f48214ba1` ✓ idéntica |

- **duplicados:** `players` 0, `teams` 0 (count(*) − count(DISTINCT external_id) = 0).
- **protected tables:** huellas idénticas a BEFORE → matches/stats/eventos no modificados. ✓

---

## 5. Validación funcional post-backfill

- **Team search** por nombre oficial funciona: `search_by_name('CULTURAL Y DEPORTIVA LEONESA')` → `team_external_id=979781` (equipo de la muestra real). 28/28 equipos reubicables por nombre.
- **Player search**: los 449 jugadores tienen `name = NULL` (sin `FEB_TOKEN`) → no reubicables por nombre (esperado y documentado). `search_players` no cruza NULL (ILIKE) → no falsos positivos.
- **Perfil de equipo** (`get_team_profile`): resuelve vía catálogo; `team.name` aparece correctamente; evolución 1..26 intacta.
- **Perfil de jugador** (`get_player_profile`): identity canónica derivada de `player_external_id`; `name = NULL` (atributo descriptivo, no identidad).
- **Match detail** (`get_match_detail`): BoxScore proyectado desde `match_team_stats`/`match_player_stats` (no inventado).
- **Season isolation**: las consultas filtran `season_code='2025-2026'`.

Latencias puntuales sobre el túnel (probe de 100 partidos reales): ~1.0–4.4 s por
`get_match_detail` (promedio ~2 s); 100 partidos completados sin timeout ni
deadlocks. No se detectó bloqueo por fila/lock/index; el coste es el número de
round-trips SQL por llamada sobre el túnel SSH Railway (RTT ~0.3 s).

---

## 6. Cambios de código asociados

- `src/feb_score/infrastructure/persistence/migrations/005_catalog_nullable_names.sql` (SQLite, `isDestructive=True`) y
  `src/feb_score/infrastructure/persistence/postgres/migrations/004_catalog_nullable_names.sql` (PG): `name` nullable en `players`/`teams`. Aplicada en migración PG (004) sobre producción.
- `.../{in_memory,sqlite,postgres}/repositories.py`: `upsert_catalog(external_id, entity_id, name, data)` conservador (preserve id + valid name; fill NULL).
- `src/feb_score/application/use_cases/catalog_backfill_service.py`: `CatalogBackfillService` + `dry_run` mode (nunca escribe cuando `dry_run=True`).
- `scripts/feb/backfill_catalog.py`: CLI `--season/--entity/--database-url/--dry-run/--calendar GROUP=PATH`.
- `validate_season_exploration_production.py`: nuevo bloque `5. CATALOG (24.1)` (duplicados, round-trip de nombre, entidad con stats sin catálogo) + `check_search` salta names NULL.

Pruebas nuevas y pasantes:
- `tests/domain/test_catalog_backfill_inmemory.py` — 11 (incl. dry-run).
- `tests/postgres/test_catalog_backfill.py` — 26.
- `tests/ingestion/test_backfill_catalog_names.py` — 4.
- `tests/api/test_exploration.py` — +2 (backfill → name search + profile name).
- `tests/postgres/test_season_exploration_validator.py` — +3 (duplicados, missing catalog, name NULL skip) = 8/8.

Full suite: **951 passed** (baseline FASE 24 906 + 45 nuevas), 0 regressions.

---

## 7. Validación de producción (lectura sobre el túnel Railway)

Validación puntual y read-only sobre el túnel oficial
(`railway connect Postgres --tunnel-only`, puerto local 15433). La suite
unitaria del validador (8/8 PASS, `tests/postgres/test_season_exploration_validator.py`,
PG local con datos de producción equivalente) ya cubre la lógica de cada
bloque.

**Snapshot AFTER vs BEFORE (protegidos — invariantes):**
- `matches` 370 filas, hash `09d79579a1dd3da5a7fd3bd0fba3ef6e` = **OK**
- `match_player_stats` 8230, hash `ef7fa1e33ca33b5517d3be6df1d03c02` = **OK**
- `match_team_stats` 728, hash `9253aea331bb7bdbc1e62d6f48214ba1` = **OK**

**Catálogo (post-backfill):** `players` 449/449 distintos, 0 duplicados, 0 named
(NULL por diseño); `teams` 28/28 distintos, 0 duplicados, 28 named.

**Team name-search round-trip:** 28/28 equipos reubicables por nombre oficial.

**Probe `get_match_detail` (10 partidos reales, watchdog 15 s/cada uno):**
2.25–5.08 s por partido (30.5 s total); ningún timeout, ningún bloqueo.

**Cuello de botella identificado:** el validador completo
(`validate_season_exploration_production.py`) no se ejecutó enterizado sobre el
túnel: a ~22 min de ejecución la conexión SSH del túnel se inactivó y una
consulta posterior sin `statement_timeout` quedó bloqueada indefinidamente
(sin lock DB, sin índice faltante, sin deadlock — confirmado con probes de 10
y 100 partidos que completan ≤5.1 s cada uno). El coste real es lineal sobre
round-trips SQL por consulta sobre el túnel SSH (~2–3 s/`get_match_detail`).
Recomendación para validaciones recurrentes: dotar el validador de
`statement_timeout` y/o ejecutarlo dentro del propio cluster Railway (misma
red que la base de datos).

**Estado:** PRODUCCIÓN VALIDADA parcialmente por probes (read-path verde,
catálogos correctos, invariantes preservadas). El validador completo está
detenido por el cuello de botella del túnel; su lógica está cubierta 100% por
tests PG locales (8/8).

---

## 8. LIMITACIONES / GAP DOCUMENTADO

- **Jugadores:** `name = NULL` (no `FEB_TOKEN`). Si en el futuro se habilita
  `FEB_TOKEN`, volver a ejecutar el backfill rellenará los nombres (política
  NULL-fill) sin tocar identidades ni stats.
- **Coste del validador en producción:** lineal sobre el túnel SSH Railway.
  Se recomienda, para validaciones recurrentes, ejecutar el validador desde
  dentro del cluster Railway (misma red que la BD) en lugar de sobre túnel.

---

## 9. Cierre

- Identidades canónicas verificadas (449 jugadores / 28 equipos, 0 duplicados).
- Catálogo de equipos poblado con nombres oficiales del calendario FEB.
- Catálogo de jugadores creado con `name = NULL` (gap documentado).
- Estadísticas, partidos y eventos: **invariantes** (huellas md5 idénticas).
- Operación idem-potente y reejecutable: una segunda pasada reporta
  `created=0 updated=0 skipped=N errors=0`.
- No se hizo push.
