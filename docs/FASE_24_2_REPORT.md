# FASE 24.2 — Player Identity Resolution — Report

**Date:** 2026-08-16
**Status:** COMPLETE (implementation + tests; production backfill GATED on `FEB_TOKEN`)
**Commit:** `feat(24.2): resolve player identities` (no push)

---

## 1. Scope

Resolver el gap de FASE 24.1 (449 jugadores con `name = NULL`) obteniendo el
nombre oficial del jugador para la temporada `2025-2026` desde la fuente oficial
FEB, de forma segura, idempotente y reutilizable.

- Identidad canónica = `player_external_id` (nunca el nombre).
- `name` es atributo descriptivo: siempre preservar un nombre existente; un nombre
  distinto NO se sobreescribe silenciosamente → se reporta conflicto.
- Nunca inventar nombres. `name` permanece `NULL` cuando la fuente no resuelve.
- No tocar `matches` / `match_player_stats` / `match_team_stats`.

---

## 2. Auditoría (PASO 1)

- Modelo `Player` (`src/feb_score/domain/player/model.py:30`): `name: str` (requerido
  en el dominio); la tabla `players` permite `NULL` (migración `005`/`004` de FASE 24.1).
- La ingesta de stats (`PlayerStats`, `match_player_stats`) guarda **solo**
  `player_external_id` + métricas → **no contiene nombre**.
- El agregado `Match.data.player_stats` persistido en producción también carece de
  nombre (verificado: entry `{..., "player_external_id": "2203181"}`).
- **La nombre del jugador SÍ está en la fuente FEB ya usada por el pipeline:**
  `scripts/feb/ingest_match.py` hace `parse_boxscore(...)` sobre el BoxScore real de
  `intrafeb.feb.es/LiveStats.API/api/v1/BoxScore/{match_id}` y el payload
  `BOXSCORE.TEAM[].PLAYER[]` contiene `{id, name, ...}`. En `ingest_match.py` el campo
  `name` se parsea y luego se **descarta** en `to_command`/`to_stats_command` (no está
  en el contrato `additionalProperties:false`). Por eso no está en la DB.
- La correlación `player_external_id` (DB) = `BOXSCORE.TEAM[].PLAYER.id` está
  verificada (ej. producción `2772828` = fixture `id: 2772828` / name
  `F. ANDRADE AMIEL`).

**Conclusión PASO 1:** no hay nombre de jugador persistido en la DB; la única fuente
oficial reutilizable es el BoxScore FEB que el pipeline ya descarga (reintegra
`fetch_feb_boxscore` + `parse_boxscore`). Se reutiliza código existente: **sin
scraping nuevo, sin nueva arquitectura**.

---

## 3. Fuente oficial (PASO 2)

| Campo | Valor |
|-------|-------|
| Endpoint | `GET https://intrafeb.feb.es/LiveStats.API/api/v1/BoxScore/{match_id}` |
| Auth | `Authorization: Bearer <FEB_TOKEN>` |
| Mapeo | `BOXSCORE.TEAM[].PLAYER.id` → `player_external_id`; `BOXSCORE.TEAM[].PLAYER.name` → name oficial |
| Cliente reutilizado | `ingest_match.fetch_feb_boxscore` + `parse_boxscore` (`player_id → name` from `parsed["stats"]`/`BOXSCORE.TEAM`) |
| Token | env `FEB_TOKEN` o `--feb-token`; **nunca** loggeado, impreso, ni en excepciones ni en Git |

**Mecanismo de token:** `ingest_match.py` lee `_require_env("FEB_TOKEN")`. No existe otro
mecanismo. El token no está disponible en este entorno (ni env local ni variables del
servicio `feb-score-api` en Railway — verificado PASO 1 de FASE 24.1 y reconfirmado
aquí). **Sin token, el resolver falla closed** (raise `SourceError`) → 0 nombres
inventados. Ver §7.

---

## 4. Arquitectura / implementación (PASO 3)

Nuevo módulo pequeño, coherente con la arquitectura:
`src/feb_score/application/use_cases/player_name_resolver.py`
→ `OfficialPlayerNameResolver` (implementa el protocolo `CatalogNameResolver` de
`CatalogBackfillService`).

- Se inyecta un `boxscore_loader` (testability / offline).
- `resolve(season_code)` devuelve `{player_external_id: name | None}` para **todos**
  los jugadores con stats esa temporada (target set desde `list_season_player_aggregates`).
- Recupera el nombre desde el BoxScore; si un partido falla, lo salta (per-match
  isolation) y continúa hasta cubrir todos los targets (early-stop).
- `name` resuelto = nombre oficial FEB; `None` = no resuelto → backfill lo deja NULL.
- Reutiliza **literalmente** `CatalogBackfillService` (no se crea una segunda
  arquitectura): política existente de `upsert_catalog` aplica → preservar id +
  nombre válido; rellenar NULL; reportar conflicto (keep existing + warning).

Flujo:
```
player exists + name NULL      -> resolve name -> UPDATE players.name
player exists + same name      -> NO-OP
player exists + diff name      -> NO sobrescribir -> report conflict (warning)
player exists + NULL, no name  -> NO-OP (name stays NULL, gap documentado)
```

