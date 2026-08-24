-- Content Engine — persistent content queue.
--
-- The pipeline (Insight → Planner → Copy → Render → Validate) writes one row
-- per generated ContentItem here. Persistence gives the queue what an in-memory
-- store cannot: cross-run deduplication (a story is queued at most once, keyed
-- on story_identity_key), an audit trail (created/updated/published), and the
-- data needed for novelty scoring ("did we already cover this story type in
-- this round?").
--
-- Storage shape mirrors the rest of the platform: indexed query columns + a
-- ``data`` JSON blob holding the full ContentItem (story, copy, validations).
-- The bulky rendered SVG lives in its own nullable column so list queries stay
-- light. INSERT OR IGNORE on the UNIQUE story_identity_key enforces dedup.
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
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    published_at          TEXT,
    data                  TEXT NOT NULL,
    rendered_svg          TEXT
);

CREATE INDEX IF NOT EXISTS idx_content_queue_status
    ON content_queue (status, priority DESC, created_at);

CREATE INDEX IF NOT EXISTS idx_content_queue_round
    ON content_queue (season_code, round_number, story_type);
