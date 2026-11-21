CREATE TABLE runner_connections (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 enabled INTEGER NOT NULL DEFAULT 1, config_json TEXT NOT NULL, secret_cipher TEXT NOT NULL,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE runner_connection_settings (
 id INTEGER PRIMARY KEY CHECK(id=1), default_connection_id TEXT REFERENCES runner_connections(id),
 revision INTEGER NOT NULL DEFAULT 1
);
INSERT INTO runner_connection_settings(id) VALUES(1);
ALTER TABLE conversations ADD COLUMN runner_connection_json TEXT;
