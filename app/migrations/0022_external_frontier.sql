ALTER TABLE frontier_runs ADD COLUMN origin TEXT NOT NULL DEFAULT 'server';
ALTER TABLE frontier_runs ADD COLUMN external_provenance_json TEXT;
