# FASE 22.3 — Season Backfill (report)

**Estado:** COMPLETE (backfill real de la temporada 2025-2026 validado + replay idempotente)
**Fecha:** 2026-08-15
**Suite de tests:** 572 passed (baseline previo 557 + 15 nuevos, sin regresiones)

## Objetivo

Permitir ejecutar automáticamente **toda la temporada 2025-2026 del grupo ESTE**,
jornada por jornada, reutilizando exclusivamente la arquitectura existente
(`discover_matches.py` → `ingest_round.py` → `ingest_match.py`). No se diseñó una
segunda arquitectura: el nuevo componente es únicamente un **orquestador de temporada**.

## Arquitectura

```
discover_matches.py (22.1)
   |  enumeración determinista de jornadas (1 GET calendario + parse_calendar)
   v
ingest_round.py (22.2)
   |  por jornada: discovery + ingesta individual (reutiliza ingest_match.py)
   v
ingest_season.py (22.3, NUEVO orquestador)
   |  bucle de jornadas + aislamiento + resumen agregado
   v
FEB (intrafeb BoxScore) -> API (create_or_update_match / upsert_match_stats)
   v
PostgreSQL (matches / match_player_stats / match_team_stats)
```

El runner `ingest_season.py` delega 100% de la ingesta en `ingest_round.run_round`
(que a su vez reutiliza `ingest_match.*`). El único uso directo de
`discover_matches` es la enumeración determinista de las jornadas disponibles
(no se asume ciegamente "26"): un único GET + `parse_calendar` → rango real.

## CLI

```bash
# Temporada completa (grupo ESTE por defecto)
python3 scripts/feb/ingest_season.py --season 2025-2026

# Rango de jornadas (validación incremental)
python3 scripts/feb/ingest_season.py --season 2025-2026 --round-from 1 --round-to 3

# Dry-run (descubre + reporta volumen; NO POST, no toca Production)
python3 scripts/feb/ingest_season.py --season 2025-2026 --round-from 1 --round-to 3 --dry-run

# Espaciado entre jornadas (rate-limit real de FEB BoxScore: HTTP 429 en fetchs seguidos)
python3 scripts/feb/ingest_season.py --season 2025-2026 --delay 4
```

- `--group` default `ESTE`. OESTE NO soportado (requiere POST ASP.NET; trabajo futuro)
  y se rechaza con exit 2.
- `--round-from` / `--round-to` filtran las jornadas realmente descubiertas (inclusive).

## Exit codes

| Código | Significado |
|---|---|
| `0` | Todas las jornadas procesadas (failed global = 0) |
| `1` | Al menos un fallo de ingestión (match o jornada) |
| `2` | Error de configuración/argumentos (grupo OESTE, rango inválido, round < 1) |
| `3` | Discovery de temporada fallido (calendario no disponible/parseable) |
| `6` | Error inesperado |

## Descubrimiento de jornadas

- Determinista: 1 GET al calendario + `parse_calendar` → `{round: [MatchRef]}`.
- No se asume un número fijo: se reportan las jornadas realmente descubiertas.
- Jornadas que no existen no se inventan; si una jornada falla, se registra y se
  continúa con la siguiente cuando es seguro.

Resultado real del discovery (dry-run global):

```
season=2025-2026
group=ESTE
rounds=26
matches=182
```

## Aislamiento de errores

- Un partido fallido → registrado por `run_round`; la jornada continúa.
- Una jornada fallida → registrada; la siguiente jornada continúa.
- Nunca se aborta la temporada por un fallo local.

Evidencia real: en el backfill, las jornadas 18-19 sufrieron `HTTP 429`
(rate-limit de FEB). El runner continuó con las jornadas 20-26 (todas OK) y
el resumen reportó los 6 fallos; un re-run de 18-19 los resolvió (transitorios).

## Dry-run real

```
FASE 22.3 — SEASON BACKFILL (DRY RUN)
season=2025-2026
group=ESTE
rounds=3
matches=21
rounds: 1, 2, 3
DRY_RUN
POST disabled
```

Y global: `rounds=26 matches=182`, sin POST.

## Tests

`tests/ingestion/test_ingest_season.py` — **15 tests** offline (mocks/fakes, sin
FEB real, sin Production):

1. Procesa varias jornadas.
2. Respeta `round-from`.
3. Respeta `round-to`.
4. Agrega correctamente los resultados.
5. Continúa después de una jornada parcialmente fallida.
6. Dry-run no hace POST.
7. Calcula correctamente los totales.
8. Exit code correcto (0 éxito / 1 fallos).
9. No imprime secretos (ni en excepciones de jornada).
10. CLI exit 2 con grupo OESTE.
11. CLI exit 2 con rango inválido (from > to).
12. CLI exit 2 con round-from < 1.
13. CLI exit 3 cuando el discovery falla (SourceError).
14. Reutiliza la lógica existente (no duplica funciones de ingestión).
15. Aislamiento de una jornada con excepción (continúa).

