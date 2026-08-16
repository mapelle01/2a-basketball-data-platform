# FASE 24 — Match & Player Exploration API — Report

**Date:** 2026-08-16
**Status:** COMPLETE (production massive validation PARTIAL — see below)
**Commit:** single closing commit `feat(24): complete match and player exploration API` (no push)

---

## 1. Scope (24.1 → 24.4)

| ID | Feature | Endpoint(s) |
|----|---------|-------------|
| 24.1 | Match detail enriched with BoxScore | `GET /v1/matches/{external_id}` (additive enrichment of the existing route: `team_stats` + `player_stats` from the stats tables, sorted by id) |
| 24.2 | Player season profile | `GET /v1/seasons/{season_code}/players/{player_external_id}` |
| 24.3 | Team season profile + round evolution | `GET /v1/seasons/{season_code}/teams/{team_external_id}` |
| 24.4 | Match / player / team search | `GET /v1/matches` + `GET /v1/seasons/{season_code}/players/search` + `GET /v1/seasons/{season_code}/teams/search` |

All exploration routes are **public** (no auth), except the pre-existing
`POST /v1/commands` (system auth) — consistent with the read-only analytics
API of FASE 23.

## 2. Behaviour contract

- **Match detail** (24.1) enriches the existing match route additively. The
  read model is built exclusively from the stats tables; it is never invented.
- **Player profile** (24.2): `totals`/`metrics` are `None` when the player has
  no stats rows that season (never fabricated). `teams` are the catalog
  registrations of the season; if no `players` record exists, identity is
  **derived from the BoxScore stats projection** (`list_player_season_teams`):
  the profile resolves with `name`/`position`/`nationality`/`birth_date` =
  `null` and the teams the player actually appeared for. A 404 is returned
  only when the entity has **no catalog record AND no stats**.
- **Team profile** (24.3): same derivation rule (`team`/`name` = `null` when
  no catalog record, totals/metrics/evolution still resolved from stats).
  `evolution` is per-round over `matches.data.round_number` (rounds without a
  round number are excluded); it is ordered by `round_number` ASC and sums
  exactly to `totals`.
- **Search** (24.4): match search requires `season_code` (optional
  `competition_id`, `round_number`, `team_external_id` home-or-away, `q`,
  `limit`), ordered by `external_id` ASC, deterministic. Player/team name
  search is case-insensitive substring over the **catalog**; wildcards are
  treated literally (never interpreted). `season_code` is validated with
  `^[0-9]{4}-[0-9]{2,4}$` (same contract as `SeasonCode`, enforced in the API
  layer without importing the domain — architecture boundary).

## 3. Architecture notes

- `api/exploration.py` stays within the API layer boundary: it does **not**
  import `feb_score.domain` except `errors`/`common`; season validation is
  delegated to a `_validated_season_code()` helper mirroring `SeasonCode`
  (tested by `test_api_imports_domain_only_via_errors`).
- New repository capability `MatchStatsRepository.list_player_season_teams`
  implemented across **InMemory / SQLite / PostgreSQL** (contract-tested on
  SQLite + PG).
- Route registration order in `main.py` (unchanged): search → generic →
  analytics → profiles.
- The match-detail route intentionally has **no `response_model`** (returns a
  raw DTO); the OpenAPI drift tests assert the Pydantic-backed schemas
  (`PlayerProfileResponse`, `TeamProfileResponse`, `MatchSearchResponse`) and
  the presence of all six GET paths instead.

## 4. Tests

Local suite: **906 passed, 0 failed** (845 baseline + **61 new**).

| Suite | New tests | Result |
|-------|-----------|--------|
| `tests/api/test_exploration.py` (FastAPI, seed via gateway repos) | 28 | PASS |
| `tests/postgres/test_exploration_repositories.py` (SQLite + PG contract suite) | 17 | PASS |
| `tests/domain/test_exploration_inmemory.py` (InMemory + service) | 9 | PASS |
| `tests/postgres/test_season_exploration_validator.py` (synthetic production-shaped PG) | 7 | PASS |

