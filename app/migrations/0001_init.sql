-- 0001_init: initial schema for the shared memory layer (SQLite).

CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY,
    arxiv_id TEXT UNIQUE,
    title TEXT,
    authors TEXT,
    abstract TEXT,
    categories TEXT,
    source TEXT CHECK(source IN ('upload', 'arxiv', 'import')),
    status TEXT CHECK(status IN ('new', 'pushed', 'reading', 'read', 'dismissed')) DEFAULT 'new',
    pdf_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_created_at ON papers(created_at);

-- Chunks pushed to Qdrant; vectors live in Qdrant, metadata lives here.
CREATE TABLE IF NOT EXISTS chunks_meta (
    id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    chunk_idx INTEGER NOT NULL,
    section TEXT,
    page INTEGER,
    text TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (paper_id, chunk_idx)
);

CREATE INDEX IF NOT EXISTS idx_chunks_meta_paper ON chunks_meta(paper_id);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    note_type TEXT CHECK(note_type IN ('section_analysis', 'annotation', 'chat_summary')) NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notes_paper ON notes(paper_id);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    module TEXT NOT NULL,
    title TEXT,
    messages TEXT NOT NULL DEFAULT '[]',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_jobs (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    errors TEXT NOT NULL DEFAULT '[]',
    status TEXT CHECK(status IN ('pending', 'running', 'completed', 'failed')) DEFAULT 'pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS push_log (
    id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    push_date TEXT NOT NULL,
    channel TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_push_log_paper ON push_log(paper_id);

-- Singleton row (id = 1): interest profile of the paper radar.
CREATE TABLE IF NOT EXISTS interest_profile (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    keywords TEXT NOT NULL DEFAULT '{}',
    negative_keywords TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Singleton row (id = 1): AI mentor knowledge map (nodes/edges/mastery JSON).
CREATE TABLE IF NOT EXISTS knowledge_map (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    nodes TEXT NOT NULL DEFAULT '[]',
    edges TEXT NOT NULL DEFAULT '[]',
    mastery TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    tier TEXT CHECK(tier IN ('fast', 'strong')) NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON llm_usage(created_at);
