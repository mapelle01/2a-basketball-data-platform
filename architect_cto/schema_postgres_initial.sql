-- Schema inicial PostgreSQL para plataforma FEB (Core Engine)
-- Fecha: 2026-08-07

-- Extensiones útiles
CREATE EXTENSION IF NOT EXISTS pgcrypto; -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Competitions
CREATE TABLE IF NOT EXISTS competitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    country TEXT,
    gender TEXT,
    level INT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Seasons
CREATE TABLE IF NOT EXISTS seasons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competition_id UUID NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT,
    start_date DATE,
    end_date DATE,
    metadata JSONB,
    UNIQUE (competition_id, code)
);

-- Rounds (jornadas)
CREATE TABLE IF NOT EXISTS rounds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    season_id UUID NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    number INT,
    name TEXT,
    start_date DATE,
    end_date DATE,
    metadata JSONB,
    UNIQUE (season_id, number)
);

-- Venues
CREATE TABLE IF NOT EXISTS venues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    city TEXT,
    capacity INT,
    metadata JSONB
);

-- Teams
CREATE TABLE IF NOT EXISTS teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT, -- id original de la FEB si existe
    name TEXT NOT NULL,
    short_name TEXT,
    code TEXT,
    crest_url TEXT,
    venue_id UUID REFERENCES venues(id),
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    UNIQUE (external_id)
);
CREATE INDEX IF NOT EXISTS idx_teams_name ON teams USING gin (to_tsvector('simple', name));

-- Players
CREATE TABLE IF NOT EXISTS players (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT, -- id original
    name TEXT NOT NULL,
    dob DATE,
    nationality TEXT,
    height_cm INT,
    position TEXT,
    photo_url TEXT,
    current_team_id UUID REFERENCES teams(id),
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    UNIQUE (external_id)
);
CREATE INDEX IF NOT EXISTS idx_players_name ON players USING gin (to_tsvector('simple', name));

-- Officials (árbitros)
CREATE TABLE IF NOT EXISTS officials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    license TEXT,
    nationality TEXT,
    metadata JSONB
);

-- Matches (source-of-truth por partido)
CREATE TABLE IF NOT EXISTS matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT UNIQUE, -- id del sistema FEB (si existe)
    season_id UUID REFERENCES seasons(id) ON DELETE SET NULL,
    round_id UUID REFERENCES rounds(id) ON DELETE SET NULL,
    home_team_id UUID REFERENCES teams(id),
    away_team_id UUID REFERENCES teams(id),
    venue_id UUID REFERENCES venues(id),
    scheduled_at TIMESTAMP WITH TIME ZONE,
    status TEXT, -- SCHEDULED/FINISHED/CANCELLED
    score_home INT,
    score_away INT,
    score_text TEXT,
    duration_seconds INT,
    raw_json JSONB, -- snapshot of normalized raw payload (short)
    raw_json_path TEXT, -- S3 path to full raw JSON
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_matches_season_date ON matches (season_id, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_matches_external_id ON matches (external_id);

-- Team Stats (por partido)
CREATE TABLE IF NOT EXISTS team_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id),
    pts INT,
    fgm INT, fga INT, p3m INT, p3a INT, ftm INT, fta INT,
    reb_off INT, reb_def INT, ast INT, to INT, fouls INT,
    metadata JSONB,
    raw_json JSONB
);
CREATE INDEX IF NOT EXISTS idx_teamstats_match_team ON team_stats (match_id, team_id);

-- Player Stats (por partido)
CREATE TABLE IF NOT EXISTS player_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    player_id UUID REFERENCES players(id),
    team_id UUID REFERENCES teams(id),
    minutes TEXT,
    pts INT, reb INT, ast INT, st INT, bs INT, tov INT, fouls INT, val INT,
    fgm INT, fga INT, p3m INT, p3a INT, ftm INT, fta INT,
    metadata JSONB,
    raw_json JSONB
);
CREATE INDEX IF NOT EXISTS idx_playerstats_match_player ON player_stats (match_id, player_id);

-- Events / Incidencias (substitutions, fouls, technicals)
CREATE TABLE IF NOT EXISTS match_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    minute INT,
    type TEXT,
    actor_id UUID, -- player/official/team id
    description TEXT,
    metadata JSONB
);
CREATE INDEX IF NOT EXISTS idx_events_match ON match_events (match_id, minute);

-- Standings (snapshots)
CREATE TABLE IF NOT EXISTS standings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    season_id UUID NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    snapshot_at TIMESTAMP WITH TIME ZONE NOT NULL,
    team_id UUID NOT NULL REFERENCES teams(id),
    position INT,
    played INT,
    won INT,
    lost INT,
    points INT,
    goal_diff INT,
    metadata JSONB
);
CREATE INDEX IF NOT EXISTS idx_standings_season_snapshot ON standings (season_id, snapshot_at DESC);

-- Leaderboards
CREATE TABLE IF NOT EXISTS leaderboards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    season_id UUID REFERENCES seasons(id),
    category TEXT, -- points, rebounds, assists, rating
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    entries JSONB -- array of {rank, player_id, team_id, total, games, average}
);
CREATE INDEX IF NOT EXISTS idx_leaderboards_season_cat ON leaderboards (season_id, category);

-- Snapshot / Raw archive (referencia a S3)
CREATE TABLE IF NOT EXISTS raw_archives (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id UUID REFERENCES matches(id),
    source TEXT, -- e.g., BoxScore, TeamStats
    s3_path TEXT NOT NULL,
    schema_version TEXT,
    size_bytes BIGINT,
    stored_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_raw_archives_match ON raw_archives (match_id);

-- Audit / ingestion log
CREATE TABLE IF NOT EXISTS ingestion_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_external_id TEXT,
    event_type TEXT,
    status TEXT,
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- MISC: materialized views and helper functions will crearse posteriormente.

-- Partitioning recommendation: si escala, particionar matches y player_stats por season_id or scheduled_at (range) para rendimiento.

-- End schema
