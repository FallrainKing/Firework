-- Complete the dynamic skill execution contract while preserving existing rows.
-- A run stores the concrete version and execution policy used at submission.
CREATE TABLE skill_registry_state (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    revision INTEGER NOT NULL DEFAULT 1
);
INSERT INTO skill_registry_state(singleton_id, revision) VALUES (1, 1);

CREATE TABLE skill_imports_new (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL DEFAULT '',
    archive_hash TEXT NOT NULL,
    request_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('uploading','validating','awaiting_config','installed','rejected','failed')),
    report_json TEXT NOT NULL DEFAULT '{}',
    candidate_json TEXT NOT NULL DEFAULT '{}',
    result_version_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO skill_imports_new(
    id, filename, archive_hash, request_key, status, report_json,
    candidate_json, result_version_id, created_at
)
SELECT
    id, '', archive_hash, 'legacy:' || id, 'installed', report_json,
    candidate_json, NULL, created_at
FROM skill_imports;
DROP TABLE skill_imports;
ALTER TABLE skill_imports_new RENAME TO skill_imports;

ALTER TABLE conversations ADD COLUMN skill_version_id INTEGER;
ALTER TABLE agent_runs ADD COLUMN skill_version_id INTEGER;
ALTER TABLE agent_runs ADD COLUMN skill_hash TEXT;
ALTER TABLE agent_runs ADD COLUMN execution_policy_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE task_templates ADD COLUMN skill_version_id INTEGER;
ALTER TABLE task_templates ADD COLUMN source_template_key TEXT;
