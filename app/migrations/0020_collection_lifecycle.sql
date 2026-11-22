-- Reversible category removal: memberships and source evidence remain intact.
ALTER TABLE paper_collections ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE paper_collections ADD COLUMN deleted_at TEXT;
ALTER TABLE paper_collections ADD COLUMN deletion_group TEXT;
DROP INDEX idx_collection_sibling;
CREATE UNIQUE INDEX idx_collection_sibling ON paper_collections(coalesce(parent_id,0),name) WHERE deleted_at IS NULL;
CREATE INDEX idx_collection_trash ON paper_collections(deletion_group) WHERE deleted_at IS NOT NULL;
