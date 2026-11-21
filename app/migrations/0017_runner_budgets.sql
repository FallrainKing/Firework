CREATE TABLE runner_budgets (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 builtin INTEGER NOT NULL DEFAULT 0, values_json TEXT NOT NULL,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE runner_budget_revisions (
 budget_id TEXT NOT NULL REFERENCES runner_budgets(id), revision INTEGER NOT NULL,
 name TEXT NOT NULL, values_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(budget_id,revision)
);
CREATE TABLE runner_budget_settings (
 id INTEGER PRIMARY KEY CHECK(id=1), default_budget_id TEXT REFERENCES runner_budgets(id),
 revision INTEGER NOT NULL DEFAULT 1
);
INSERT INTO runner_budget_settings(id) VALUES(1);
