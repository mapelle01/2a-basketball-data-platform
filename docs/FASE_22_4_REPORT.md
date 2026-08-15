# FASE 22.4 — Match Metadata Integrity (round_number real + retry HTTP 429)

**Estado:** COMPLETE (propagación de jornada real + retry 429 + reparación histórica validados)
**Fecha:** 2026-08-15
**Suite de tests:** 604 passed (baseline previo 572 + 32 nuevos, sin regresiones)

## Objetivo

Dos problemas detectados en FASE 22.3:

1. **Jornada persistida incorrecta.** `ingest_match.to_command` hardcodeaba
   `round_number = 1` (decisión heredada de FASE 21.B2). Los 182 matches reales de
   la temporada 2025-2026 quedaron en producción con `round_number=1`, pese a que el
   discovery conoce la jornada real (`MatchRef.round_number`).
2. **Fragilidad ante HTTP 429.** Fetchs seguidos a FEB (y POSTs a nuestra API)
   devolvían `HTTP 429` (rate-limit); en 22.3 se mitigó manualmente con `--delay`.
   FASE 22.4 añade reintento controlado con backoff + `Retry-After`.

No se re-diseñó arquitectura: se reutiliza íntegramente `discover_matches.py` →
`ingest_round.py` → `ingest_match.py`. Los cambios son mínimos y localizados.

## Cambios

### A. Propagación de la jornada real

- `discover_matches.py`: nueva función pública `resolve_round_for_match(season,
  external_id, calendar_html=None)` → jornada real de un match (1 GET al calendario),
  para el CLI manual `--match-id`.
- `ingest_match.py`:
  - `parse_boxscore(..., round_number=None)` guarda `parsed["round_number"]`.
  - `to_command` emite `payload["round_number"]` solo cuando es conocida (>=1).
    Cuando es `None` (fixture/offline o `--match-id` sin jornada resuelta) el
    campo se **omite** (el contrato `create_or_update_match.v1.json` lo declara
    opcional, min 1; enviar 0 rompería la validación). Nunca se inventa una jornada.
  - `run()`: el path real `--match-id` resuelve la jornada vía discovery; si la
    fuente no está disponible, cae a `None` (campo omitido) sin romper el flujo.
- `ingest_round.py`: `process_one` pasa `round_number=ref.round_number` a
  `parse_boxscore` → la jornada del discovery llega al command. **Sin hardcode.**

### B. Retry de HTTP 429 (bounded, stdlib)

- `ingest_match.py`: nueva función `request_with_retry(open_fn, *, max_retries,
  base_backoff, retry_statuses=(429,), sleep=time.sleep)`.
  - Reintenta SOLO status 429 (401/403/404/500/503 propagan al instante, nunca
    se convierten en retries infinitos).
  - Backoff exponencial `base * 2**attempt`; si la respuesta trae `Retry-After`
    (delta-seconds) se respeta ese valor.
  - Acotado: como mucho `max_retries` reintentos, luego re-lanza el `HTTPError`.
  - `open_fn` y `sleep` inyectables → tests offline sin red real.
- Aplicado a las 3 peticiones reales: `fetch_feb_boxscore` (FEB) y
  `post_command` / `post_stats_command` (nuestra API; el 429 observado en 22.3
  vino del path POST).
- Env opcionales documentados: `FEB_MAX_RETRIES` (default 3), `FEB_RETRY_BACKOFF`
  (default 1.0s). No cambian el comportamiento por defecto.

### C. Reparación histórica (`scripts/feb/repair_round_numbers.py`)

La idempotencia backend (`command_id` = UUIDv5 de season|competition|external_id,
`has_processed` → skip) **impide** corregir los históricos vía el comando actual:
el `command_id` no incluye la jornada, así que un replay no puede re-escribirla.
La corrección segura es un UPDATE quirúrgico del JSONB:

```sql
UPDATE matches
   SET data = jsonb_set(data, '{round_number}', '<rn>'::jsonb)
 WHERE external_id = '<id>'
   AND data->>'round_number' IS DISTINCT FROM '<rn>';
```

Propiedades (requisitos del plan): **explícito** (solo toca `data->>'round_number'`),
**idempotente** (guard `IS DISTINCT FROM` → re-ejecutar es no-op), **seguro**
(no borra, no duplica, no crea external_ids nuevos, no toca
`match_player_stats`/`match_team_stats`), **sin secrets** (solo GET público del
calendario + SQL por stdout; la aplicación se hace vía túnel Railway + psql).

El script reutiliza `ingest_season.discover_rounds()` como única fuente de verdad
de la jornada (NO duplica discovery).

## CLI

```bash
# Resumen del mapeo external_id -> jornada real (sin SQL)
python3 scripts/feb/repair_round_numbers.py --season 2025-2026 --dry-run

# Genera el SQL idempotente por stdout
python3 scripts/feb/repair_round_numbers.py --season 2025-2026 > repair_rounds.sql

# Aplicación (túnel Railway + psql, credenciales nunca impresas por el script)
railway connect Postgres --tunnel-only --ssh -P 15433
PGPASSWORD=... psql -h 127.0.0.1 -p 15433 -U postgres -d railway -f repair_rounds.sql
```

Exit codes coherentes con el resto de scripts FEB: `0` OK, `2` configuración
inválida, `3` fuente/parse fallido, `6` inesperado.

## Validación offline (tests)

`tests/ingestion/test_fase_224_round_retry.py` — **22 tests**:

