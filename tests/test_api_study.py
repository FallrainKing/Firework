"""Task 5: 解读/对比 API 路由 — interpret job + compare 同步端点 + 0002 迁移.

覆盖 brief 的 9 个测试：interpret 创建 200 / 404 / 409；fake gateway 跑
run_interpretation → job done 且 notes 存在（含重跑幂等——契约 2）；gateway
全挂（six-dim 调用抛 "all providers failed"）→ job failed、errors 非空、
已成功节 notes 保留（契约 3，Review Focus #3）；compare 成功（含去重）/
数量校验 400 / 不存在 id 400（契约 4）；migration 0002 表重建。

 seeding 经测试线程的第二个连接（WAL 允许并发访问，与 test_api_notes
同模式）；compare 的向量经 ``client.app.state.store``（lifespan 建的
:memory: qdrant）写入。
"""

from __future__ import annotations

import json
import sqlite3
import time

import pytest
from conftest import FakeGateway

from app.config import Settings
from app.db import MIGRATIONS_DIR, get_conn
from app.llm.gateway import LLMExhaustedError
from app.rag.vector_store import ChunkPoint

SIX_KEYS = (
    "background",
    "innovation",
    "architecture",
    "formulas",
    "experiments",
    "limitations",
)

SIX_DIM_JSON = json.dumps(
    {k: f"{k} 的中文解读。" for k in SIX_KEYS}, ensure_ascii=False
)

TITLE_A = "对比论文甲：强化学习方法"
ABSTRACT_A = "论文甲的摘要：提出一种基于强化学习的训练技巧。"
TITLE_B = "对比论文乙：监督对比方法"
ABSTRACT_B = "论文乙的摘要：提出一种监督对比学习框架。"

CHUNK_A_P2 = "论文甲的方法细节：使用策略梯度与经验回放。"
CHUNK_A_P5 = "论文甲的实验结果：在标准基准上提升三个点。"
CHUNK_B_P3 = "论文乙的实验设置：在三个公开数据集上评测。"

