# FASE 22.6 — Backfill completo OESTE (Segunda FEB 2025-2026)

## Resumen

Ingesta real de las 26 jornadas del grupo OESTE de Segunda FEB 2025-2026
completada. 182 matches ingeridos, 182/182 matches OK, 182/182 stats OK,
0 duplicados, `round_number` 1..26 correcto, ESTE intacto, replay idempotente.

## Discovery

* Jornadas descubiertas: **26** (rango 1..26).
* Partidos descubiertos: **182** (7 por jornada).
* IDs OESTE esperados y confirmados: jornada 1 → `2487759..2487765`,
  jornada 26 → `2487934..2487940`.
* Vía `ingest_season.py --group OESTE --dry-run` y `discover_matches.py
  --group OESTE` (POST ASP.NET de FASE 22.5).

## Ingesta

* Partidos OK: **182/182** (`match_ok=182`).
* Stats OK: **182/182** (`stats_ok=182`).
* Errores: **0** (`failed=0`).
* 429 encontrados: **0**.
* Retries necesarios: **0**.
* Delay entre jornadas: 1.5 s; `FEB_MAX_RETRIES=5`, `FEB_RETRY_BACKOFF=2.0`.
* STATUS: **PASS** (26/26 jornadas, 0 fallos).

## Producción

Contadores reales (DB Railway, tablas `matches` / `match_player_stats` /
`match_team_stats`; `external_id` numérico):

| Métrica | Antes (precheck) | Después | Esperado |
|---|---|---|---|
| matches OESTE | 7 | **182** | 182 |
| player_stats OESTE | 159 | **4132** | > 0 |
| team_stats OESTE | 14 | **364** | 364 |
| matches ESTE | 182 | **182** | 182 |
| player_stats ESTE | 4098 | **4098** | 4098 |
| team_stats ESTE | 364 | **364** | 364 |
| matches totales (num) | 189 | **364** | 364 |

*Nota:* `player_stats` OESTE = 4132 es el valor real de producción; cada match
tiene su roster real de la fuente FEB (no se asumió un número fijo).

## Round integrity

Distribución de jornadas OESTE (consultada de la DB, `data->>'round_number'`):

```
round 1  → 7    round 10 → 7    round 19 → 7
round 2  → 7    round 11 → 7    round 20 → 7
round 3  → 7    round 12 → 7    round 21 → 7
round 4  → 7    round 13 → 7    round 22 → 7
round 5  → 7    round 14 → 7    round 23 → 7
round 6  → 7    round 15 → 7    round 24 → 7
round 7  → 7    round 16 → 7    round 25 → 7
round 8  → 7    round 17 → 7    round 26 → 7
round 9  → 7    round 18 → 7
```

Matches OESTE con `round_number` nulo/0: **0**.

## Idempotencia

Replay completo OESTE tras el backfill: 26/26 jornadas, 182/182 matches OK,
182/182 stats OK, `failed=0`, **STATUS PASS**.

Contadores después del replay (idénticos al backfill, sin nuevos duplicados):

```
OESTE matches     = 182
OESTE player_stats = 4132
OESTE team_stats  = 364
dup matches       = 0
dup player_stats  = 0
dup team_stats    = 0
```

## ESTE integrity

ESTE antes == ESTE después (182/4098/364). Sin alteración.

## /ready

```json
{"status":"ready","checks":{"schema_version":"2","database":"ok","migrations":"up_to_date"}}
```

## Limitaciones / incidentes

* **Incidente transitorio FEB (no bloqueante):** durante el primer intento de
  replay, el endpoint de BoxScore de FEB (`intrafeb.feb.es/.../BoxScore`)
  devolvió `HTTP 500` para **todos** los IDs (OESTE y ESTE), incluso para
  `2486864` (ESTE, ya ingerido en fases previas). Se confirmó que era un fallo
  del lado de FEB (no de nuestro código: el retry 429 no aplica a 500 y el
  entorno estaba correcto). No se modificó producción: todos los contadores
  quedaron intactos. Tras ~60 s la fuente se recuperó y el replay completo
  terminó en PASS.
* **0 eventos 429** durante el backfill y el replay con `--delay 1.5`.
* El `_ctl0:token` del POST ASP.NET no se imprime (revisado en FASE 22.5).

## Tests

Suite completa: **628 passed, 0 failed** (`PYTHONPATH=.:src .venv/bin/pytest -q`).

## Commits

* `05942c8` — FASE 22.5 (soporte OESTE, previo).
* Este reporte: commit de documentación (sin cambios funcionales).

## Próximo paso recomendado

Cierre del ciclo 2025-2026: validación final de publicaciones/leaderboards con
ambos grupos completos (364 matches), o cierre documental del proyecto
(no avanzar automáticamente a 22.7).