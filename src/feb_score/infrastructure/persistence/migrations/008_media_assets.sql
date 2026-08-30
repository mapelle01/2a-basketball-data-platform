-- Media assets — the FEB SCORE! media database (evolution of image_overrides).
--
-- image_overrides stores ONE operator image per (kind, external_id). The media
-- database keeps MANY photos per entity, each with rights metadata, so the
-- system can hold a licensed library and choose the right photo per post while
-- respecting the licence. Bytes live in the row for the same reason as
-- image_overrides: the container filesystem is wiped on every deploy.
--
-- The licence gate is `approved` (+ `commercial_use`): the selection path uses
-- ONLY approved photos, never an unlicensed one. `role` is primary/action/
-- alternate; `tags` is free-form JSON (orientation, face_visible, ...).
--
-- Non-destructive and idempotent. Comments stay on their own lines (the SQLite
-- statement splitter joins lines, so an inline -- would comment out the rest).

CREATE TABLE IF NOT EXISTS media_assets (
    asset_id       TEXT NOT NULL PRIMARY KEY,
    kind           TEXT NOT NULL,
    external_id    TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'primary',
    approved       INTEGER NOT NULL DEFAULT 0,
    content_type   TEXT NOT NULL,
    image          BLOB NOT NULL,
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
