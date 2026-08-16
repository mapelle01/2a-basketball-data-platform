-- FASE 24.1: catalog backfill needs `name` to be nullable so entities whose
-- official name is not available are stored as name = NULL (documented gap).
-- SQLite cannot ALTER COLUMN: rebuild both catalog tables preserving data.
-- Additive: only relaxes the NOT NULL constraint.
CREATE TABLE players_v2 (
    player_id   TEXT PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,
    name        TEXT,
    data        TEXT NOT NULL
);
INSERT INTO players_v2 (player_id, external_id, name, data)
    SELECT player_id, external_id, name, data FROM players;
DROP TABLE players;
ALTER TABLE players_v2 RENAME TO players;

CREATE TABLE teams_v2 (
    team_id     TEXT PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,
    name        TEXT,
    data        TEXT NOT NULL
);
INSERT INTO teams_v2 (team_id, external_id, name, data)
    SELECT team_id, external_id, name, data FROM teams;
DROP TABLE teams;
ALTER TABLE teams_v2 RENAME TO teams;