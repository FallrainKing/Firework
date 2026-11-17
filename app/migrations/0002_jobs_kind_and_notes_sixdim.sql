-- 0002: import_jobs.kind + notes CHECK gains 'six_dim' (P2 deep reading).

-- ① background jobs gain an explicit kind; existing and P1-created rows are
--    plain imports, which is the column's default.
ALTER TABLE import_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'import';

-- ② SQLite cannot ALTER a CHECK constraint in place: rebuild the notes table
--    (new shape → copy rows → drop old → rename → recreate the paper index).
CREATE TABLE notes_new (
    id INTEGER PRIMARY KEY,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    note_type TEXT CHECK(note_type IN ('section_analysis', 'annotation', 'chat_summary', 'six_dim')) NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO notes_new (id, paper_id, note_type, content, created_at)
    SELECT id, paper_id, note_type, content, created_at FROM notes;

DROP TABLE notes;
ALTER TABLE notes_new RENAME TO notes;

CREATE INDEX IF NOT EXISTS idx_notes_paper ON notes(paper_id);
