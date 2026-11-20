CREATE TABLE file_objects (
 hash TEXT PRIMARY KEY CHECK(length(hash)=64),
 storage_key TEXT NOT NULL UNIQUE,
 size INTEGER NOT NULL CHECK(size>0),
 page_count INTEGER NOT NULL CHECK(page_count BETWEEN 1 AND 300),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE paper_documents (
 id TEXT PRIMARY KEY,
 paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE RESTRICT,
 role TEXT NOT NULL CHECK(role IN ('main','supplement')),
 title TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX idx_document_main ON paper_documents(paper_id) WHERE role='main';
CREATE TABLE document_versions (
 id TEXT PRIMARY KEY,
 document_id TEXT NOT NULL REFERENCES paper_documents(id) ON DELETE RESTRICT,
 file_hash TEXT NOT NULL REFERENCES file_objects(hash) ON DELETE RESTRICT,
 label TEXT NOT NULL,
 original_filename TEXT NOT NULL DEFAULT '',
 source TEXT NOT NULL DEFAULT '',
 description TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(document_id,file_hash)
);
ALTER TABLE paper_documents ADD COLUMN current_version_id TEXT REFERENCES document_versions(id);
ALTER TABLE papers ADD COLUMN default_version_id TEXT REFERENCES document_versions(id);
ALTER TABLE reader_annotations ADD COLUMN document_version_id TEXT REFERENCES document_versions(id);
ALTER TABLE conversation_papers ADD COLUMN file_version TEXT;
CREATE INDEX idx_document_paper ON paper_documents(paper_id);
CREATE INDEX idx_annotation_version ON reader_annotations(document_version_id,deleted,page);