MARKDOWN_REPLY = (
    "| 维度 | 对比论文甲 | 对比论文乙 |\n"
    "|---|---|---|\n"
    "| 方法 | 策略梯度 [P1|2] | 对比学习 |\n"
    "| 核心思想 | 强化训练技巧 [P1|5] | 监督对比框架 |\n"
    "| 实验设置 | 标准基准 | 三个数据集 [P2|3] |\n"
    "| 结果 | 提升三点 | 稳定收敛 |\n"
    "| 局限 | 样本效率低 | 需要大量标注 |\n"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _seed_conn(tmp_path) -> sqlite3.Connection:
    """A test-thread connection to the same app.db the lifespan opened."""
    conn = sqlite3.connect(tmp_path / "app.db")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _add_paper(
    conn,
    title="解读目标论文",
    status="new",
    sections=(),
    abstract=None,
) -> int:
    cur = conn.execute(
        "INSERT INTO papers (title, abstract, status) VALUES (?, ?, ?)",
        (title, abstract, status),
    )
    pid = cur.lastrowid
    for idx, (section, text) in enumerate(sections):
        conn.execute(
            "INSERT INTO chunks_meta (paper_id, chunk_idx, section, page, text)"
            " VALUES (?, ?, ?, 1, ?)",
            (pid, idx, section, text),
        )
    conn.commit()
    return pid


def _paper_status(conn, pid) -> str:
    return conn.execute(
        "SELECT status FROM papers WHERE id = ?", (pid,)
    ).fetchone()[0]


def _wait_job_done(client, job_id: int, timeout: float = 120.0) -> dict:
    """Poll the shared job endpoint until status flips to done."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        r = client.get(f"/api/import/jobs/{job_id}")
        assert r.status_code == 200
        last = r.json()
        if last["status"] == "done":
            return last
        time.sleep(0.05)
    pytest.fail(f"job {job_id} did not finish in {timeout}s: {last}")


def _note_types(client, pid) -> list[str]:
    notes = client.get(f"/api/papers/{pid}/notes").json()["notes"]
    return [n["note_type"] for n in notes]


class StudyGateway:
    """Gateway double for the study routes.

    Routes like tests/test_reader.py's fake: a prompt whose last message
    contains "JSON" is the six-dim synthesis call; every other prompt is a
    section interpretation. With ``fail_six_dim`` the synthesis call raises
    LLMExhaustedError — the error the real gateway now raises when every
    provider failed — after the section notes were already produced.
    """

    def __init__(
        self,
        section_reply: str = "## 本节解读",
        six_dim_reply: str = SIX_DIM_JSON,
        fail_six_dim: bool = False,
    ):
        self.section_reply = section_reply
        self.six_dim_reply = six_dim_reply
        self.fail_six_dim = fail_six_dim

    @staticmethod
    def _reply(text: str) -> dict:
        return {
            "text": text,
            "thinking": "",
            "provider": "fake",
            "model": "fake",
            "usage": {"input": 0, "output": 0},
        }

    async def chat(self, messages, tier="fast", max_tokens=4096, temperature=None):
        text = messages[-1]["content"]
        if "JSON" in text:
            if self.fail_six_dim:
                raise LLMExhaustedError(
                    f"all providers failed for tier {tier!r}",
                    [
                        {
                            "provider": "fake",
                            "error": "HTTP 500",
                            "text_len": None,
                        }
                    ],
                )
            return self._reply(self.six_dim_reply)
        return self._reply(self.section_reply)


def _seed_compare_stack(client, conn, embedder):
    """Two papers with abstracts + known-page chunks in the app's own store."""
    pid_a = _add_paper(conn, TITLE_A, abstract=ABSTRACT_A, status="read")
    pid_b = _add_paper(conn, TITLE_B, abstract=ABSTRACT_B, status="read")
    store = client.app.state.store

    def upsert(pid, chunks):
        vectors = embedder.embed([text for text, _, _ in chunks])
        store.upsert_chunks(
            [
                ChunkPoint(
                    paper_id=pid,
                    chunk_index=i,
                    text=text,
                    page=page,
                    section=section,
                    vector=vector,
                )
                for i, ((text, page, section), vector)
                in enumerate(zip(chunks, vectors))
            ]
        )

    upsert(pid_a, [(CHUNK_A_P2, 2, "2 Method"), (CHUNK_A_P5, 5, "4 Experiments")])
    upsert(pid_b, [(CHUNK_B_P3, 3, "3 Setup")])
    return pid_a, pid_b


# ---------------------------------------------------------------------------
# interpret route: 200 / 404 / 409
# ---------------------------------------------------------------------------


def test_interpret_creates_job(api_client, tmp_path):
    """POST interpret on an existing paper → 200 {"job_id": int}; the job is
    visible on the shared job endpoint with total=1 and finishes done=1."""
    with api_client(StudyGateway()) as client:
        conn = _seed_conn(tmp_path)
        pid = _add_paper(conn, sections=[("1 Introduction", "引言内容")])
        r = client.post(f"/api/papers/{pid}/interpret")
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]
        assert isinstance(job_id, int)

        job = _wait_job_done(client, job_id)
        assert job["id"] == job_id
        assert job["total"] == 1
        assert job["done"] == 1
        assert job["failed"] == 0
        assert job["errors"] == []


def test_interpret_paper_not_found_returns_404(api_client, tmp_path):
    _seed_conn(tmp_path)
    with api_client(StudyGateway()) as client:
        r = client.post("/api/papers/99999/interpret")
        assert r.status_code == 404


def test_interpret_conflict_when_job_running_returns_409(api_client, tmp_path):
    """A still-running interpret job for the same paper blocks a re-start."""
    with api_client(StudyGateway()) as client:
        conn = _seed_conn(tmp_path)
        pid = _add_paper(conn, sections=[("1 Introduction", "引言内容")])
        # seed after lifespan startup: the startup sweep would otherwise
        # flip a pending/running row to failed
        conn.execute(
            "INSERT INTO import_jobs (path, kind, total, status)"
            " VALUES (?, 'interpret', 1, 'running')",
            (f"interpret:{pid}",),
        )
        conn.commit()

        r = client.post(f"/api/papers/{pid}/interpret")
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# run_interpretation: success (with idempotent re-run) / failure
# ---------------------------------------------------------------------------


