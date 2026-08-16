-- FASE 23.6 — migration #4 (SQLite): season analytics query indexes.
--
-- Every season analytics read (FASE 23.5 aggregates, leaderboards and metrics)
-- filters EXCLUSIVELY by ``season_code`` and then GROUP BY / ORDER BY the entity
-- id:
--
--   WHERE season_code = ? GROUP BY player_external_id, season_code
--   WHERE season_code = ? GROUP BY team_external_id, season_code
--
-- The existing indexes (idx_player_stats_season = (player_external_id,
-- season_code) and idx_team_stats_match = (match_external_id)) cannot serve a
-- season-first lookup, so each analytics request would scan the full stats
-- tables as seasons accumulate. These two season-first indexes directly back
-- the six read endpoints.
--
-- Idempotent (IF NOT EXISTS) and non-destructive: applies cleanly on a fresh
-- install and upgrades an existing v3 database in place without touching data.

CREATE INDEX IF NOT EXISTS idx_player_stats_season_scan
    ON match_player_stats(season_code, player_external_id);

CREATE INDEX IF NOT EXISTS idx_team_stats_season_scan
    ON match_team_stats(season_code, team_external_id);