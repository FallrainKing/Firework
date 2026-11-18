"""SQL for agent runs and the conversation fields the orchestrator owns."""
from __future__ import annotations

import sqlite3


def find_run(db: sqlite3.Connection, run_id: str):
    return db.execute('SELECT * FROM agent_runs WHERE id=?', (run_id,)).fetchone()


def find_run_by_key(db: sqlite3.Connection, request_key: str):
    return db.execute('SELECT * FROM agent_runs WHERE request_key=?', (request_key,)).fetchone()


def count_active_runs(db: sqlite3.Connection) -> int:
    return db.execute("SELECT count(*) FROM agent_runs WHERE status IN ('queued','running')").fetchone()[0]


def has_active_run(db: sqlite3.Connection, conv_id: int):
    return db.execute(
        "SELECT 1 FROM agent_runs WHERE conversation_id=? AND status IN ('queued','running')",
        (conv_id,),
    ).fetchone()


def list_runs(db: sqlite3.Connection, conversation_id: int | None, q: str):
    sql = 'SELECT * FROM agent_runs WHERE 1=1'
    args = []
    if conversation_id is not None:
        sql += ' AND conversation_id=?'
        args.append(conversation_id)
    if q:
        sql += ' AND (instr(lower(prompt),lower(?))>0 OR instr(lower(answer),lower(?))>0)'
        args.extend([q, q])
    return db.execute(sql + ' ORDER BY created_at DESC, rowid DESC LIMIT 50', args).fetchall()


def run_status_counts(db: sqlite3.Connection) -> dict:
    return dict(db.execute('SELECT status,count(*) FROM agent_runs GROUP BY status').fetchall())


def search_papers(db: sqlite3.Connection, q: str):
    return db.execute(
        "SELECT id,title,authors,abstract,arxiv_id,status FROM papers WHERE instr(lower(coalesce(title,'')),lower(?))>0 OR instr(lower(coalesce(abstract,'')),lower(?))>0 ORDER BY id DESC LIMIT 50",
        (q, q),
    ).fetchall()


def insert_conversation(db: sqlite3.Connection, title: str, skill: str, kind: str, native_session_id: str):
    return db.execute(
        "INSERT INTO conversations(module,title,messages,skill,kind,native_session_id) VALUES ('agent',?,'[]',?,?,?)",
        (title, skill, kind, native_session_id),
    )


def insert_run(db, run_id, request_key, conv_id, skill, prompt, context_json, purpose, attachment_ids_json) -> None:
    db.execute(
        "INSERT INTO agent_runs(id,request_key,conversation_id,skill,prompt,status,skill_version,context_json,purpose,attachment_ids_json) VALUES (?,?,?,?,?,'queued','0.4.0',?,?,?)",
        (run_id, request_key, conv_id, skill, prompt, context_json, purpose, attachment_ids_json),
    )


def clear_draft(db: sqlite3.Connection, conv_id: int) -> None:
    db.execute("UPDATE conversations SET draft_prompt='' WHERE id=?", (conv_id,))


def cancel_run(db: sqlite3.Connection, run_id: str) -> None:
    db.execute(
        "UPDATE agent_runs SET status='cancelled',error='已取消',finished_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('queued','running')",
        (run_id,),
    )


def update_progress(db: sqlite3.Connection, run_id: str, progress_json: str) -> None:
    db.execute("UPDATE agent_runs SET progress_json=? WHERE id=? AND status IN ('queued','running')", (progress_json, run_id))


def set_run_status(db: sqlite3.Connection, run_id: str, status: str) -> None:
    # Guard: a run cancelled while queued must not be revived.
    db.execute("UPDATE agent_runs SET status=? WHERE id=? AND status IN ('queued','running')", (status, run_id))


def finish_run(db, run_id, status, answer, model, usage_json, tool_calls_json, metadata_json, cost, error) -> None:
    # Guard: terminal writes never overwrite a cancellation (or any terminal state).
    db.execute(
        "UPDATE agent_runs SET status=?,answer=?,model=?,usage_json=?,tool_calls_json=?,metadata_json=?,cli_estimated_cost_usd=?,error=?,finished_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('queued','running')",
        (status, answer, model, usage_json, tool_calls_json, metadata_json, cost, error, run_id),
    )


def fail_run_if_active(db: sqlite3.Connection, run_id: str, error: str) -> None:
    db.execute(
        "UPDATE agent_runs SET status='failed',error=?,finished_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('queued','running')",
        (error, run_id),
    )


def fail_run(db: sqlite3.Connection, run_id: str, error: str) -> None:
    db.execute(
        "UPDATE agent_runs SET status='failed',error=?,finished_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('queued','running')",
        (error, run_id),
    )


