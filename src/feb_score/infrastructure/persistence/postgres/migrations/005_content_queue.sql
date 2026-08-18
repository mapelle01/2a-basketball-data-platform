-- Content Engine — persistent content queue (PostgreSQL).
--
-- Mirror of the SQLite migration 006. One row per generated ContentItem:
-- indexed query columns + a JSONB ``data`` blob (full ContentItem) + the
-- rendered SVG in its own nullable column. UNIQUE story_identity_key enforces
-- cross-run deduplication (a story is queued at most once).
--
-- Non-destructive and idempotent (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS content_queue (
    content_id            TEXT PRIMARY KEY,
    story_identity_key    TEXT NOT NULL UNIQUE,
    season_code           TEXT NOT NULL,
    round_number          INTEGER,
    story_type            TEXT NOT NULL,
    template_id           TEXT NOT NULL,
    template_version      TEXT NOT NULL,
    design_system_version TEXT NOT NULL,
    status                TEXT NOT NULL,
    priority              INTEGER NOT NULL DEFAULT 0,
    created_at            TIMESTAMPTZ NOT NULL,
    updated_at            TIMESTAMPTZ NOT NULL,
    published_at          TIMESTAMPTZ,
    data                  JSONB NOT NULL,
    rendered_svg          TEXT
);

CREATE INDEX IF NOT EXISTS idx_content_queue_status
    ON content_queue (status, priority DESC, created_at);

CREATE INDEX IF NOT EXISTS idx_content_queue_round
    ON content_queue (season_code, round_number, story_type);