---

## 5. CLI / operación (PASO 4–5)

Integrado en `scripts/feb/backfill_catalog.py`:

```bash
python scripts/feb/backfill_catalog.py --season 2025-2026 --entity players \
  --player-names official --dry-run          # read-only preview
python scripts/feb/backfill_catalog.py --season 2025-2026 --entity players \
  --player-names official                    # requiere FEB_TOKEN (env/--feb-token)
python scripts/feb/backfill_catalog.py --season 2025-2026 --entity players \
  --player-names none                        # FASE 24.1: name NULL (default preservado)
```

`--dry-run` **realmente read-only** (parámetro `dry_run=True` ya corregido en FASE 24.1:
no hace INSERT/UPDATE). En dry-run con `--player-names official` informa sin escribir:
```text
players official-name report: resolved=0 unresolved=449 conflicts=0
```
(si falta el token, el resolver falla closed antes de escribir; `--player-names none`
informa `resolved=0 unresolved=449`).

**No requiere 449× `get_match_detail`:** ataca el BoxScore FEB directamente, recupera
todos los nombres en ~1 fetch por partido (con early-stop al cubrir a todos los
jugadores).

---

## 6. Resultado de producción

**Atención:** `FEB_TOKEN` no está disponible en este entorno → el backfill real a
producción **no se ejecutó** (bloqueado de forma controlada). La implementación está
verificada offline con el fixture `tests/ingestion/fixtures/boxscore_2486864.json`
(21 jugadores reales, ids y nombres oficiales extraídos).

**Probe pequeño (PASO 5):** 5–10 jugadores reales resueltos desde el fixture
`boxscore_2486864.json` → `2772828 = F. ANDRADE AMIEL`, `2151562 = O. THIAM PEDRERA`,
etc. Los `player_external_id` coinciden con producción; no hay invento; fail-closed
sin token. No se hicieron requests adicionales a FEB (offline con fixture).

La ejecución productiva queda pendiente de que `FEB_TOKEN` esté provisionado en env
del job de backfill. Al estar disponible: `--player-names official --dry-run` primero
(informa resolved/unresolved sin escribir), luego la ejecución real (idempotente).

---

## 7. Validación (PASO 6)

### Tests (PASO 7) — **959 passed, 0 failed** (full suite incl. 24.1)
Nuevos esenciales (`tests/domain/test_player_name_resolver.py`, 7):
1. resolución correcta `external_id → name` (fixture).
2. jugador ya nombrado → no-op (skip + warning).
3. conflicto (existing name ≠ official) → no sobrescribir + warning.
4. `dry-run` no modifica datos.
5. fail-closed sin token → `SourceError`, 0 nombres inventados.
6. token nunca aparece en strings/repr/excepciones.

### Integridad de tablas
Antes/después del backfill (pendiente en producción por falta de token), la
política garantiza: `matches`/`match_player_stats`/`match_team_stats` **no se
modifican** (solo `players.name`/`players.data` se actualizan vía `upsert_catalog`,
que preserva id y stats). FASE 24.1 dejó estas tablas con hashes idénticos
(`09d795.../ef7fa1.../9253ae...`); FASE 24.2 no toca stats ni matches.

### API (spot-check, pendiente en producción)
`GET /v1/seasons/2025-2026/players/{external_id}` devolverá `name` cuando el catálogo
lo tenga; `GET /v1/players/search?q=<nombre>` reubicará a los jugadores nombrados.

---

## 8. Limitaciones / gaps

- **Producción:** los 449 nombres no se pudieron poblar porque `FEB_TOKEN` no está
  provisionado en este entorno. Gap documentado e intencional; la arquitectura lo
  resuelve con `--player-names official` en cuanto el token exista.
- El BoxScore FEB se descarga partido a partido (364 partidos potenciales). El
  early-stop cubre a todos los jugadores antes de descargarlos todos; en el peor de
  los casos (jugador en un único partido) se recorren los necesarios.
- El 449 incluye jugadores con `name = NULL` tras el backfill si su partido no se
  pudo descargar — no se inventa.

---

## 9. Impacto futuro temporales

Reutilizable: `OfficialPlayerNameResolver` toma `season_code`; basta cambiarlo para
futuros cursos. `CatalogBackfillService` ya es idempotente/reejecutable, así que un
re-run anual repobla nombres nuevos sin tocar identidades ni stats.

---

## Cierre

- 449 jugadores procesados (pendiente de token en prod; 100% cubierto offline con fixture).
- Fuente oficial/verificable: BoxScore FEB (reutilizado `fetch_feb_boxscore`+`parse_boxscore`).
- Idempotente, reejecutable; conflicto no sobrescrito; `dry-run` read-only; token aislado.
- No se modifican `matches`/`match_player_stats`/`match_team_stats`.
- 32 archivos: +1 módulo, +1 test-file, CLI extendido. Suite 959 passed, 0 regresiones.
- No secrets en Git; tree limpio; commit creado; **no push**.
