CREATE TABLE IF NOT EXISTS auth_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts(
 id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','user')),
 enabled INTEGER NOT NULL DEFAULT 0,workspace_key TEXT NOT NULL UNIQUE,
 session_version INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL,last_login_at INTEGER
);
CREATE TABLE IF NOT EXISTS auth_sessions(
 token_hash TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id),
 csrf TEXT NOT NULL,session_version INTEGER NOT NULL,created_at INTEGER NOT NULL,
 expires_at INTEGER NOT NULL,revoked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_auth_session_account ON auth_sessions(account_id);
CREATE TABLE IF NOT EXISTS auth_attempts(key TEXT PRIMARY KEY,window_start INTEGER NOT NULL,attempts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS auth_audit(
 id INTEGER PRIMARY KEY,actor_id TEXT,action TEXT NOT NULL,target_id TEXT,created_at INTEGER NOT NULL
);
INSERT OR IGNORE INTO auth_meta VALUES ('schema_version','1');
