-- FASE 24.1: catalog backfill needs `name` to be nullable so entities whose
-- official name is not available are stored as name = NULL (documented gap).
-- Additive: only relaxes the NOT NULL constraint; no data loss.
ALTER TABLE players ALTER COLUMN name DROP NOT NULL;
ALTER TABLE teams ALTER COLUMN name DROP NOT NULL;