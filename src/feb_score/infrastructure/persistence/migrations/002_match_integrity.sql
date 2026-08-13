-- FASE 10 — migration #2: match integrity + optimistic version column.
--
--  * Adds a normalised `version` column to `matches` so the optimistic-concurrency
--    guard in SqliteMatchRepository can compare stored vs mutated version without
--    re-reading the JSON blob (json_extract for backfill only).
--  * DB-level integrity for `matches`, without duplicating business logic:
--      - status must be a known enum value (mirrors domain MatchStatus)
--      - data must be valid JSON (defends the serialization contract at rest)
--      - home/away teams must differ (matches the domain invariant)
--  * DESTRUCTIVE: drops and rebuilds `matches`. connection.py creates a safety
--    backup (SqliteDatabase.backup) before applying it.
--
-- SQLite cannot add CHECK constraints via ALTER TABLE, hence the rebuild:
--   1. CREATE matches_v2 with the new constraints
--   2. copy existing rows (backfilling version from the JSON blob)
--   3. drop the old table and rename
--   4. recreate the filtered indexes

CREATE TABLE matches_v2 (
    match_id       TEXT PRIMARY KEY,
    external_id    TEXT NOT NULL UNIQUE,
    competition_id TEXT NOT NULL,
    season_code    TEXT NOT NULL,
    status         TEXT NOT NULL
                   CHECK (status IN ('PROVISIONAL','SCHEDULED','IN_PLAY','FINALIZED','POSTPONED','CANCELLED')),
    version        INTEGER NOT NULL DEFAULT 1,
    data           TEXT NOT NULL CHECK (json_valid(data)),
    CHECK (json_extract(data, '$.home_team_id') <> json_extract(data, '$.away_team_id'))
);

INSERT INTO matches_v2 (match_id, external_id, competition_id, season_code, status, version, data)
    SELECT match_id, external_id, competition_id, season_code, status,
           CAST(json_extract(data, '$.version') AS INTEGER), data
    FROM matches;

DROP TABLE matches;

ALTER TABLE matches_v2 RENAME TO matches;

CREATE INDEX IF NOT EXISTS idx_matches_season ON matches(competition_id, season_code);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);