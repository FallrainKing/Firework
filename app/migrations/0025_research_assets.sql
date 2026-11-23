CREATE TABLE run_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES agent_runs(id),
 kind TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_run_events_cursor ON run_events(run_id,id);
CREATE TABLE material_manifests (
 run_id TEXT PRIMARY KEY REFERENCES agent_runs(id), authorized_json TEXT NOT NULL,
 actual_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE conversation_seeds (
 conversation_id INTEGER PRIMARY KEY REFERENCES conversations(id),
 source_session_id INTEGER NOT NULL REFERENCES conversations(id),
 history_json TEXT NOT NULL, transfer_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE research_artifacts (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL, current_revision INTEGER NOT NULL,
 source_key TEXT UNIQUE, source_run_id TEXT REFERENCES agent_runs(id), origin TEXT NOT NULL,
 archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE artifact_papers (
 artifact_id TEXT NOT NULL REFERENCES research_artifacts(id), paper_id INTEGER NOT NULL REFERENCES papers(id),
 PRIMARY KEY(artifact_id,paper_id)
);
CREATE TABLE artifact_revisions (
 artifact_id TEXT NOT NULL REFERENCES research_artifacts(id), revision INTEGER NOT NULL,
 markdown TEXT NOT NULL, evidence_json TEXT NOT NULL, materials_json TEXT NOT NULL,
 status TEXT NOT NULL, producer_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(artifact_id,revision)
);
CREATE TABLE knowledge_items (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, current_revision INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'candidate', needs_review INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE knowledge_revisions (
 knowledge_id TEXT NOT NULL REFERENCES knowledge_items(id), revision INTEGER NOT NULL,
 markdown TEXT NOT NULL, sources_json TEXT NOT NULL, claim_type TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(knowledge_id,revision)
);
CREATE TABLE knowledge_sources (
 knowledge_id TEXT NOT NULL REFERENCES knowledge_items(id), artifact_id TEXT NOT NULL,
 artifact_revision INTEGER NOT NULL,
 FOREIGN KEY(artifact_id,artifact_revision) REFERENCES artifact_revisions(artifact_id,revision),
 PRIMARY KEY(knowledge_id,artifact_id)
);
CREATE VIRTUAL TABLE knowledge_fts USING fts5(id UNINDEXED,title,body,tokenize='unicode61');
CREATE TABLE research_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, resource_type TEXT NOT NULL, resource_id TEXT NOT NULL,
 action TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE version_reader_states (
 conversation_id INTEGER NOT NULL REFERENCES conversations(id), paper_id INTEGER NOT NULL REFERENCES papers(id),
 file_version TEXT NOT NULL, page INTEGER NOT NULL, zoom TEXT NOT NULL, tab TEXT NOT NULL,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(conversation_id,paper_id,file_version)
);
INSERT INTO version_reader_states(conversation_id,paper_id,file_version,page,zoom,tab)
 SELECT r.conversation_id,r.paper_id,v.file_hash,r.page,r.zoom,r.tab FROM reader_states r
 JOIN papers p ON p.id=r.paper_id JOIN document_versions v ON v.id=p.default_version_id;
CREATE TABLE document_text_chunks (
 version_id TEXT NOT NULL REFERENCES document_versions(id), chunk_index INTEGER NOT NULL,
 text TEXT NOT NULL, page INTEGER, section TEXT, PRIMARY KEY(version_id,chunk_index)
);
INSERT INTO document_text_chunks(version_id,chunk_index,text,page,section)
 SELECT p.default_version_id,c.chunk_idx,c.text,c.page,c.section FROM chunks_meta c JOIN papers p ON p.id=c.paper_id
 WHERE p.default_version_id IS NOT NULL;
CREATE TABLE annotation_migrations (
 source_id TEXT NOT NULL REFERENCES reader_annotations(id), target_version_id TEXT NOT NULL REFERENCES document_versions(id),
 target_id TEXT NOT NULL REFERENCES reader_annotations(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(source_id,target_version_id)
);
CREATE TABLE research_files (
 hash TEXT PRIMARY KEY CHECK(length(hash)=64), paper_id INTEGER NOT NULL REFERENCES papers(id),
 filename TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE artifact_files (
 artifact_id TEXT NOT NULL, revision INTEGER NOT NULL, file_hash TEXT NOT NULL REFERENCES research_files(hash),
 FOREIGN KEY(artifact_id,revision) REFERENCES artifact_revisions(artifact_id,revision),
 PRIMARY KEY(artifact_id,revision,file_hash)
);
