ALTER TABLE conversations ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'managed';
ALTER TABLE conversations ADD COLUMN parent_session_id INTEGER REFERENCES conversations(id);
CREATE TABLE native_terminals (
 conversation_id INTEGER PRIMARY KEY REFERENCES conversations(id),
 state TEXT NOT NULL DEFAULT 'stopped',
 generation TEXT,
 error TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
