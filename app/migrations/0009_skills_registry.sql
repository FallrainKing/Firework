-- Unified skill registry: dynamic skills (ZIP-installed) share the same
-- registry rows as built-in skills. Versions are immutable; runs bind a
-- concrete skill_version row, so upgrades never mutate history.
CREATE TABLE skills (
    id TEXT PRIMARY KEY,                 -- builtin keys stay as-is ('paper_read'); custom get 'custom:<uuid>'
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'builtin' CHECK(source IN ('builtin','zip')),
    status TEXT NOT NULL DEFAULT 'enabled' CHECK(status IN ('enabled','disabled','archived')),
    default_version_id INTEGER REFERENCES skill_versions(id),
    revision INTEGER NOT NULL DEFAULT 1, -- bumped on every status/default/meta change
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE skill_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL REFERENCES skills(id),
    version TEXT NOT NULL,
    content_hash TEXT NOT NULL,          -- SHA-256 of the normalized file list
    storage_key TEXT NOT NULL,            -- '' for builtin (repo skills/<id>/); else packages/<version_id>
    entry TEXT NOT NULL DEFAULT 'SKILL.md',
    manifest_json TEXT NOT NULL DEFAULT '{}',
    validation_status TEXT NOT NULL DEFAULT 'validated' CHECK(validation_status IN ('validated','incompatible')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (skill_id, version)
);
CREATE TABLE skill_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE skill_category_items (
    skill_id TEXT NOT NULL REFERENCES skills(id),
    category_id INTEGER NOT NULL REFERENCES skill_categories(id),
    PRIMARY KEY (skill_id, category_id)
);
CREATE TABLE skill_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE skill_tag_items (
    skill_id TEXT NOT NULL REFERENCES skills(id),
    tag_id INTEGER NOT NULL REFERENCES skill_tags(id),
    PRIMARY KEY (skill_id, tag_id)
);
CREATE TABLE skill_imports (
    id TEXT PRIMARY KEY,                 -- hex import id
    status TEXT NOT NULL CHECK(status IN ('checking','checked','installed','rejected')),
    archive_hash TEXT NOT NULL DEFAULT '',
    report_json TEXT NOT NULL DEFAULT '{}',
    candidate_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE skill_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT,
    version_id INTEGER,
    action TEXT NOT NULL,                -- import/install/enable/disable/validate-run
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE user_preferences (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL DEFAULT '{}',
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
