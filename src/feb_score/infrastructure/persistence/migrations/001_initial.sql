-- FASE 9 — SQLite real schema (migration #1).
--
-- Evolución documentada respecto al DDL propuesto en FASE 8:
--
--  * Los aggregates se reconstruyen SIEMPRE mediante la serialización definida
--    (application.persistence.serialization). Para garantizar que la serialización
--    es la única fuente de verdad y evitar desincronización columna/JSON, cada tabla
--    almacena las columnas clave normalizadas (identity + filtros de las interfaces)
--    y un blob `data` JSON con el agregado completo.
--
--  * Se eliminan las tablas normalizadas `seasons` y `rounds`: Season y
--    RoundDefinition son datos internos del agregado Competition, que se persiste
--    completo en competitions.data. Sin ellas no hay doble fuente de verdad.
--
--  * Se elimina la tabla normalizada `registrations`: Player.registrations y
--    Team.registrations son listas de value objects del dominio, se persisten dentro
--    de cada agregado. La atomicidad de la escritura dual la garantiza la frontera
--    transaccional (SqliteUnitOfWork), no la normalización.
--
--  * `ratings` no tiene índice UNIQUE (player, season, version, calculated_at): el
--    repo in-memory añade duplicados si se repite un comando sin idempotencia;
--    SQLite debe preservar esa semántica (la idempotencia es responsabilidad del
--    caller vía idempotency table).
--
-- Todas las sentencias son idempotentes (IF NOT EXISTS) y la migración se gestiona
-- con PRAGMA user_version en connection.py (reproducible de cero o sobre BD existente).

CREATE TABLE IF NOT EXISTS competitions (
    competition_id TEXT PRIMARY KEY,
    external_id    TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    data           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    match_id       TEXT PRIMARY KEY,
    external_id    TEXT NOT NULL UNIQUE,
    competition_id TEXT NOT NULL,
    season_code    TEXT NOT NULL,
    status         TEXT NOT NULL,
    data           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_matches_season ON matches(competition_id, season_code);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);

CREATE TABLE IF NOT EXISTS players (
    player_id   TEXT PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    data        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    team_id     TEXT PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    data        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS correction_proposals (
    proposal_id        TEXT PRIMARY KEY,
    match_external_id  TEXT NOT NULL,
    status             TEXT NOT NULL,
    data               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proposals_match ON correction_proposals(match_external_id);

CREATE TABLE IF NOT EXISTS standing_snapshots (
    snapshot_id    TEXT PRIMARY KEY,
    competition_id TEXT NOT NULL,
    season_code    TEXT NOT NULL,
    generated_at   TEXT NOT NULL,
    data           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_season ON standing_snapshots(competition_id, season_code, generated_at);

CREATE TABLE IF NOT EXISTS leaderboards (
    leaderboard_id TEXT PRIMARY KEY,
    season_code    TEXT NOT NULL,
    category       TEXT NOT NULL,
    generated_at   TEXT NOT NULL,
    data           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leaderboards_season ON leaderboards(season_code, category, generated_at);

CREATE TABLE IF NOT EXISTS ratings (
    rating_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_external_id TEXT NOT NULL,
    season_code        TEXT NOT NULL,
    rating_version     TEXT NOT NULL,
    calculated_at      TEXT NOT NULL,
    data               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ratings_player ON ratings(player_external_id, season_code);

CREATE TABLE IF NOT EXISTS publications (
    publication_id TEXT PRIMARY KEY,
    template_id    TEXT NOT NULL,
    status         TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    data           TEXT NOT NULL
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
    produced_at    TEXT NOT NULL,
    payload        TEXT NOT NULL,
    delivered      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_pending   ON domain_events(delivered, produced_at);
CREATE INDEX IF NOT EXISTS idx_events_aggregate ON domain_events(aggregate_type, aggregate_id);