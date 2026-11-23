ALTER TABLE reader_translations ADD COLUMN anchor_json TEXT NOT NULL DEFAULT '{}';
CREATE TABLE connection_tests (
 id TEXT PRIMARY KEY, connection_id TEXT NOT NULL REFERENCES runner_connections(id), connection_revision INTEGER NOT NULL,
 kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'running', result_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TEXT
);
CREATE TABLE connection_models (
 parent_id TEXT NOT NULL REFERENCES runner_connections(id), connection_id TEXT NOT NULL REFERENCES runner_connections(id),
 PRIMARY KEY(parent_id,connection_id)
);
CREATE TABLE workspace_contexts (
 id TEXT PRIMARY KEY, payload_json TEXT NOT NULL DEFAULT '{}', revision INTEGER NOT NULL DEFAULT 0,
 shared INTEGER NOT NULL DEFAULT 0, auth_version INTEGER NOT NULL DEFAULT 0,
 observed_at INTEGER NOT NULL DEFAULT 0, expires_at INTEGER NOT NULL DEFAULT 0
);
ALTER TABLE workspace_contexts ADD COLUMN auth_session_hash TEXT NOT NULL DEFAULT '';
CREATE TABLE context_selections (
 id TEXT PRIMARY KEY, context_id TEXT NOT NULL REFERENCES workspace_contexts(id), anchor_json TEXT NOT NULL, expires_at INTEGER NOT NULL
);
ALTER TABLE reader_annotations ADD COLUMN source_artifact_id TEXT REFERENCES research_artifacts(id);
CREATE TABLE reader_external_translations (
 id TEXT PRIMARY KEY, paper_id INTEGER NOT NULL REFERENCES papers(id), artifact_id TEXT NOT NULL REFERENCES research_artifacts(id),
 page INTEGER NOT NULL, file_version TEXT NOT NULL, quote TEXT NOT NULL, rects_json TEXT NOT NULL,
 language TEXT NOT NULL, answer TEXT NOT NULL, status TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE external_submissions (
 token_id TEXT NOT NULL, client_job_id TEXT NOT NULL, body_hash TEXT NOT NULL, receipt_json TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(token_id,client_job_id)
);
ALTER TABLE reader_annotations ADD COLUMN source_annotation_id TEXT REFERENCES reader_annotations(id);
CREATE UNIQUE INDEX idx_external_annotation_adopted ON reader_annotations(source_annotation_id) WHERE source_annotation_id IS NOT NULL;
ALTER TABLE workspace_contexts ADD COLUMN context_revision INTEGER NOT NULL DEFAULT 0;