def run_count(db: sqlite3.Connection, conv_id: int) -> int:
    return db.execute('SELECT count(*) FROM agent_runs WHERE conversation_id=?', (conv_id,)).fetchone()[0]


def last_run(db: sqlite3.Connection, conv_id: int):
    return db.execute(
        'SELECT status,answer,prompt FROM agent_runs WHERE conversation_id=? ORDER BY rowid DESC LIMIT 1',
        (conv_id,),
    ).fetchone()


def session_runs(db: sqlite3.Connection, conv_id: int, before: int | None, limit: int):
    sql = 'SELECT rowid AS sequence,* FROM agent_runs WHERE conversation_id=?'
    args = [conv_id]
    if before is not None:
        sql += ' AND rowid<?'
        args.append(before)
    return db.execute(sql + ' ORDER BY rowid DESC LIMIT ?', args + [limit]).fetchall()


def conversation_ids_matching(db: sqlite3.Connection, q: str) -> list[int]:
    return [r[0] for r in db.execute(
        "SELECT DISTINCT c.id FROM conversations c WHERE c.module='agent' AND EXISTS(SELECT 1 FROM agent_runs r WHERE r.conversation_id=c.id AND (instr(lower(r.prompt),lower(?))>0 OR instr(lower(r.answer),lower(?))>0))",
        (q, q),
    )]


def runs_by_ids(db: sqlite3.Connection, ids) -> dict:
    ids = list(ids)
    if not ids:
        return {}
    placeholders = ','.join('?' * len(ids))
    rows = db.execute(f'SELECT id,status,answer,error FROM agent_runs WHERE id IN ({placeholders})', ids).fetchall()
    return {r['id']: {'status': r['status'], 'answer': r['answer'], 'error': r['error']} for r in rows}


def conversation_paper_ids(db: sqlite3.Connection, conv_id: int) -> list[int]:
    return [p[0] for p in db.execute(
        'SELECT paper_id FROM conversation_papers WHERE conversation_id=? ORDER BY paper_id',
        (conv_id,),
    )]


def past_successful_runs(db: sqlite3.Connection, conv_id: int, run_id: str):
    return db.execute(
        "SELECT prompt,answer FROM agent_runs WHERE conversation_id=? AND status='succeeded' AND id<>? ORDER BY rowid DESC LIMIT 20",
        (conv_id, run_id),
    ).fetchall()


def find_import_request(db: sqlite3.Connection, conv_id: int, run_id: str):
    return db.execute(
        'SELECT id FROM import_requests WHERE conversation_id=? AND run_id=?', (conv_id, run_id)
    ).fetchone()


def set_native_session(db: sqlite3.Connection, conv_id: int, native_session_id: str) -> None:
    db.execute('UPDATE conversations SET native_session_id=? WHERE id=?', (native_session_id, conv_id))


def set_native_ready(db: sqlite3.Connection, conv_id: int) -> None:
    db.execute('UPDATE conversations SET native_ready=1 WHERE id=?', (conv_id,))


def touch_conversation(db: sqlite3.Connection, conv_id: int) -> None:
    db.execute('UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (conv_id,))


def paper_linked_to_conversation(db: sqlite3.Connection, conv_id: int, paper_id: int):
    return db.execute(
        'SELECT 1 FROM conversation_papers WHERE conversation_id=? AND paper_id=?',
        (conv_id, paper_id),
    ).fetchone()


def seed_templates(db: sqlite3.Connection, templates) -> None:
    for t in templates:
        db.execute(
            'INSERT OR IGNORE INTO task_templates(id,name,description,kind,skill,prompt,builtin) VALUES (?,?,?,?,?,?,1)',
            (t['id'], t['name'], t['description'], t['kind'], t['skill'], t['prompt']),
        )


def conversations_missing_native_id(db: sqlite3.Connection):
    return db.execute("SELECT id FROM conversations WHERE module='agent' AND native_session_id IS NULL").fetchall()


def fail_interrupted_runs(db: sqlite3.Connection) -> None:
    db.execute(
        "UPDATE agent_runs SET status='failed', error='Service restarted; retry manually to avoid duplicate usage', finished_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running')"
    )


def fail_orphan_imports(db: sqlite3.Connection) -> None:
    db.execute(
        "UPDATE import_requests SET status='failed',error='服务重启，请手动重试' WHERE status IN ('pending','running') AND run_id IN (SELECT id FROM agent_runs WHERE status IN ('failed','cancelled'))"
    )


def fail_imports_for_run(db: sqlite3.Connection, run_id: str, error: str) -> None:
    db.execute(
        "UPDATE import_requests SET status='failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE run_id=? AND status IN ('pending','running')",
        (error, run_id),
    )
