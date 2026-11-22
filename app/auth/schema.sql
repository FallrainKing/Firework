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
CREATE TABLE IF NOT EXISTS zotero_pairings(
 id TEXT PRIMARY KEY,secret_hash TEXT NOT NULL,user_code TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL,instance_id TEXT NOT NULL,expires_at INTEGER NOT NULL,
 account_id TEXT REFERENCES accounts(id),claimed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS zotero_devices(
 id TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id),
 name TEXT NOT NULL,instance_id TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,
 session_version INTEGER NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
 revoked INTEGER NOT NULL DEFAULT 0,last_seen INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_zotero_account_instance ON zotero_devices(account_id,instance_id);
UPDATE auth_meta SET value='2' WHERE key='schema_version';
CREATE TABLE IF NOT EXISTS external_tokens(
 id TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id),name TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE,prefix TEXT NOT NULL,scopes_json TEXT NOT NULL,
 paper_ids_json TEXT,session_version INTEGER NOT NULL,created_at INTEGER NOT NULL,
 expires_at INTEGER NOT NULL,revoked INTEGER NOT NULL DEFAULT 0,last_seen INTEGER,
 rate_window INTEGER NOT NULL DEFAULT 0,rate_count INTEGER NOT NULL DEFAULT 0
);
UPDATE auth_meta SET value='3' WHERE key='schema_version';
