-- FASE 8 — SQLite feasibility: proposed schema (design artifact, not yet wired).
--
-- Strategy:
--   * Aggregates whose identity is a domain UUID -> UUID PK (TEXT).
--   * External business keys -> UNIQUE columns with supporting indexes.
--   * Value Objects -> scalar columns (IDs/enums as TEXT, ratings as REAL, dates/times ISO TEXT).
--   * Nested / list-of-dict structures that are never filtered -> JSON TEXT columns.
--   * Player/Team registrations -> normalized `registrations` table (single source of truth,
--     removes the current dual-write between Player.registrations and Team.registrations).
--   * matches.version -> optimistic concurrency (UPDATE ... WHERE version = :expected).
--   * domain_events -> append-only event log written in the same transaction as the aggregate
--     change (outbox-lite); a dispatcher may later publish from it.
--
-- SQLite notes: FK enforcement requires PRAGMA foreign_keys = ON per connection.
-- matches.competition_id deliberately has NO FK: the collector writes matches for a
-- competition that may not be defined yet ("unknown" is a legal value).

CREATE TABLE IF NOT EXISTS competitions (
    competition_id   TEXT PRIMARY KEY,          -- CompetitionId
    external_id      TEXT NOT NULL UNIQUE,      -- ExternalId (feb-api key)
    name             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seasons (
    competition_external_id TEXT NOT NULL REFERENCES competitions(external_id) ON DELETE CASCADE,
    season_code             TEXT NOT NULL,      -- SeasonCode
    rules_version           TEXT NOT NULL,
    PRIMARY KEY (competition_external_id, season_code)
);

CREATE TABLE IF NOT EXISTS rounds (
    competition_external_id TEXT NOT NULL REFERENCES competitions(external_id) ON DELETE CASCADE,
    season_code             TEXT NOT NULL,
    number                  INTEGER NOT NULL,   -- RoundDefinition.number
    label                   TEXT NOT NULL,      -- RoundDefinition.label
    PRIMARY KEY (competition_external_id, season_code, number),
    FOREIGN KEY (competition_external_id, season_code)
        REFERENCES seasons(competition_external_id, season_code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS matches (
    match_id           TEXT PRIMARY KEY,        -- MatchId (uuid)
    external_id        TEXT NOT NULL UNIQUE,    -- ExternalId (feb-api key)
    competition_id     TEXT NOT NULL,           -- CompetitionId (no FK, may be "unknown")
    season_code        TEXT NOT NULL,           -- SeasonCode
    round_number       INTEGER NOT NULL,
    home_team_id       TEXT NOT NULL,           -- ExternalId
    away_team_id       TEXT NOT NULL,           -- ExternalId
    scheduled_at       TEXT NOT NULL,           -- datetime ISO-8601
    status             TEXT NOT NULL,           -- MatchStatus enum value
    version            INTEGER NOT NULL DEFAULT 1,
    -- free-form dicts -> JSON
    source             TEXT,
    venue              TEXT,
    raw                TEXT,
    -- value objects / nested structures -> JSON
    score_summary      TEXT,                    -- {home_score, away_score, periods:[{period,home,away}]}
    home_team_stats    TEXT,                    -- TeamStats
    away_team_stats    TEXT,                    -- TeamStats
    player_stats       TEXT,                    -- [PlayerStats]
    correction_history TEXT,                    -- [{correction_id,approved_at,approver_id,reason,previous_version,new_version}]
    CHECK (home_team_id <> away_team_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_season   ON matches(competition_id, season_code);
CREATE INDEX IF NOT EXISTS idx_matches_status   ON matches(status);

CREATE TABLE IF NOT EXISTS players (
    player_id      TEXT PRIMARY KEY,            -- PlayerId (uuid)
    external_id    TEXT NOT NULL UNIQUE,        -- ExternalId (feb-api key)
    name           TEXT NOT NULL,
    birth_date     TEXT,                        -- date ISO-8601
    nationality    TEXT,
    position       TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    team_id      TEXT PRIMARY KEY,              -- TeamId (uuid)
    external_id  TEXT NOT NULL UNIQUE,          -- ExternalId (feb-api key)
    name         TEXT NOT NULL
);

-- Single normalized registration table (replaces the dual-write on Player and Team).
CREATE TABLE IF NOT EXISTS registrations (
    registration_id   TEXT PRIMARY KEY,         -- uuid (shared by both sides today)
    player_external_id TEXT NOT NULL REFERENCES players(external_id) ON DELETE CASCADE,
    team_external_id   TEXT NOT NULL REFERENCES teams(external_id) ON DELETE CASCADE,
    season_code        TEXT NOT NULL,           -- SeasonCode
    dorsal             INTEGER,
    registered_at      TEXT,                    -- date ISO-8601
    registered_to      TEXT,                    -- date ISO-8601
    role               TEXT,
    UNIQUE (player_external_id, season_code)    -- domain invariant: one registration per player/season
);
CREATE INDEX IF NOT EXISTS idx_registrations_team ON registrations(team_external_id, season_code);

CREATE TABLE IF NOT EXISTS correction_proposals (
    proposal_id          TEXT PRIMARY KEY,      -- CorrectionProposalId (uuid)
    match_external_id    TEXT NOT NULL REFERENCES matches(external_id) ON DELETE CASCADE,
    proposed_by_id       TEXT NOT NULL,         -- Actor.id
    proposed_by_role     TEXT NOT NULL,         -- Actor.role
    proposed_at          TEXT NOT NULL,         -- datetime ISO-8601
    reason               TEXT NOT NULL,
    changes              TEXT NOT NULL,         -- JSON [{"op":...}]
    status               TEXT NOT NULL DEFAULT 'PROPOSED',
    approved_by_id       TEXT,
    approved_by_role     TEXT,
    approved_at          TEXT,
    previous_version     TEXT,
    new_version          TEXT,
    rejected_by_id       TEXT,
    rejected_by_role     TEXT,
    rejected_at          TEXT,
    rejection_reason     TEXT,
    comment              TEXT
);
CREATE INDEX IF NOT EXISTS idx_proposals_match ON correction_proposals(match_external_id);

CREATE TABLE IF NOT EXISTS standing_snapshots (
    snapshot_id      TEXT PRIMARY KEY,          -- SnapshotId (uuid)
    competition_id   TEXT NOT NULL,             -- CompetitionId
    season_code      TEXT NOT NULL,             -- SeasonCode
    generated_at     TEXT NOT NULL,             -- datetime ISO-8601
    rounds_included  INTEGER NOT NULL DEFAULT 0,
    matches_count    INTEGER NOT NULL,
    rules_version    TEXT NOT NULL,
    description      TEXT,
    entries          TEXT NOT NULL              -- JSON [StandingEntry]
);
CREATE INDEX IF NOT EXISTS idx_snapshots_season ON standing_snapshots(competition_id, season_code, generated_at);

CREATE TABLE IF NOT EXISTS leaderboards (
    leaderboard_id   TEXT PRIMARY KEY,          -- LeaderboardId (uuid)
    season_code      TEXT NOT NULL,             -- SeasonCode
    category         TEXT NOT NULL,             -- LEADERBOARD_CATEGORIES key
    generated_at     TEXT NOT NULL,             -- datetime ISO-8601
    min_games        INTEGER NOT NULL,
    entries          TEXT NOT NULL              -- JSON [LeaderboardEntry]
);
CREATE INDEX IF NOT EXISTS idx_leaderboards_season ON leaderboards(season_code, category, generated_at);

CREATE TABLE IF NOT EXISTS ratings (
    rating_id          INTEGER PRIMARY KEY AUTOINCREMENT,  -- surrogate; PlayerRating has no own id
    player_external_id TEXT NOT NULL REFERENCES players(external_id) ON DELETE CASCADE,
    season_code        TEXT NOT NULL,
    rating_value       REAL NOT NULL,           -- RatingValue
    rating_version     TEXT NOT NULL,           -- RatingVersion
    calculated_at      TEXT NOT NULL,           -- datetime ISO-8601
    source_stats       TEXT NOT NULL            -- JSON [PlayerStats dicts]
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ratings_latest
    ON ratings(player_external_id, season_code, rating_version, calculated_at);

CREATE TABLE IF NOT EXISTS publications (
    publication_id   TEXT PRIMARY KEY,          -- PublicationId (uuid)
    title            TEXT NOT NULL,
    content          TEXT NOT NULL,
    template_id      TEXT NOT NULL,
    refs             TEXT NOT NULL,             -- JSON [{"type","id"}]
    created_at       TEXT NOT NULL,             -- datetime ISO-8601
    created_by_id    TEXT,
    created_by_role  TEXT,
    published_at     TEXT,
    status           TEXT NOT NULL DEFAULT 'DRAFT',
    locale           TEXT
);

-- Command idempotency (INSERT OR IGNORE marks; SELECT before dispatch).
CREATE TABLE IF NOT EXISTS idempotency (
    command_id     TEXT PRIMARY KEY,
    processed_at   TEXT NOT NULL
);

-- Event log (outbox-lite): every DomainEvent produced inside a command transaction
-- is inserted here atomically with the aggregate change, then a dispatcher can
-- publish and mark delivered. aggregate_id allows per-aggregate replay.
CREATE TABLE IF NOT EXISTS domain_events (
    event_id       TEXT PRIMARY KEY,
    event_type     TEXT NOT NULL,               -- e.g. 'MatchFinalized'
    aggregate_type TEXT NOT NULL,               -- e.g. 'Match'
    aggregate_id   TEXT NOT NULL,               -- aggregate key (match external_id, proposal_id, ...)
    produced_at    TEXT NOT NULL,               -- EventMeta.produced_at
    payload        TEXT NOT NULL,               -- JSON event payload
    delivered      INTEGER NOT NULL DEFAULT 0   -- 0=pending, 1=dispatched
);
CREATE INDEX IF NOT EXISTS idx_events_pending  ON domain_events(delivered, produced_at);
CREATE INDEX IF NOT EXISTS idx_events_aggregate ON domain_events(aggregate_type, aggregate_id);