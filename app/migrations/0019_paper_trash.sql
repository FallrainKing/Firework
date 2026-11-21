-- Reversible library removal. Files, annotations, sessions and external mappings
-- remain intact, so restoring does not re-import or duplicate a paper.
ALTER TABLE papers ADD COLUMN deleted_at TEXT;
CREATE INDEX idx_papers_deleted_at ON papers(deleted_at);