Validación de la suite completa: **572 passed** (557 previos + 15 nuevos).

## Backfill real — temporada 2025-2026 (grupo ESTE)

### Ingesta real 1-3 (validación incremental)

```
round=1  discovered=7  match_ok=7  stats_ok=7  failed=0
round=2  discovered=7  match_ok=7  stats_ok=7  failed=0
round=3  discovered=7  match_ok=7  stats_ok=7  failed=0
STATUS: PASS
```

### Backfill completo (26 jornadas)

Primera ejecución: `rounds_discovered=26 matches_discovered=182 matches_ok=176
stats_ok=176 failed=6` (6 fallos `HTTP 429` en jornadas 18-19, transitorios).

Re-run de 18-19: `14/14 OK, failed=0`. Tras esto la temporada completa quedó
procesada: **182/182** (posterior replay completo lo confirmó: `STATUS: PASS`).

## Auditoría post-backfill (PostgreSQL de producción, túnel Railway)

| Métrica | Valor |
|---|---|
| Matches totales (external_id numérico) | 182 |
| Player stats (`match_player_stats`) | 4098 |
| Team stats (`match_team_stats`) | 364 |
| Duplicados de matches | 0 |
| Duplicados de player stats | 0 |
| Matches sin player stats | 0 |
| Matches sin team stats | 0 |
| `/ready` | ready (schema_version 2, migraciones al día) |

## Idempotencia / replay

Segunda ejecución de la temporada completa (`--delay 4`):

```
rounds_discovered=26
rounds_processed=26
matches_discovered=182
matches_ok=182
stats_ok=182
failed=0
STATUS: PASS
exit=0
```

Comparación antes/después del replay:

| Métrica | Antes | Después |
|---|---|---|
| Matches | 182 | 182 |
| Player stats | 4098 | 4098 |
| Team stats | 364 | 364 |
| Duplicados | 0 | 0 |

La idempotencia la proveen los comandos backend existentes (`command_id` UUIDv5 +
`idempotency` + `ON CONFLICT DO UPDATE`); el runner no añade mecanismos alternativos.
Ejecutar dos veces no duplica registros. `idempotency` rows en producción: 370
(182 matches + 182 stats + registros previos de fases anteriores).

## Limitaciones

- **ESTE only**: el grupo OESTE no es alcanzable vía GET (dropdown ASP.NET →
  `__doPostBack`); requiere POST ASP.NET al calendario. Rechazado con exit 2.
  Trabajo futuro.
- **Rate-limit FEB (HTTP 429)**: fetchs BoxScore seguidos devuelven 429. Se
  resolvió con `--delay N` entre jornadas (default 0, no cambia comportamiento
  previo). Documentado en el CLI.
- **`round_number` en la DB**: los 182 matches quedan almacenados con
  `round_number=1` en `matches.data` porque `ingest_match.to_command` hardcodea
  `round_number = 1` (decisión de FASE 21.B2, heredada). El `command_id`
  (UUIDv5 de season|competition|external_id) no incluye la jornada y la
  idempotencia evita re-propagarla en un replay, por lo que NO se corrigió
  retroactivamente (evitar tocar 22.1/22.2 innecesariamente). La jornada real se
  conoce en el discovery (`MatchRef.round_number`) y se usa para el resumen y la
  cobertura; la persistencia del round correcto queda como trabajo futuro
  (FASE 22.4 candidata).
- `FEB_BOX_SCORE_BASE_URL`: si se define con `baloncestoenvivo.feb.es/api/BoxScore`
  provoca HTTP 500 (endpoint incorrecto). El default de código
  (`intrafeb.feb.es/LiveStats.API/api/v1/BoxScore`) es el correcto; las
  ejecuciones reales usaron el default (unset de la variable).

## Siguiente fase

Recomendaciones basadas en los resultados reales:

1. **Persistir el `round_number` real** en la ingesta (propagar
   `MatchRef.round_number` → `to_command`), corrigiendo la limitación detectada
   en esta fase; requeriría una estrategia para los datos ya existentes.
2. **Soporte del grupo OESTE** (POST ASP.NET al calendario de FEB).
3. **Reintento con backoff de HTTP 429** dentro de `ingest_round`/`ingest_season`
   (evitar reintentos manuales).
4. **Leaderboards / proyecciones de temporada** sobre los 182 matches + stats ya
   persistidos (p.ej. estadísticas de equipo/jugador agregadas por temporada).

No se avanza automáticamente a FASE 22.4 sin validación previa.