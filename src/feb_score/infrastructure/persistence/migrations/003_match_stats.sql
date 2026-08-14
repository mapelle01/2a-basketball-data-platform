-- FASE 21.B3 — migration #3: queryable BoxScore stats projection.
--
-- Stats belong to the Match aggregate (source of truth in matches.data via the
-- serialization module). These tables are an INDEXED, UNIQUE-guaranteed read
-- model so the FASE 21.B3 query patterns are efficient and re-ingestion cannot
-- duplicate rows:
--
--   * stats of one player in a match      (match_external_id, player_external_id)
--   * all players of a match              (match_external_id)
--   * one player across a season          (player_external_id, season_code)
--   * team stats in a match               (match_external_id, team_external_id)
--
-- Idempotency: PRIMARY KEY (match_external_id, player_external_id) / team key;
-- repositories upsert with INSERT OR REPLACE so replaying the same stats command
-- overwrites the same rows instead of duplicating them.
--
-- Non-destructive and fully idempotent (IF NOT EXISTS): applies cleanly on a
-- fresh install and upgrades an existing v1/v2 database in place.

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
    minutes            REAL NOT NULL DEFAULT 0,
    played_at          TEXT,
    data               TEXT NOT NULL,
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
    data                   TEXT NOT NULL,
    PRIMARY KEY (match_external_id, team_external_id)
);

CREATE INDEX IF NOT EXISTS idx_team_stats_match
    ON match_team_stats(match_external_id);