1. `parse_boxscore` guarda `round_number`.
2. `None` cuando no se pasa.
3. Rango de jornadas (1 y 26).
4. `to_command` payload con la jornada real.
5. Payload **omite** `round_number` cuando es desconocida.
6. No hardcodeada a 1 (2, 3, 26).
7. Payload cumple el contrato (`additionalProperties:false`) con jornada incluida.
8. `ingest_round` propaga `ref.round_number` → command (jornada 12).
9. Jornadas distintas (1/2/3) llegan al command desde el discovery.
10. `resolve_round_for_match` contra el fixture del calendario (rounds 1, 2, no-match → None).
11. Retry: éxito tras 1 × 429.
12. Backoff exponencial (1.0 → 2.0).
13. `Retry-After` respetado (duerme 7.0s).
14. Agota retries tras `max_retries` (1 intento + 3 reintentos → re-lanza).
15. `max_retries=0` → sin reintentos, sin sleep.
16-19. 400/401/403/404/500/503 nunca se reintentan (1 intento, sin sleep).
20. Default `time.sleep` no duerme en error no reintentable.

`tests/ingestion/test_repair_round_numbers.py` — **10 tests**:

1. `build_round_map` desde discovery → mapeo external_id→jornada.
2. SQL idempotente y quirúrgico (solo `round_number`; sin stats/DELETE/INSERT).
3. SQL con los valores de jornada correctos.
4. Mapa vacío → sin statements.
5. Determinismo y orden por external_id.
6. CLI `--dry-run`: no emite SQL.
7. CLI emite SQL por stdout (instrucción psql documentada).
8. CLI exit 2 con temporada no soportada.
9. CLI exit 3 con discovery fallido.
10. Reutiliza la lógica existente (no duplica discovery).

Suite completa: **604 passed** (572 previos + 32 nuevos).

## Validación offline del fixture

```
round=1 -> payload.round_number=1
round=2 -> payload.round_number=2
round=3 -> payload.round_number=3
round=None -> 'round_number' in payload: False
resolve 2486849 -> 1
resolve 2486853 -> 2
```

## Validación real controlada (rounds 1-3 + /ready + no dups)

Replay real de las jornadas 1-3 con el pipeline corregido (idempotente):

```
round=1  discovered=7  match_ok=7  stats_ok=7  failed=0
round=2  discovered=7  match_ok=7  stats_ok=7  failed=0
round=3  discovered=7  match_ok=7  stats_ok=7  failed=0
```

- `/ready` OK (schema_version 2, migraciones al día).
- 182 matches, 0 duplicados, 0 matches sin stats (ver auditoría).

El CLI manual `--match-id 2486864 --dry-run` resuelve la jornada real vía
discovery: `round_number=3` (coherente con el calendario real).

## Reparación histórica (producción)

Mapeo generado por discovery real: **182 external_ids** → 26 jornadas × 7.

Distribución real antes/después de la reparación (via `jsonb_set` + guard
`IS DISTINCT FROM`, aplicado por túnel Railway + psql):

| Jornada | Matches |
|---|---|
| 1 .. 26 | 7 cada una (26 × 7 = 182) |

Resultado: los 182 matches quedan con su **jornada real** en `matches.data`. Se
aplicaron 182 `UPDATE` (cada uno `UPDATE 1`).

## Auditoría post-reparación (PostgreSQL de producción)

| Métrica | Antes (22.3) | Después (22.4) |
|---|---|---|
| Matches (external_id numérico) | 182 | 182 |
| Jornadas distintas (`round_number`) | 1 | **26** |
| Player stats (`match_player_stats`) | 4098 | 4098 |
| Team stats (`match_team_stats`) | 364 | 364 |
| Duplicados de matches | 0 | 0 |
| Duplicados de player stats | 0 | 0 |
| Matches sin player stats | 0 | 0 |
| Matches sin team stats | 0 | 0 |
| `/ready` | ready | ready |

Verificación por API (round real):

```
2486849 -> round=1
2486856 -> round=2
2486863 -> round=3
2486900 -> round=8
2487030 -> round=26
```

## Replay tras la reparación (idempotencia + round preservado)

Segunda ejecución de la temporada completa con el pipeline corregido
(`--delay 2`):

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
| Jornadas distintas | 26 | 26 |
| Player stats | 4098 | 4098 |
| Team stats | 364 | 364 |
| Duplicados | 0 | 0 |
| `idempotency` rows | 370 | 370 |

El replay no tocó los valores de jornada ni duplicó registros; 175 matches con
jornada != 1 tras la reparación (182 − 7 de la jornada 1, que era correcta).

## Seguridad

- Los scripts nunca imprimen `FEB_TOKEN`, `FEB_API_KEY`, `DATABASE_URL` ni
  `Authorization`. `repair_round_numbers.py` no usa credenciales de BD (solo GET
  público del calendario + SQL por stdout).
- El SQL se aplica manualmente vía túnel; ninguna credencial quedó en el repo.
- Retry/backoff no loggea secretos (no imprime la petición).

## Limitaciones

- **ESTE only**: OESTE sigue sin soporte (POST ASP.NET; trabajo futuro) → exit 2.
- **Reparación manual por SQL**: la idempotencia backend impide corregir los
  históricos vía el comando; la reparación es un UPDATE quirúrgico documentado y
  idempotente, aplicado con psql bajo control explícito (no automatizado).
- **`--match-id` manual sin calendario disponible**: si el discovery falla, el
  payload omite `round_number` (campo opcional) en lugar de inventar una jornada.
- Retry respeta `Retry-After` en formato delta-seconds; fechas HTTP se ignoran
  (se usa el backoff exponencial como fallback).

## Siguiente fase

1. **Soporte del grupo OESTE** (POST ASP.NET al calendario de FEB).
2. **Leaderboards / proyecciones de temporada** sobre los 182 matches + stats con
   jornada real ya persistida.
3. **Reparación automatizada** de históricos (script de aplicación con
   credenciales gestionadas de forma segura) si se precisa en el futuro.

No se avanza automáticamente a FASE 22.5 sin validación previa.