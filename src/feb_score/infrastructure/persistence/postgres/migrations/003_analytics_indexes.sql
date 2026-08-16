-- FASE 23.6 — migration #3 (PostgreSQL): season analytics query indexes.
--
-- Structural mirror of SQLite 004_analytics_indexes.sql. All six season
-- analytics read endpoints (FASE 23.5) filter exclusively by ``season_code``
-- and aggregate/order by the entity id:
--
--   WHERE season_code = %s GROUP BY player_external_id, season_code
--   WHERE season_code = %s GROUP BY team_external_id, season_code
--
-- The existing indexes (idx_player_stats_season = (player_external_id,
-- season_code) and idx_team_stats_match = (match_external_id)) cannot serve a
-- season-first lookup, so without these the reads scan the full stats tables.
--
-- Idempotent (IF NOT EXISTS) and non-destructive: fresh install or in-place
-- upgrade both reach the current schema.

CREATE INDEX IF NOT EXISTS idx_player_stats_season_scan
    ON match_player_stats(season_code, player_external_id);

CREATE INDEX IF NOT EXISTS idx_team_stats_season_scan
    ON match_team_stats(season_code, team_external_id);