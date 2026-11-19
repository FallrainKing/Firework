-- Local user identity for the single-user research workbench.
-- The deployment currently has no authentication service, so auth_subject is
-- reserved for future integration and the API always exposes mode='local'.
CREATE TABLE user_profile (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    display_name TEXT NOT NULL DEFAULT '本地研究用户',
    avatar_storage_key TEXT NOT NULL DEFAULT '',
    auth_mode TEXT NOT NULL DEFAULT 'local' CHECK(auth_mode IN ('local')),
    auth_subject TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO user_profile(singleton_id) VALUES (1);
