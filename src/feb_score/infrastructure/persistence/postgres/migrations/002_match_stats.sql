-- FASE 21.B3 — migration #2 (PostgreSQL): queryable BoxScore stats projection.
--
-- Structural mirror of SQLite 003_match_stats.sql. Stats belong to the Match
-- aggregate (matches.data JSONB is the source of truth); these tables are the
-- INDEXED, UNIQUE-guaranteed read model for the FASE 21.B3 query patterns:
--
--   * one player in a match       (match_external_id, player_external_id)
--   * all players of a match      (match_external_id)
--   * one player across a season  (player_external_id, season_code)
--   * team stats in a match       (match_external_id, team_external_id)
--
-- Idempotency: PRIMARY KEY on the FEB external keys; repositories upsert with
-- ON CONFLICT DO UPDATE so replaying the same stats command overwrites rows
-- instead of duplicating them. JSONB is used for the `data` blob (mirroring the
-- existing PostgreSQL schema), while the query columns stay normalized and
-- indexable.
--
-- Non-destructive and idempotent (IF NOT EXISTS): fresh install or in-place
-- upgrade both reach the current schema.

CREATE TABLE IF NOT EXISTS match_player_stats (
    match_external_id  TEXT NOT NULL,
    player_external_id TEXT NOT NULL,
    team_external_id   TEXT NOT NULL,
    season_code        TEXT NOT NULL,
    points             INTEGER NOT NULL,
    rebounds           INTEGER NOT NULL,
    assists            INTEGER NOT NULL,
    steals             INTEGER NOT NULL DEFAULT 0,
    blocks             INTEGER NOT NULL DEFAULT 0,
    turnovers          INTEGER NOT NULL DEFAULT 0,
    minutes            DOUBLE PRECISION NOT NULL DEFAULT 0,
    played_at          TIMESTAMPTZ,
    data               JSONB NOT NULL,
    PRIMARY KEY (match_external_id, player_external_id)
);

CREATE INDEX IF NOT EXISTS idx_player_stats_season
    ON match_player_stats(player_external_id, season_code);
CREATE INDEX IF NOT EXISTS idx_player_stats_match
    ON match_player_stats(match_external_id);

CREATE TABLE IF NOT EXISTS match_team_stats (
    match_external_id      TEXT NOT NULL,
    team_external_id       TEXT NOT NULL,
    season_code            TEXT NOT NULL,
    points_for             INTEGER NOT NULL,
    points_against         INTEGER NOT NULL,
    field_goals_made       INTEGER NOT NULL,
    field_goals_attempted  INTEGER NOT NULL,
    three_points_made      INTEGER NOT NULL,
    three_points_attempted INTEGER NOT NULL,
    free_throws_made       INTEGER NOT NULL,
    free_throws_attempted  INTEGER NOT NULL,
    turnovers              INTEGER NOT NULL,
    rebounds               INTEGER NOT NULL,
    data                   JSONB NOT NULL,
    PRIMARY KEY (match_external_id, team_external_id)
);

CREATE INDEX IF NOT EXISTS idx_team_stats_match
    ON match_team_stats(match_external_id);