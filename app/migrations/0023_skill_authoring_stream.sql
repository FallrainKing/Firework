CREATE TABLE skill_drafts (
 skill_id TEXT PRIMARY KEY REFERENCES skills(id), revision INTEGER NOT NULL DEFAULT 1,
 body_json TEXT NOT NULL, published_revision INTEGER, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE skill_placements (
 skill_id TEXT PRIMARY KEY REFERENCES skills(id), revision INTEGER NOT NULL DEFAULT 1,
 surfaces_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE agent_runs ADD COLUMN stream_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN entry_context TEXT;
