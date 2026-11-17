ALTER TABLE papers ADD COLUMN doi TEXT;
ALTER TABLE papers ADD COLUMN source_url TEXT;
CREATE UNIQUE INDEX idx_papers_doi ON papers(doi) WHERE doi IS NOT NULL;
ALTER TABLE agent_runs ADD COLUMN context_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE agent_runs ADD COLUMN purpose TEXT NOT NULL DEFAULT 'chat';
CREATE TABLE reader_annotations (
 id TEXT PRIMARY KEY,
 paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
 conversation_id INTEGER REFERENCES conversations(id),
 file_version TEXT NOT NULL,
 page INTEGER NOT NULL CHECK(page>=1),
 kind TEXT NOT NULL CHECK(kind IN ('highlight','note','ink')),
 quote TEXT NOT NULL DEFAULT '',
 content TEXT NOT NULL DEFAULT '',
 color TEXT NOT NULL DEFAULT '#f5d76e',
 rects_json TEXT NOT NULL DEFAULT '[]',
 points_json TEXT NOT NULL DEFAULT '[]',
 deleted INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_reader_annotations_paper ON reader_annotations(paper_id,deleted,page);
CREATE TABLE reader_states (
 conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
 page INTEGER NOT NULL DEFAULT 1,
 zoom TEXT NOT NULL DEFAULT 'fit',
 tab TEXT NOT NULL DEFAULT 'outline',
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(conversation_id,paper_id)
);
CREATE TABLE reader_translations (
 id TEXT PRIMARY KEY,
 paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
 conversation_id INTEGER NOT NULL REFERENCES conversations(id),
 page INTEGER NOT NULL,
 file_version TEXT NOT NULL,
 quote TEXT NOT NULL,
 quote_hash TEXT NOT NULL,
 language TEXT NOT NULL DEFAULT 'zh-CN',
 run_id TEXT NOT NULL REFERENCES agent_runs(id),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(paper_id,file_version,quote_hash,language)
);
CREATE TABLE import_requests (
 id TEXT PRIMARY KEY,
 request_key TEXT NOT NULL UNIQUE,
 channel TEXT NOT NULL CHECK(channel IN ('upload','arxiv','doi','url')),
 source_value TEXT NOT NULL,
 original_filename TEXT,
 file_hash TEXT,
 target_paper_id INTEGER REFERENCES papers(id),
 collection_id INTEGER REFERENCES paper_collections(id),
 conversation_id INTEGER REFERENCES conversations(id),
 run_id TEXT REFERENCES agent_runs(id),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','completed','failed')),
 paper_id INTEGER REFERENCES papers(id),
 message TEXT,
 error TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
UPDATE task_templates SET skill='paper_discover', description='在 arXiv、Crossref 等来源检索，并把结果加入论文库。' WHERE id='discover' AND builtin=1;
