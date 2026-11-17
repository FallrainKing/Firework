-- Additive MVP: preserve papers, notes, historical conversations and usage.
CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY,
    request_key TEXT NOT NULL UNIQUE,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    skill TEXT NOT NULL,
    skill_version TEXT NOT NULL DEFAULT '0.1.0',
    prompt TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed')),
    answer TEXT NOT NULL DEFAULT '',
    model TEXT,
    usage_json TEXT NOT NULL DEFAULT '{}',
    tool_calls_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    cli_estimated_cost_usd REAL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);
CREATE INDEX idx_agent_runs_conversation ON agent_runs(conversation_id, created_at);
