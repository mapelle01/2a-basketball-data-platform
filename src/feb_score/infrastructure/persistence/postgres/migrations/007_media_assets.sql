-- Media assets — the FEB SCORE! media database (evolution of image_overrides).
-- See the SQLite migration (008) for the rationale. BYTEA rather than BLOB.
-- Non-destructive and idempotent.

CREATE TABLE IF NOT EXISTS media_assets (
    asset_id       TEXT NOT NULL PRIMARY KEY,
    kind           TEXT NOT NULL,
    external_id    TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'primary',
    approved       INTEGER NOT NULL DEFAULT 0,
    content_type   TEXT NOT NULL,
    image          BYTEA NOT NULL,
    byte_size      INTEGER NOT NULL,
    source         TEXT,
    source_url     TEXT,
    photographer   TEXT,
    copyright      TEXT,
    license_type   TEXT,
    commercial_use INTEGER NOT NULL DEFAULT 0,
    date_acquired  TEXT,
    expiry         TEXT,
    tags           TEXT,
    notes          TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_media_entity ON media_assets(kind, external_id);

CREATE INDEX IF NOT EXISTS idx_media_approved ON media_assets(kind, external_id, approved);