def test_interpret_job_success_writes_notes_and_rerun_is_idempotent(
    api_client, tmp_path
):
    """Job completes with section + six-dim notes; a re-run deletes the old
    notes first (先删后写) and does not duplicate them; a 'read' paper is
    re-read through 'reading' back to 'read'."""
    with api_client(StudyGateway()) as client:
        conn = _seed_conn(tmp_path)
        pid = _add_paper(
            conn, sections=[("1 Introduction", "引言内容"), ("2 Method", "方法内容")]
        )
        r = client.post(f"/api/papers/{pid}/interpret")
        assert r.status_code == 200, r.text
        job = _wait_job_done(client, r.json()["job_id"])
        assert job["done"] == 1 and job["failed"] == 0

        notes = client.get(f"/api/papers/{pid}/notes").json()["notes"]
        by_type: dict[str, list[dict]] = {}
        for note in notes:
            by_type.setdefault(note["note_type"], []).append(note)
        assert sorted(by_type) == ["section_analysis", "six_dim"]
        assert len(by_type["section_analysis"]) == 2
        assert all(n["content"] == "## 本节解读" for n in by_type["section_analysis"])
        assert "## 背景" in by_type["six_dim"][0]["content"]
        assert _paper_status(conn, pid) == "read"

        # re-run on the already-'read' paper: old notes deleted, result same
        r2 = client.post(f"/api/papers/{pid}/interpret")
        assert r2.status_code == 200, r2.text
        job2 = _wait_job_done(client, r2.json()["job_id"])
        assert job2["done"] == 1 and job2["failed"] == 0
        assert len(_note_types(client, pid)) == 3
        assert _paper_status(conn, pid) == "read"


def test_interpret_job_failure_marks_failed(api_client, tmp_path):
    """All-provider failure at the six-dim call → job reaches the terminal
    'failed' state with a non-empty error, and the section notes produced
    before the failure survive (契约 3). The paper stays 'reading'."""
    with api_client(StudyGateway(fail_six_dim=True)) as client:
        conn = _seed_conn(tmp_path)
        pid = _add_paper(
            conn, sections=[("1 Introduction", "引言内容"), ("2 Method", "方法内容")]
        )
        r = client.post(f"/api/papers/{pid}/interpret")
        assert r.status_code == 200, r.text
        job = _wait_job_done(client, r.json()["job_id"])
        assert job["failed"] == 1
        assert job["done"] == 0
        assert job["errors"] and job["errors"][0]

        # raw row is 'failed' (not 'running') — so a re-run is not 409-blocked
        raw_status = conn.execute(
            "SELECT status FROM import_jobs WHERE id = ?", (job["id"],)
        ).fetchone()[0]
        assert raw_status == "failed"

        # the two section analyses made before the failure are preserved,
        # the six-dim note is not
        assert _note_types(client, pid) == ["section_analysis", "section_analysis"]
        assert _paper_status(conn, pid) == "reading"


def test_interpret_rerun_without_content_preserves_old_notes(api_client, tmp_path):
    """重跑时论文已失去索引内容 → job failed，但旧解读 notes 与 'read'
    状态原样保留（不再"进入即删"旧 notes / 置 reading）。"""
    with api_client(StudyGateway()) as client:
        conn = _seed_conn(tmp_path)
        pid = _add_paper(conn, sections=[("1 Introduction", "引言内容")])
        r = client.post(f"/api/papers/{pid}/interpret")
        assert r.status_code == 200, r.text
        _wait_job_done(client, r.json()["job_id"])
        assert _paper_status(conn, pid) == "read"
        assert len(_note_types(client, pid)) == 2

        # the paper loses its indexed content (e.g. re-ingest cleared it)
        conn.execute("DELETE FROM chunks_meta WHERE paper_id = ?", (pid,))
        conn.commit()

        r2 = client.post(f"/api/papers/{pid}/interpret")
        assert r2.status_code == 200, r.text
        job = _wait_job_done(client, r2.json()["job_id"])
        # the job reflects the failure honestly (the endpoint collapses
        # completed|failed → "done"; per-item failure lives in failed/errors),
        # but the old interpretation survives untouched and the status
        # was not disturbed
        assert job["failed"] == 1 and job["done"] == 0
        assert "no indexed content" in job["errors"][0]
        assert _paper_status(conn, pid) == "read"
        assert len(_note_types(client, pid)) == 2


# ---------------------------------------------------------------------------
# compare route
# ---------------------------------------------------------------------------


