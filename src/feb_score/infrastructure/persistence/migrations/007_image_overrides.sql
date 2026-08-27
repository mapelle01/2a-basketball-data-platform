-- Image overrides — operator-supplied player photos and team crests.
--
-- Card imagery defaults to the official FEB URLs, resolved at render time. When
-- FEB has no image, or a poor one, an operator can upload a replacement here;
-- the render path consults this table FIRST and only then falls back to FEB and
-- finally to the statistical initials.
--
-- Why in the database and not on disk: the container filesystem is ephemeral
-- (wiped on every deploy), so a file written to disk would not survive the next
-- release. The bytes therefore live in a row, keyed by (kind, external_id) with
-- kind in ('player','team').
--
-- Non-destructive and idempotent (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS image_overrides (
    kind         TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    content_type TEXT NOT NULL,
    image        BLOB NOT NULL,
    byte_size    INTEGER NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (kind, external_id)
);
