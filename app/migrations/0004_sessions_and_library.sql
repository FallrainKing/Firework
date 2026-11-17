-- Task sessions: management ID is distinct from the provider-native UUID.
CREATE TABLE session_categories (
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL UNIQUE CHECK(length(name) BETWEEN 1 AND 80),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE task_templates (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 kind TEXT NOT NULL,
 skill TEXT NOT NULL,
 prompt TEXT NOT NULL,
 builtin INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE conversations ADD COLUMN category_id INTEGER REFERENCES session_categories(id);
ALTER TABLE conversations ADD COLUMN draft_prompt TEXT NOT NULL DEFAULT '';
ALTER TABLE conversations ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat';
ALTER TABLE conversations ADD COLUMN skill TEXT NOT NULL DEFAULT 'chat';
ALTER TABLE conversations ADD COLUMN template_id TEXT REFERENCES task_templates(id);
ALTER TABLE conversations ADD COLUMN native_session_id TEXT;
ALTER TABLE conversations ADD COLUMN native_ready INTEGER NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX idx_conversations_native ON conversations(native_session_id) WHERE native_session_id IS NOT NULL;
CREATE INDEX idx_conversations_category ON conversations(category_id, archived, updated_at);
UPDATE conversations SET skill=coalesce((SELECT skill FROM agent_runs WHERE conversation_id=conversations.id ORDER BY rowid LIMIT 1),'chat') WHERE module='agent';
UPDATE conversations SET kind=CASE WHEN skill IN ('search_arxiv','search_library') THEN 'discovery' ELSE 'chat' END WHERE module='agent';
CREATE TABLE conversation_papers (
 conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE RESTRICT,
 PRIMARY KEY(conversation_id,paper_id)
);
CREATE TABLE paper_collections (
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL UNIQUE CHECK(length(name) BETWEEN 1 AND 80),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE paper_collection_items (
 collection_id INTEGER NOT NULL REFERENCES paper_collections(id) ON DELETE CASCADE,
 paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
 PRIMARY KEY(collection_id,paper_id)
);
ALTER TABLE papers ADD COLUMN affiliations TEXT NOT NULL DEFAULT '[]';
ALTER TABLE papers ADD COLUMN affiliation_source TEXT NOT NULL DEFAULT 'missing';
ALTER TABLE papers ADD COLUMN brief_summary TEXT NOT NULL DEFAULT '';
ALTER TABLE papers ADD COLUMN summary_source TEXT NOT NULL DEFAULT 'abstract_excerpt';
ALTER TABLE papers ADD COLUMN metadata_version INTEGER NOT NULL DEFAULT 1;
