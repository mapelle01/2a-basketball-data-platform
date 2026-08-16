# FASE 23.9 — Production Deploy & Public Analytics Smoke Test

## Status

```
COMPLETE — PUBLIC ANALYTICS API VALIDATED
```

Se desplegó el código HEAD sobre el servicio existente `feb-score-api`
(proyecto `feb-score-production`, entorno `production`) mediante el mecanismo
oficial del repositorio (`railway up`, Railway builds desde el Dockerfile —
misma estrategia que el workflow `deploy-production.yml`), se aplicó la
migración aditiva `003_analytics_indexes` con el sistema de migraciones del
proyecto y los 6 endpoints públicos de FASE 23.5 responden **200** contra datos
REALES de producción. Validación end-to-end:

```
Production DB: PASS
Production deployment: PASS
Public analytics API: PASS
End-to-end analytics: PASS
```

## Deployment

* **Servicio:** `feb-score-api` (proyecto `feb-score-production`, entorno
  `production`, URL pública `https://feb-score-api-production.up.railway.app`).
* **Commit desplegado:** `2721606` (código HEAD de la rama `main`, árbol
  limpio).
* **Mecanismo oficial:** `railway up --service feb-score-api --environment
  production` (Railway builds desde `Dockerfile`; `railway.toml`: healthcheck
  `/ready`, `overlapSeconds=0`, `restartPolicyType=ALWAYS`). Sin push a git,
  sin servicio/BD nueva, sin cambios de dominio público ni secrets.
* **Resultado:** deployment exitoso. `/ready` → 200 con
  `schema_version: "3"`, `database: "ok"`, `migrations: "up_to_date"` en ~40s
  tras el lanzamiento.

## Migration

* **`003_analytics_indexes.sql`** localizado en
  `src/feb_score/infrastructure/persistence/postgres/migrations/` y registrado
  como versión 3 (`analytics_indexes`) en `MIGRATIONS` de
  `postgres/connection.py`.
* **Contenido (verificado):** aditiva, idempotente (`IF NOT EXISTS`), no
  destructiva, exclusivamente índices analytics:
  `idx_player_stats_season_scan(season_code, player_external_id)` y
  `idx_team_stats_season_scan(season_code, team_external_id)`.
* **Aplicación:** mediante el mecanismo oficial del proyecto (runner de
  migraciones `PgDatabase.migrate()`, el mismo que ejecuta el servidor al
  arrancar) a través del túnel oficial de Railway CLI. Solo aplicó la migración
  pendiente (versión 3). Re-ejecución idempotente (no-op).
* **Antes:** schema_version 2, sin índices season_scan. **Después:**
  schema_version 3, ambos índices presentes, `schema_version` registra
  `(1, initial)`, `(2, match_stats)`, `(3, analytics_indexes)`.
* Sin `DROP`, sin `DELETE`, sin modificar filas.

## Production (datos reales)

* 364 partidos `segunda-feb` (`2025-2026`).
* 449 jugadores.
* 28 equipos.
* 8.230 player stats.
* 728 team stats.

## API — Smoke test público (6 endpoints)

Todos sobre la URL pública, solo GET, sin autenticación (endpoints públicos por
diseño), sin secretos en las respuestas:

| Endpoint | HTTP | count | Validación |
|---|---|---|---|
| `/v1/seasons/2025-2026/players` | 200 | 449 | envelope correcto (`season_code`, `count`, `items`) |
| `/v1/seasons/2025-2026/players/leaderboards?metric=points` | 200 | 449 | rank 1 existe, ranks consecutivos, IDs válidos, valores coherentes |
| `/v1/seasons/2025-2026/players/metrics` | 200 | 449 | `games_played` ≥ 0, per-game ≥ 0 |
| `/v1/seasons/2025-2026/teams` | 200 | 28 | envelope correcto |
| `/v1/seasons/2025-2026/teams/leaderboards?metric=classification` | 200 | 28 | rank 1 existe, ranks consecutivos, clasificación coherente |
| `/v1/seasons/2025-2026/teams/metrics` | 200 | 28 | `wins`+`losses`=26 por equipo, `win_percentage` 0..100, `point_difference_per_game` presente |

