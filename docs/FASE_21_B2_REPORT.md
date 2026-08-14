# FASE 21.B2 — FEB SOURCE CONNECTOR (real FEB format) + DRY-RUN VALIDATED

## Status

**PASS — connector entregado al formato REAL de FEB; dry-run offline validado; CI 493 tests green; merge a main.**

**Ingesta en vivo (production POST) — PENDING:** el connector está operativo y offline-validado,
pero la **primera ingesta REAL a production** (`FEB_TOKEN` + `FEB_API_KEY` reales) no se ejecutó
ni se pedirán/obtuvieron esas credenciales. Pendiente tuyo (FASE 21.B2.1 opcional).

## Cambios (B2)

- `scripts/feb/ingest_match.py` (rewrite): `fetch_feb_boxscore(match_id, token)`,
  `parse_boxscore(boxscore, match_id, season_code)`, `to_command(...)`, `post_command(...)` (inalterado),
  CLI `argparse` (`--fixture`, `--dry-run`, `--match-id`), env config (`FEB_TOKEN`, `FEB_MATCH_ID`,
  `FEB_SEASON_CODE` requerido, `FEB_COMPETITION_ID`, `FEB_BOX_SCORE_BASE_URL`, `FEB_API_KEY`, `FEB_TARGET_API`).
- `tests/ingestion/test_feb_connector.py` (rewrite, 14 tests, fixture real `boxscore_2486864.json`).
- `tests/ingestion/fixtures/boxscore_2486864.json` (fixture real FEB auditado).
- `scripts/feb/smoke_fetch_feb.py` (manual smoke; NOT en CI).
- `scripts/feb/README.md` (documentación real fuente/mapping/env/CLI).

## Source FEB real (verificado)

- URL: `https://intrafeb.feb.es/LiveStats.API/api/v1/BoxScore/{match_id}`
- Auth: `Authorization: Bearer <FEB_TOKEN>`.
- Fixture real (auditado): `tests/ingestion/fixtures/boxscore_2486864.json` → 2486864,
  Segunda FEB / CompID=118; home BUENO ARENAS ALBACETE BASKET(979897) 80 vs LOBE HUESCA LA MAGIA(981281) 88;
  parciales 15-20/17-30/22-16/26-22; fecha `18-10-2025 19:00`.

## DRY-RUN (offline) — evidencia real

```
$ FEB_SEASON_CODE=2025-2026 FEB_MATCH_ID=2486864 \
  python3 scripts/feb/ingest_match.py --fixture tests/ingestion/fixtures/boxscore_2486864.json --dry-run
external_id=2486864
competition=SEGUNDA FEB (CompID=118)
season=2025-2026
home_team=979897 (BUENO ARENAS ALBACETE BASKET)
away_team=981281 (LOBE HUESCA LA MAGIA)
scheduled_at=2025-10-18T19:00:00+01:00 (B2: +01:00 assumed (FEB no TZ))
home_score=80
away_score=88
quarters=[(1, 15, 20), (2, 17, 30), (3, 22, 16), (4, 26, 22)]
players= home:10 away:11
command_id=c86e1174-6e78-5487-99ca-baabda55ddda
DRY_RUN
```

No exige `FEB_TOKEN`/`FEB_SOURCE_URL`/`FEB_API_KEY`. No imprime tokens.

## Mapping real → command (contract-compliant)

- `external_id` = `match_id` FEB (2486864).
- `competition_id` = `segunda-feb` (logical; FEB `CompID=118` preservado en `source`).
- `scheduled_at` = `2025-10-18T19:00:00+01:00` (offset B2 provisional: FEB no publica TZ).
- Home/away por orden `HEADER.TEAM[0|1]`. Score final `HEADER.TEAM[].pts`. Parciales `QUARTERS.QUARTER`.
- Player stats desde `BOXSCORE.TEAM[].PLAYER[]` (id/name/no/min/pts/reb/assist/val/to/bs/st/pf/1P/2P/3P/FG).
- `source`/`raw` trazables.

## Contract constraint

`create_or_update_match.v1.json` permite `raw` solo `boxscore_ref`/`teamstats_ref`
(`additionalProperties:false`) → **no se embede BoxScore/stats completo en B2** (no se rompe schema).
Persistencia completa de stats en Postgres → **FASE 21.B3**.

## Evidencia tests (14/14 PASS)

parse competition/CompID, external_id, equipos, score 80-88, 4 parciales, scheduled_at,
REID (id=2813013, pts=12, reb=6, assist=1, val=14), player keys, command_id determinista,
command_id ≠ per external_id, dry-run offline (no FEB_SOURCE_URL/FEB_TOKEN), dry-run no POST,
token never in output, payload schema-compliant (additionalProperties).

CI: **493 passed** (479 + 14). Merge `31bac66` → GitHub Actions `ci` **success** (run 31815403335).

## Production / Staging (intactos — connector no redeploya la imagen API)

- Production: deployment `3471a1de` SUCCESS; `/health` 200; `/ready` 200
  (schema_version=1, database=ok, migrations=up_to_date); `/docs` 404; POST no-key 401.
- Staging: `/health` 200, `/ready` 200, `/docs` 200 → intacto.

## Security

- `FEB_TOKEN` / `FEB_API_KEY` vía env; nunca en Git/logs/payloads/URLs.
- `smoke_fetch_feb.py` rechaza tokens malformados (`=`, prefix `Bearer `, newlines).
- 0 literales 64-hex/keys en archivos tracked (secret scan clean).

## Pendiente (no es blocker del conector)

- **Ingesta en vivo a production:** requiere `FEB_TOKEN` (intrafeb) + `FEB_API_KEY` reales →
  tú los provees → `python3 scripts/feb/ingest_match.py --match-id 2486864` (POST real).
- Player stats persistence en Postgres → FASE 21.B3.

## Conclusión B2

FASE 21.B1 + 21.B2 **COMPLETE** (connector real, idempotent, offline-validado, CI 493 green,
merge a main, prod/staging intactos). La **cadena FEB→API→Postgres→GET** está arquitecturada y con
el parser de formato real validado; la ingesta en vivo queda pending de credenciales reales.