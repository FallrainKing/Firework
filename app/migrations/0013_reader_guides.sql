CREATE TABLE reader_guide_tasks (
 id TEXT PRIMARY KEY,paper_id INTEGER NOT NULL REFERENCES papers(id),file_version TEXT NOT NULL,
 semantic_key TEXT NOT NULL,request_key TEXT NOT NULL UNIQUE,request_json TEXT NOT NULL,
 skill_id TEXT NOT NULL,skill_version_id INTEGER REFERENCES skill_versions(id),skill_hash TEXT,
 conversation_id INTEGER REFERENCES conversations(id),agent_run_id TEXT UNIQUE REFERENCES agent_runs(id),
 status TEXT NOT NULL DEFAULT 'dispatching',manifest_id TEXT NOT NULL UNIQUE,
 payload_json TEXT,validation_json TEXT NOT NULL DEFAULT '[]',coverage_json TEXT NOT NULL DEFAULT '{}',
 active INTEGER NOT NULL DEFAULT 0,hidden INTEGER NOT NULL DEFAULT 0,error TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,finished_at TEXT
);
CREATE UNIQUE INDEX idx_guide_semantic_active ON reader_guide_tasks(semantic_key) WHERE hidden=0 AND status IN ('dispatching','queued','running','staging','published','partial');
CREATE INDEX idx_guide_paper ON reader_guide_tasks(paper_id,created_at DESC);
CREATE TABLE reader_guide_blocks (
 id TEXT NOT NULL,task_id TEXT NOT NULL REFERENCES reader_guide_tasks(id),material_id TEXT NOT NULL,
 page INTEGER NOT NULL,text TEXT NOT NULL,data_json TEXT NOT NULL,
 PRIMARY KEY(task_id,id)
);
CREATE TABLE reader_guide_items (
 id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES reader_guide_tasks(id),item_key TEXT NOT NULL,
 item_json TEXT NOT NULL,anchors_json TEXT NOT NULL,location_status TEXT NOT NULL,
 UNIQUE(task_id,item_key)
);
ALTER TABLE reader_annotations ADD COLUMN origin TEXT NOT NULL DEFAULT 'user';
ALTER TABLE reader_annotations ADD COLUMN guide_task_id TEXT REFERENCES reader_guide_tasks(id);
ALTER TABLE reader_annotations ADD COLUMN guide_item_id TEXT REFERENCES reader_guide_items(id);
ALTER TABLE reader_annotations ADD COLUMN derived_from TEXT REFERENCES reader_guide_items(id);
CREATE UNIQUE INDEX idx_annotation_adopted ON reader_annotations(derived_from) WHERE derived_from IS NOT NULL;
CREATE TABLE reader_guide_adoptions(request_key TEXT PRIMARY KEY,item_id TEXT NOT NULL REFERENCES reader_guide_items(id),annotation_id TEXT NOT NULL REFERENCES reader_annotations(id));
