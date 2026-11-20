-- Multiple clicks can share one pending transfer while each request remains idempotent.
CREATE TABLE zotero_export_request_keys (
 request_key TEXT PRIMARY KEY,
 export_id TEXT NOT NULL REFERENCES zotero_exports(id) ON DELETE CASCADE
);
INSERT INTO zotero_export_request_keys(request_key,export_id) SELECT request_key,id FROM zotero_exports;
