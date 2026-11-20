CREATE TABLE paper_collections_new (
 id INTEGER PRIMARY KEY,name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 parent_id INTEGER REFERENCES paper_collections_new(id) ON DELETE RESTRICT,
 CHECK(parent_id IS NULL OR parent_id<>id)
);
INSERT INTO paper_collections_new(id,name,created_at) SELECT id,name,created_at FROM paper_collections;
DROP TABLE paper_collections;
ALTER TABLE paper_collections_new RENAME TO paper_collections;
CREATE UNIQUE INDEX idx_collection_sibling ON paper_collections(coalesce(parent_id,0),name);
CREATE TABLE zotero_links (
 device_id TEXT NOT NULL,library_key TEXT NOT NULL,item_key TEXT NOT NULL,
 paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE RESTRICT,
 source_json TEXT NOT NULL,source_hash TEXT NOT NULL,metadata_version INTEGER NOT NULL,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(device_id,library_key,item_key)
);
CREATE TABLE zotero_attachment_links (
 device_id TEXT NOT NULL,library_key TEXT NOT NULL,attachment_key TEXT NOT NULL,
 item_key TEXT NOT NULL,document_id TEXT NOT NULL REFERENCES paper_documents(id),
 version_id TEXT NOT NULL REFERENCES document_versions(id),file_hash TEXT NOT NULL,
 PRIMARY KEY(device_id,library_key,attachment_key)
);
CREATE TABLE paper_tags (
 paper_id INTEGER NOT NULL REFERENCES papers(id),tag TEXT NOT NULL,
 source_device TEXT NOT NULL DEFAULT '',PRIMARY KEY(paper_id,tag,source_device)
);
CREATE TABLE zotero_exports (
 id TEXT PRIMARY KEY,device_id TEXT NOT NULL,paper_id INTEGER NOT NULL REFERENCES papers(id),
 request_key TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','leased','completed','failed')),
 lease_token TEXT,lease_until INTEGER NOT NULL DEFAULT 0,result_json TEXT,error TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_zotero_export_device ON zotero_exports(device_id,status,created_at);