Nota sobre `metric=wins` (ejemplo del enunciado): según el contrato vigente
`wins` **no** es una métrica soportada de leaderboard de equipo (el conjunto es
`classification | points_for | point_difference | win_percentage`, definido en
`TeamLeaderboardMetric.ALL`); la petición responde **400 INVALID_PARAMETER**
(controlado), coherente con el hardening de FASE 23.6 y con la regla "no
cambiar contratos". El leaderboard de equipos se validó con su métrica
contratada `classification` (200).

Muestra de contenido real (coherente con FASE 23.8):
* player top points: `{rank:1, player_external_id:"2736564", games_played:26,
  points:524, ...}`.
* player sample: `{player_external_id:"1072760", games_played:18, points:160,
  minutes:401.032}`.
* team sample: `{team_external_id:"979781", wins:11, losses:15,
  win_percentage:42.307…, point_difference_per_game:-2.5, ...}`.

## Hardening HTTP

| Petición | Resultado |
|---|---|
| `?metric=bogus` | **400 INVALID_PARAMETER** |
| `?metric=wins` | **400 INVALID_PARAMETER** (métrica no soportada, ver contrato) |
| `?limit=0` | **400 INVALID_PARAMETER** |
| `?limit=501` | **400 INVALID_PARAMETER** |
| `?limit=abc` | **400 INVALID_BODY** |
| `/v1/seasons/2099-2099/players` | **200** `count=0` `items=[]` (temporada inexistente) |

Nunca `500`, nunca stack traces, ningún secreto en las respuestas.

## Determinism

* `players/leaderboards?metric=points&limit=20` ejecutada dos veces → **cuerpos
  JSON idénticos**.
* `teams/leaderboards?metric=classification` ejecutada dos veces → **cuerpos
  JSON idénticos**.

## Health

* `GET /health` → **200** `{"status":"ok"}`.
* `GET /ready` → **200**
  `{"status":"ready","checks":{"schema_version":"3","database":"ok","migrations":"up_to_date"}}`.

Sin stack traces, sin DSN, sin secretos.

## Known non-blocking data (6 filas ajenas)

```
6 non-segunda-feb matches remain in production:
- smoke-comp: 5
- feb-comp: 1
```

* **No se eliminaron** (regla de la fase).
* No afectan a los analytics `segunda-feb`: el bloque MATCHES del validador
  mantiene el scope `competition_id = 'segunda-feb'` (364).
* No aparecen en las respuestas públicas de `2025-2026` (los endpoints leen
  `match_player_stats`/`match_team_stats`, 8.230/728 filas, todas de la
  temporada real).
* Ninguna fue modificada. La limpieza/decisión queda fuera de 23.9.

## Validación final contra producción

Re-ejecución de `validate_season_analytics_production.py` (túnel oficial,
READ-ONLY):

```
PRODUCTION VALIDATION: PASS
```

6/6 bloques PASS (MATCHES con scope `segunda-feb`; PLAYER/TEAM AGGREGATES;
LEADERBOARDS; METRICS; INTEGRIDAD), sin convertir las 6 filas ajenas en
errores (diagnóstico informativo).

## Tests

Suite completa: **845 passed, 0 failed** (sin regresiones; el baseline se
mantuvo — no se añadieron tests en esta fase porque no se modificó código).

## Seguridad

* Sin impresión de `DATABASE_URL`, passwords, tokens, API keys ni headers de
  autorización (el DSN se construyó desde la salida del túnel sin volcarlo).
* `railway up` no toca secrets; no se modificó configuración de producción.
* Respuestas públicas auditadas contra `password/token/Authorization/api_key/
  postgres.railway.internal/Traceback/psycopg`: sin coincidencias.
* Túnel cerrado tras la validación.

## Limitaciones

* `metric=wins` responde 400 (contrato existente); si el producto quisiera una
  clasificación por victorias como leaderboard habría que añadir la métrica en
  una fase de evolución (fuera de 23.9).
* La limpieza de las 6 filas ajenas queda pendiente (fuera de alcance).
* Grupo ESTE/OESTE no persistido (limitación documentada en 23.7/23.8): el
  validador verifica el equivalente estructural.

## Commits

* `feat(23.9): deploy and validate public season analytics` — este informe y
  la addenda documental en `FINAL_PROJECT_AUDIT.md` / `FINAL_CLOSURE.md`.
  Sin push.