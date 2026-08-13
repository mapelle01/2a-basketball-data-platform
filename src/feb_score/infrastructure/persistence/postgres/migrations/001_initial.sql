-- FASE 12 — PostgreSQL real schema (migration #1).
--
-- Structural mirror of the SQLite schema (001_initial.sql + 002_match_integrity.sql
-- merged, since PostgreSQL has no user_version pragma): the aggregates are
-- reconstructed from the JSONB `data` blob (serialization is the single source of
-- truth), normalized key columns serve lookups, and the `matches` table carries
-- the optimistic-concurrency `version` column plus DB-level integrity checks that
-- mirror the domain invariants (known status, valid JSON, home <> away).
--
-- Differences from SQLite, all deliberate:
--   * TEXT uuids -> TEXT (kept: interfaces and contracts pass raw strings; no
--     uuid cast is required and nothing gains from one here).
--   * data TEXT -> JSONB (indexable, canonical, json-validated at write time).
--   * domain_events.payload -> JSONB; delivered -> BOOLEAN.
--   * CHECK/constraints expressed as PostgreSQL CHECKs.
--   * Indexes chosen for the query patterns actually used by the repositories.

CREATE TABLE IF NOT EXISTS competitions (
    competition_id TEXT PRIMARY KEY,
    external_id    TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    data           JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    match_id       TEXT PRIMARY KEY,
    external_id    TEXT NOT NULL UNIQUE,
    competition_id TEXT NOT NULL,
    season_code    TEXT NOT NULL,
    status         TEXT NOT NULL
                   CHECK (status IN ('PROVISIONAL','SCHEDULED','IN_PLAY','FINALIZED','POSTPONED','CANCELLED')),
    version        INTEGER NOT NULL DEFAULT 1,
    data           JSONB NOT NULL,
    CHECK (data->>'home_team_id' <> data->>'away_team_id')
);
CREATE INDEX IF NOT EXISTS idx_matches_season ON matches(competition_id, season_code);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);

CREATE TABLE IF NOT EXISTS players (
    player_id   TEXT PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    data        JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    team_id     TEXT PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    data        JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS correction_proposals (
    proposal_id        TEXT PRIMARY KEY,
    match_external_id  TEXT NOT NULL,
    status             TEXT NOT NULL,
    data               JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proposals_match ON correction_proposals(match_external_id);

CREATE TABLE IF NOT EXISTS standing_snapshots (
    snapshot_id    TEXT PRIMARY KEY,
    competition_id TEXT NOT NULL,
    season_code    TEXT NOT NULL,
    generated_at   TEXT NOT NULL,
    data           JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_season ON standing_snapshots(competition_id, season_code, generated_at);

CREATE TABLE IF NOT EXISTS leaderboards (
    leaderboard_id TEXT PRIMARY KEY,
    season_code    TEXT NOT NULL,
    category       TEXT NOT NULL,
    generated_at   TEXT NOT NULL,
    data           JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leaderboards_season ON leaderboards(season_code, category, generated_at);

CREATE TABLE IF NOT EXISTS ratings (
    rating_id          SERIAL PRIMARY KEY,
    player_external_id TEXT NOT NULL,
    season_code        TEXT NOT NULL,
    rating_version     TEXT NOT NULL,
    calculated_at      TEXT NOT NULL,
    data               JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ratings_player ON ratings(player_external_id, season_code);

CREATE TABLE IF NOT EXISTS publications (
    publication_id TEXT PRIMARY KEY,
    template_id    TEXT NOT NULL,
    status         TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    data           JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
    command_id    TEXT PRIMARY KEY,
    processed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS domain_events (
    event_id       TEXT PRIMARY KEY,
    event_type     TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id   TEXT NOT NULL,
    produced_at    TIMESTAMPTZ NOT NULL,
    payload        JSONB NOT NULL,
    delivered      BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_events_pending   ON domain_events(delivered, produced_at);
CREATE INDEX IF NOT EXISTS idx_events_aggregate ON domain_events(aggregate_type, aggregate_id);