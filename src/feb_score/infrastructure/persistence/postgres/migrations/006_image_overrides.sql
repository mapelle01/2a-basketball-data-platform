-- Image overrides — operator-supplied player photos and team crests.
-- See the SQLite migration (007) for the rationale. BYTEA rather than BLOB.
-- Non-destructive and idempotent.

CREATE TABLE IF NOT EXISTS image_overrides (
    kind         TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    content_type TEXT NOT NULL,
    image        BYTEA NOT NULL,
    byte_size    INTEGER NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (kind, external_id)
);
