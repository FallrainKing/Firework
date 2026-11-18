-- Async execution: allow 'cancelled' status and store streaming progress.
-- SQLite cannot ALTER a CHECK constraint, so rebuild the table (12-step
-- procedure; the migration runner disables foreign keys around the script).
CREATE TABLE agent_runs_new (
    id TEXT PRIMARY KEY,
    request_key TEXT NOT NULL UNIQUE,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    skill TEXT NOT NULL,
    skill_version TEXT NOT NULL DEFAULT '0.1.0',
    prompt TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
    answer TEXT NOT NULL DEFAULT '',
    model TEXT,
    usage_json TEXT NOT NULL DEFAULT '{}',
    tool_calls_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    cli_estimated_cost_usd REAL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    context_json TEXT NOT NULL DEFAULT '[]',
    purpose TEXT NOT NULL DEFAULT 'chat',
    attachment_ids_json TEXT NOT NULL DEFAULT '[]',
    progress_json TEXT NOT NULL DEFAULT '{}'
);
INSERT INTO agent_runs_new SELECT *, '{}' FROM agent_runs;
DROP TABLE agent_runs;
ALTER TABLE agent_runs_new RENAME TO agent_runs;
CREATE INDEX idx_agent_runs_conversation ON agent_runs(conversation_id, created_at);
