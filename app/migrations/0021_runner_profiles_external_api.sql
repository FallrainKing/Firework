CREATE TABLE runner_profiles (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 config_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE conversations ADD COLUMN runner_profile_json TEXT;
CREATE TABLE external_operations (
 token_id TEXT NOT NULL, request_key TEXT NOT NULL, body_hash TEXT NOT NULL,
 result_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(token_id,request_key)
);
CREATE TABLE external_audit (
 id INTEGER PRIMARY KEY,token_id TEXT NOT NULL,action TEXT NOT NULL,target TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
