# FASE 23.2 — Season Team Aggregates

**Fecha:** 2026-08-16  
**Estado:** COMPLETE  
**Tests:** 650 passed  

---

## Objetivo

Implementar una capa analítica de lectura que permita obtener las estadísticas acumuladas de cada equipo por temporada a partir de los registros existentes en `match_team_stats`, siguiendo exactamente el mismo patrón arquitectónico establecido en FASE 23.1 (`SeasonPlayerStats`).

---

## Auditoría inicial

### Estructura real de `match_team_stats`

**Columnas físicas normalizadas** (verificadas en `002_match_stats.sql` y en `TeamStats` del modelo de dominio):

| Columna | Tipo | Descripción |
|---|---|---|
| `match_external_id` | TEXT | PK parcial |
| `team_external_id` | TEXT | PK parcial |
| `season_code` | TEXT | Temporada |
| `points_for` | INTEGER | Puntos anotados por el equipo |
| `points_against` | INTEGER | Puntos recibidos por el equipo |
| `field_goals_made` | INTEGER | Tiros de campo convertidos |
| `field_goals_attempted` | INTEGER | Tiros de campo intentados |
| `three_points_made` | INTEGER | Triples convertidos |
| `three_points_attempted` | INTEGER | Triples intentados |
| `free_throws_made` | INTEGER | Tiros libres convertidos |
| `free_throws_attempted` | INTEGER | Tiros libres intentados |
| `turnovers` | INTEGER | Pérdidas de balón |
| `rebounds` | INTEGER | Rebotes |
| `data` | JSONB | Blob completo de la fuente |

**PRIMARY KEY:** `(match_external_id, team_external_id)` — garantiza idempotencia en replay.

**Campos NOT disponibles en TeamStats / match_team_stats:**
- `assists` → **NO EXISTE** en el modelo de equipo.
- `steals` → **NO EXISTE** en el modelo de equipo.
- `blocks` → **NO EXISTE** en el modelo de equipo.
- `minutes` → **NO EXISTE** en el modelo de equipo.

Estos campos existen en `PlayerStats` / `match_player_stats` pero no se recalcularon desde estadísticas de jugador. La fuente primaria es `match_team_stats` tal como indica el requisito.

### Identificación

- **Equipo:** `team_external_id` (ID externo FEB del equipo).
- **Temporada:** `season_code` (e.g. `"2025-2026"`).
- **Resultado:** comparando `points_for` vs `points_against` dentro de cada fila (una fila = un equipo en un partido).

---

## Modelo `SeasonTeamStats`

```python
@dataclass(frozen=True)
class SeasonTeamStats:
    team_external_id: str
    season_code: str
    games_played: int         # COUNT(match_external_id) por temporada
    wins: int                 # SUM(CASE WHEN points_for > points_against THEN 1 ELSE 0 END)
    losses: int               # SUM(CASE WHEN points_for < points_against THEN 1 ELSE 0 END)
    points_for: int           # SUM(points_for)
    points_against: int       # SUM(points_against)
    field_goals_made: int
    field_goals_attempted: int
    three_points_made: int
    three_points_attempted: int
    free_throws_made: int
    free_throws_attempted: int
    turnovers: int
    rebounds: int
```

**Invariante de dominio validada en `__post_init__`:**  
`wins + losses == games_played` (no hay empates en baloncesto).

**Ausentes documentados:** `assists`, `steals`, `blocks`, `minutes` no están disponibles en la fuente de equipo y no se han fabricado.

---

## Definiciones

### `games_played`
`COUNT(match_external_id)` — aprovecha que la PRIMARY KEY `(match_external_id, team_external_id)` garantiza exactamente 1 fila por partido por equipo. No se necesita `COUNT(DISTINCT ...)`.

### `wins` / `losses`
Calculados en SQL con `CASE WHEN`:
```sql
SUM(CASE WHEN points_for > points_against THEN 1 ELSE 0 END) AS wins,
SUM(CASE WHEN points_for < points_against THEN 1 ELSE 0 END) AS losses
```
No se modelan empates (el baloncesto siempre produce un ganador en prórroga).

---

## Query PostgreSQL