Covered explicitly: match filters (competition/round/team/q/limit),
deterministic ordering, literal wildcards, player/team name search, team
round evolution + no-round exclusion, season isolation, derived (stats-only)
profiles, catalog profiles, 404/400 hardening, OpenAPI drift, and the
validator's failure modes (broken boxscore, evolution round gap, player name
drift).

## 5. PostgreSQL synthetic validation — PASS

`validate_season_exploration_production.py` against the **synthetic** seed
(364 matches, 28 teams, 30 players, one stats-only derived player, one
cross-season contamination row) → **PASS**: all four blocks (match detail
boxscore, player profiles, team profiles + evolution, search) resolve, with
the derived player reported as an explicit diagnostic. The validator iterates
the **analytics aggregates** (entities that actually have stats), so an empty
catalog can no longer produce a vacuous pass.

## 6. Production validation — PARTIAL

Massive end-to-end validation against the real production database
(≈449 profiles × 2 aggregate queries over the SSH tunnel) was **not
re-run** by explicit decision of the phase owner. Evidence status:

- **Match detail / boxscore (24.1): PASS (real).** A real `2025-2026` match
  resolved with 2 teams / 23 players, deterministic across repeated calls.
- **Player profile (24.2): PASS (real).** Real player `1072760` resolved with
  `totals.points` 160 == aggregate, `name=null` (identity derived — the
  production `players` catalog is empty, see below).
- **Team profile + evolution (24.3): PASS (real).** Real team `979781`
  resolved with evolution rounds exactly 1..26.
- **Match search (24.4): PASS (real, earlier run).** 364 league matches /
  26 round × 14 matches recovered and re-located.
- **Player/team name search (24.4): no-data (real).** The production
  `players` and `teams` catalog tables are **empty (0 rows)**, so name search
  cannot match anything; profiles fall back to the derived identity. This is a
  **documented production data gap**, not an implementation defect.
- **Season isolation (real, smoke):** search for `2024-2025` under the same
  competition returns no rows (no overlap with `2025-2026`).

Production data touched: **none** (all validation read-only; `players`/`teams`
left empty; stray non-league matches left untouched).

## 7. Determinism / security / isolation

- **Determinism:** repeated reads of the same match/profiles return identical
  payloads (verified locally, on synthetic PG, and in the production smoke).
- **Security:** exploration endpoints are public read-only; no secrets in the
  tree; the local runbook/tunnel DSNs are ephemeral and never committed; the
  production DSN is built at runtime from `railway variables` and never
  printed.
- **Season isolation:** every read is scoped by `season_code`; cross-season
  contamination rows are ignored (verified in the synthetic PG suite).

## 8. Limitations

1. **Player/team name search has no data in production** until the `players` /
   `teams` catalog is populated (the DB currently stores only `external_id`
   inside stats blobs; no names exist anywhere). Profiles mitigate this via
   derived identity with `name=null`.
2. **Massive production validation is PARTIAL**: the full 449-player /
   28-team validator run against the live DB was not re-executed; only the
   representative smoke above (1 match, 1 player, 1 team, search, isolation,
   determinism) plus the earlier full-run evidence for 24.1/24.4.
3. **Match evolution** relies on `matches.data.round_number`; rounds without
   a round number are excluded by design (no invented rounds).
4. Match detail does not expose an OpenAPI `response_model` (raw DTO); the
   contract is covered by tests rather than the schema.

## 9. Closing criteria checklist

- 906 tests PASS (845 + 61) — **yes**
- Synthetic PostgreSQL validation PASS — **yes**
- Real production evidence documented — **yes** (smoke PASS + earlier partial)
- Limitations explicit — **yes**
- Documentation complete — **yes** (`docs/FASE_24_REPORT.md` + addenda)
- Commit created, no push — **yes**
- Working tree clean — **yes**
- No advance to FASE 25 — respected