def test_compare_success_and_dedup(api_client, tmp_path, embedder):
    with api_client(FakeGateway(strong=MARKDOWN_REPLY)) as client:
        conn = _seed_conn(tmp_path)
        pid_a, pid_b = _seed_compare_stack(client, conn, embedder)

        r = client.post(
            "/api/compare",
            json={"paper_ids": [pid_a, pid_b], "question": "方法有何差异？"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["matrix"] == MARKDOWN_REPLY
        assert body["citations"] == [
            {"paper_id": pid_a, "page": 2, "quote": CHUNK_A_P2},
            {"paper_id": pid_a, "page": 5, "quote": CHUNK_A_P5},
            {"paper_id": pid_b, "page": 3, "quote": CHUNK_B_P3},
        ]

        # duplicates collapse before validation/numbering; empty question
        # behaves like null
        r2 = client.post(
            "/api/compare",
            json={"paper_ids": [pid_a, pid_b, pid_a], "question": ""},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json() == body


def test_compare_count_validation_returns_400(api_client, tmp_path):
    """Empty, single, duplicate-collapsed-to-one and >5 id lists are 400s."""
    with api_client(FakeGateway()) as client:
        _seed_conn(tmp_path)
        for ids in ([], [1], [1, 1], [1, 2, 3, 4, 5, 6]):
            r = client.post("/api/compare", json={"paper_ids": ids, "question": None})
            assert r.status_code == 400, ids
            assert "paper_ids" in r.json()["detail"]


def test_compare_missing_paper_returns_400(api_client, tmp_path):
    with api_client(FakeGateway()) as client:
        _seed_conn(tmp_path)
        r = client.post(
            "/api/compare", json={"paper_ids": [99998, 99999], "question": "对比"}
        )
        assert r.status_code == 400
        assert "99998" in r.json()["detail"]


class ExhaustedGateway:
    """Gateway double that always raises the real gateway's exhaustion error
    (every provider failed) — the compare route must map it to 502, not 500
    or 400, and surface the per-provider attempts attribution."""

    async def chat(self, messages, tier="fast", max_tokens=4096, temperature=None):
        raise LLMExhaustedError(
            f"all providers failed for tier {tier!r}",
            [{"provider": "fake", "error": "HTTP 502", "text_len": None}],
        )


def test_compare_llm_exhausted_returns_502(api_client, tmp_path, embedder):
    with api_client(ExhaustedGateway()) as client:
        conn = _seed_conn(tmp_path)
        pid_a, pid_b = _seed_compare_stack(client, conn, embedder)

        r = client.post(
            "/api/compare", json={"paper_ids": [pid_a, pid_b], "question": "对比"}
        )

        assert r.status_code == 502, r.text
        detail = r.json()["detail"]
        assert "llm exhausted" in detail
        # the per-provider attribution travels to the API client
        assert "fake" in detail and "HTTP 502" in detail


# ---------------------------------------------------------------------------
# migration 0002
# ---------------------------------------------------------------------------


def test_migration_0002_rebuilds_notes_and_adds_kind(tmp_path):
    """A pre-0002 database (0001 applied, real rows in it) upgrades in place:
    existing notes survive the notes-table rebuild, 'six_dim' becomes writable,
    and import_jobs gains kind with default 'import'."""
    settings = Settings(data_dir=tmp_path, qdrant_url=":memory:")
    legacy = sqlite3.connect(settings.db_path)
    legacy.executescript((MIGRATIONS_DIR / "0001_init.sql").read_text("utf-8"))
    # replicate the bookkeeping _ensure_migrations did for 0001
    legacy.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    legacy.execute("INSERT INTO schema_migrations (name) VALUES ('0001_init.sql')")
    legacy.execute(
        "INSERT INTO papers (title, source) VALUES ('legacy paper', 'upload')"
    )
    legacy.execute(
        "INSERT INTO notes (paper_id, note_type, content)"
        " VALUES (1, 'annotation', '旧笔记')"
    )
    legacy.execute(
        "INSERT INTO import_jobs (path, total, status) VALUES ('/old', 2, 'completed')"
    )
    legacy.commit()
    legacy.close()

    conn = get_conn(settings)  # applies 0002
    try:
        # the legacy note survived the rebuild (same row, same content)
        row = conn.execute(
            "SELECT id, paper_id, note_type, content FROM notes"
        ).fetchone()
        assert (row["id"], row["paper_id"], row["note_type"], row["content"]) == (
            1, 1, "annotation", "旧笔记",
        )
        # six_dim is now writable (the CHECK knows it)
        conn.execute(
            "INSERT INTO notes (paper_id, note_type, content)"
            " VALUES (1, 'six_dim', '六维综合')"
        )
        conn.commit()
        # legacy import jobs default to kind='import'; new ones do too
        assert (
            conn.execute(
                "SELECT kind FROM import_jobs WHERE path = '/old'"
            ).fetchone()[0]
            == "import"
        )
        conn.execute(
            "INSERT INTO import_jobs (path, total) VALUES ('/new', 1)"
        )
        assert (
            conn.execute(
                "SELECT kind FROM import_jobs WHERE path = '/new'"
            ).fetchone()[0]
            == "import"
        )
        # the paper index was rebuilt with the table
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index'"
            " AND name='idx_notes_paper'"
        ).fetchone()
    finally:
        conn.close()