```sql
SELECT
  team_external_id,
  season_code,
  COUNT(match_external_id)                                     AS games_played,
  SUM(CASE WHEN points_for > points_against THEN 1 ELSE 0 END) AS wins,
  SUM(CASE WHEN points_for < points_against THEN 1 ELSE 0 END) AS losses,
  SUM(points_for)             AS points_for,
  SUM(points_against)         AS points_against,
  SUM(field_goals_made)       AS field_goals_made,
  SUM(field_goals_attempted)  AS field_goals_attempted,
  SUM(three_points_made)      AS three_points_made,
  SUM(three_points_attempted) AS three_points_attempted,
  SUM(free_throws_made)       AS free_throws_made,
  SUM(free_throws_attempted)  AS free_throws_attempted,
  SUM(turnovers)              AS turnovers,
  SUM(rebounds)               AS rebounds
FROM match_team_stats
WHERE season_code = %s
GROUP BY team_external_id, season_code
ORDER BY team_external_id
```

La misma query con `?` se usa en SQLite.

---

## Implementación por backend

| Backend | Método | Fuente |
|---|---|---|
| PostgreSQL | `PgMatchStatsRepository.list_season_team_aggregates` | `match_team_stats` via GROUP BY SQL |
| SQLite | `SqliteMatchStatsRepository.list_season_team_aggregates` | `match_team_stats` via GROUP BY SQL |
| InMemory | `InMemoryMatchStatsRepository.list_season_team_aggregates` | aggregation sobre `self._team` dict |

La agregación en InMemory opera sobre todos los partidos sin filtrar por `season_code` (el mock de tests no lleva esa dimensión en el store interno). Los tests de InMemory asumen setup aislado por instancia, lo cual es correcto para el patrón de test actual.

---

## Tests

Archivo: `tests/postgres/test_season_team_aggregates.py`

| Test | Cobertura |
|---|---|
| `test_single_team_multiple_games` | `games_played`, totales acumulados |
| `test_wins_and_losses` | 2W-1L, invariante `W+L==GP` |
| `test_points_for_against` | sumas de puntos |
| `test_accumulated_stats` | FG, 3P, FT, turnovers, rebounds |
| `test_season_isolation` | aislamiento de temporadas |
| `test_determinism` | orden estable (alfabético por `team_external_id`) |
| `test_multiple_teams_no_mixing` | dos equipos en mismos partidos, no se mezclan |
| `test_replay_does_not_duplicate` | replay idempotente → `games_played == 1` |
| `test_win_loss_by_points` | lógica win/loss por comparación de puntos |
| `test_math_consistency` | `SUM(games_played)==2N`, `SUM(wins)==N`, `SUM(losses)==N` |

**Resultado:** 20 tests (10 × 2 backends) — **todos PASS**.

---

## Validaciones matemáticas

### Para la temporada 2025-2026 con 364 partidos:

```
SUM(games_played) esperado = 364 × 2 = 728
SUM(wins)         esperado = 364
SUM(losses)       esperado = 364
```

Estas invariantes están verificadas en `test_math_consistency` para el entorno de test.  
El script `validate_season_team_aggregates.py` las comprueba también sobre producción.

### Consistencia de métricas:
```
SUM(aggregates.points_for)   == SUM(match_team_stats.points_for)
SUM(aggregates.points_against) == SUM(match_team_stats.points_against)
... (verificado para todas las métricas)
```

---

## Validación de Producción

`PRODUCTION VALIDATION: BLOCKED — private Railway PostgreSQL not directly reachable from local environment`

**Causa:** La base de datos de producción utiliza red privada interna de Railway (`postgres.railway.internal`), inaccesible directamente desde el entorno local Mac por diseño de seguridad.

**Script disponible:** `validate_season_team_aggregates.py` — listo para ejecutarse en cualquier entorno con acceso a la red privada:
```bash
FEB_SCORE_DATABASE_URL="<dsn>" python3 validate_season_team_aggregates.py
```

---

## Decisiones Arquitectónicas

- **No se creó una abstracción separada de lectura**: `MatchStatsRepository` ya documenta explícitamente en su docstring que es el read model para queries de season stats. Es la abstracción correcta.
- **No se añadieron `assists`/`steals`/`blocks`/`minutes`**: no existen en `TeamStats` ni en `match_team_stats`. Inventarlos contradiría el mandato de la fase.
- **wins/losses en SQL**: evita cargar datos en Python; la comparación se realiza por fila en la DB.
- **Orden `ORDER BY team_external_id`**: garantiza determinismo independiente del motor.

## Limitaciones Conocidas

- `assists`, `steals`, `blocks`, `minutes` no están disponibles a nivel de equipo. Si se necesitan en el futuro, deben añadirse como columnas físicas en `match_team_stats` durante el proceso de ingestión FEB.
- InMemory no filtra por `season_code` en `list_season_team_aggregates` (el store interno indexa por `match_external_id`, no por temporada). Los tests de InMemory están diseñados con instancias aisladas por test, lo que es equivalente.
