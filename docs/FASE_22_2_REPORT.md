# FASE 22.2 — Bulk Ingestion Runner (report)

**Estado:** COMPLETE (validación real contra producción superada)
**Fecha:** 2026-08-15
**Suite de tests:** 557 passed (baseline previo 545 + 12 nuevos, sin regresiones)

## Objetivo

Implementar el runner de ingesta masiva por jornada (`ingest_round.py`) que conecte
el discovery de partidos de FASE 22.1 (`discover_matches.py`) con la ingesta
individual ya existente de FASE 21.B2/B3 (`ingest_match.py`), produciendo un
resultado agregado por jornada con aislamiento de errores por partido.

## Arquitectura

El runner es **solo orquestador**: no duplica ninguna lógica de ingesta ni de
discovery. Reutiliza íntegramente:

- `discover_matches.discover_matches(season, round_) -> List[MatchRef]` (FASE 22.1).
- `ingest_match.fetch_feb_boxscore`, `parse_boxscore`, `to_command`,
  `to_stats_command`, `post_command`, `post_stats_command` (FASE 21.B2/B3).

Flujo por partido:

```
MatchRef -> fetch_feb_boxscore -> parse_boxscore -> to_command
         -> post_command (create_or_update_match) -> to_stats_command
         -> post_stats_command (upsert_match_stats)
```

Un fallo en un partido **no aborta la jornada**: se registra el error sanitizado
y se continúa con el siguiente. Al final se imprime el resumen agregado.

## Archivos

| Archivo | Rol |
|---|---|
| `scripts/feb/ingest_round.py` | Runner (nuevo, FASE 22.2) |
| `tests/ingestion/test_ingest_round.py` | 12 tests offline (nuevo) |
| `docs/FASE_22_2_REPORT.md` | Este reporte |
| `scripts/feb/discover_matches.py` | Discovery (FASE 22.1, reutilizado) |
| `scripts/feb/ingest_match.py` | Ingesta individual (FASE 21.B2/B3, reutilizado) |

## CLI

```
python3 scripts/feb/ingest_round.py --season 2025-2026 --round 1
python3 scripts/feb/ingest_round.py --season 2025-2026 --round 1 --dry-run
```

- `--season`: código de temporada (2025-2026).
- `--round`: número de jornada (1-based).
- `--group`: por defecto `ESTE`. OESTE NO está soportado (requiere POST ASP.NET;
  trabajo futuro) y se rechaza con exit 2.
- `--dry-run`: descubre y lista los partidos; NO hace POST ni requiere credenciales.

## Exit codes

| Código | Significado |
|---|---|
| `0` | Todos los partidos procesados correctamente |
| `1` | Al menos un fallo de ingestión |
| `2` | Error de configuración/argumentos |
| `3` | Discovery fallido |
| `6` | Error inesperado |

## Estrategia de errores

- Aislamiento por partido: `try/except` en `process_one`, sin abortar la jornada.
- Los errores se **sanitizan** (`_sanitize_error`): cualquier aparición del token
  o de la API key en el mensaje se sustituye por `[redacted]` (máx 300 chars).
- Nunca se imprime `FEB_TOKEN`, `FEB_API_KEY` ni cabeceras `Authorization`.

## Dry-run real (jornada 1, 2025-2026)

```
FASE 22.2 DRY RUN
season=2025-2026
round=1
group=ESTE
discovered=7
2486849 SPANISH BASKETBALL ACADEMY - LOBE HUESCA LA MAGIA | 2025-10-04T00:00:00+01:00
... (7 partidos, IDs 2486849-2486855)
POST disabled
exit=0
```

## Tests (offline, sin FEB real ni producción)

`tests/ingestion/test_ingest_round.py` — 12 tests con mocks/fakes:

1. Discovery devuelve N partidos (delega en `DM.discover_matches` con season/round).
2. Todos los partidos se procesan.
3. Un fallo de un partido no impide procesar los siguientes.
4. Agregación correcta de resultados (match OK pero stats falla cuenta como fallo).
5. Exit code 0 en éxito.
6. Exit code 1 con fallos.
7. Dry-run no realiza ningún POST ni fetch.
8. Los secretos nunca aparecen en la salida (ni en errores).
9. El runner reutiliza la lógica existente (no define fetch/parse/to_command/
   post_command propios).
10. Exit 2 con grupo no soportado (OESTE).
11. Exit 2 con season no soportada.
12. Exit 3 cuando el discovery falla (SourceError).

Validación de la suite completa: **557 passed** (545 previos + 12 nuevos).

## Ingesta real — jornada 1 (2025-2026, grupo ESTE)

```
2486849 OK ... 2486855 OK
discovered=7
match_ok=7
stats_ok=7
failed=0
exit=0
```

### Validación en producción (DB PostgreSQL de Railway)

| Métrica | Resultado |
|---|---|
| Matches jornada 1 en producción | 7 (external_ids 2486849-2486855) |
| Player stats (`match_player_stats`) | 161 filas (22-24 por partido) |
| Team stats (`match_team_stats`) | 14 filas (2 por partido) |
| Duplicados de matches | 0 |
| Duplicados de player stats | 0 |
| `/ready` | `{"status":"ready","schema_version":2,"migrations":"up_to_date"}` |

### Replay / idempotencia

Segunda ejecución de la jornada 1 (mismas credenciales):

```
2486849 OK ... 2486855 OK
discovered=7, match_ok=7, stats_ok=7, failed=0
exit=0
```

Conteos tras el replay: **7 matches / 161 player stats / 14 team stats, 0 duplicados**
→ la idempotencia la proveen los comandos backend existentes (`create_or_update_match`
y `upsert_match_stats`); el runner no añade estrategia nueva. Ejecutar dos veces no
duplica registros.

## Limitaciones

- Solo grupo **ESTE** alcanzable (FASE 22.1). OESTE requiere POST ASP.NET al
  calendario; trabajo futuro, rechazado con exit 2.
- `FEB_BOX_SCORE_BASE_URL`: durante la validación se detectó que una variable de
  entorno con valor `https://baloncestoenvivo.feb.es/api/BoxScore` provocaba HTTP
  500 en todos los partidos. El default de código
  (`https://intrafeb.feb.es/LiveStats.API/api/v1/BoxScore`) es el endpoint
  correcto y verificado. La jornada se procesó con el default (variable no
  seteada / unset).
- La hora individual del partido se completa con el `starttime` del BoxScore; el
  discovery usa fecha de jornada a 00:00 +01:00.

## Siguiente paso

FASE 22.3 (por definir): candidatos naturales — soporte del grupo OESTE, ingesta
de una temporada completa (26 jornadas), o validación de duración real en BoxScores.
No se avanza automáticamente sin validación previa.