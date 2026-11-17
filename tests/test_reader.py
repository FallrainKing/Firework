"""Task 3: 深度解读引擎 — 章节级解读 + 六维综合.

Ruling R1 (note_type 约定): 生产 schema 的 notes CHECK（0001_init.sql）尚不认识
``six_dim``——它随 Task 5 的 0002 迁移扩展。因此测试不直接用 get_conn() 的默认
连接，而是各自建一个独立连接（check_same_thread=False，因为 interpret_paper
按约定把全部 sqlite 操作包进 asyncio.to_thread，会在工作线程里使用该连接），
并在其上重建一个与 0001 同构、但 CHECK 多了 ``six_dim`` 的 notes 表变体。

生产路径的 reader.py 不感知 CHECK：note_type 的取值就是
'section_analysis'/'six_dim'，等 0002 落地后即可直接写。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from app.config import Settings
from app.db import get_conn
from app.study.reader import InterpretationError, interpret_paper

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
BAD_JSON = "抱歉，我无法以 JSON 形式回答。"

#: 节解读 prompt 里节文本的分隔标记（test_long_section_truncated 靠它切出正文）
SECTION_TEXT_MARK = "【节文本】\n"
TRUNCATION_MARK = "\n…[截断]"
MAX_SECTION_CHARS = 6000


def make_db(tmp_path) -> sqlite3.Connection:
    """独立连接：迁移 schema + 含 six_dim 的 notes 表变体。"""
    settings = Settings(data_dir=tmp_path, qdrant_url=":memory:")
    get_conn(settings).close()  # applies 0001_init.sql
    db = sqlite3.connect(settings.db_path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    # 同构 0001 的 notes 表，CHECK 增加 six_dim（生产等 Task 5 的 0002 迁移）
    db.execute("DROP TABLE notes")
    db.execute(
        """
        CREATE TABLE notes (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
            note_type TEXT CHECK(note_type IN
                ('section_analysis', 'annotation', 'chat_summary', 'six_dim'))
                NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_notes_paper ON notes(paper_id)")
    db.commit()
    return db


def add_paper(db, title="测试论文", status="new", sections=()) -> int:
    """插入一篇论文及若干 (section, text) chunks；返回 paper id。"""
    cur = db.execute(
        "INSERT INTO papers (title, status) VALUES (?, ?)", (title, status)
    )
    pid = cur.lastrowid
    for idx, (section, text) in enumerate(sections):
        db.execute(
            "INSERT INTO chunks_meta (paper_id, chunk_idx, section, page, text)"
            " VALUES (?, ?, ?, ?, ?)",
            (pid, idx, section, 1, text),
        )
    db.commit()
    return pid


def paper_status(db, pid) -> str:
    return db.execute(
        "SELECT status FROM papers WHERE id = ?", (pid,)
    ).fetchone()[0]


def _reply(text: str) -> dict:
    return {
        "text": text,
        "thinking": "",
        "provider": "fake",
        "model": "fake",
        "usage": {"input": 0, "output": 0},
    }


class FakeGateway:
    """可编程 gateway double：按最后一条 user 消息的内容路由。

    - 消息含 "JSON" → 六维综合调用：依次消费 six_dim_replies 队列，
      队列空后回落 six_dim_default。
    - 其余 → 节解读调用：返回 section_reply；若消息命中
      fail_section_markers 中的片段则抛错（模拟网关失败）。
    """

    def __init__(
        self,
        section_reply="## 本节解读",
        six_dim_replies=(),
        six_dim_default=None,
    ):
        self.section_reply = section_reply
        self.six_dim_queue = list(six_dim_replies)
        self.six_dim_default = (
            six_dim_default if six_dim_default is not None else SIX_DIM_JSON
        )
        self.fail_section_markers: tuple[str, ...] = ()
        self.section_prompts: list[str] = []
        self.six_dim_calls: list[list[dict]] = []
        self.calls: list[dict] = []

    async def chat(self, messages, tier="fast", max_tokens=4096, temperature=None):
        self.calls.append(
            {
                "messages": [dict(m) for m in messages],
                "tier": tier,
                "max_tokens": max_tokens,
            }
        )
        text = messages[-1]["content"]
        if "JSON" in text:
            self.six_dim_calls.append([dict(m) for m in messages])
            reply = (
                self.six_dim_queue.pop(0)
                if self.six_dim_queue
                else self.six_dim_default
            )
            return _reply(reply)
        self.section_prompts.append(text)
        if any(marker in text for marker in self.fail_section_markers):
            raise RuntimeError("fake gateway exploded")
        return _reply(self.section_reply)


def test_interpret_writes_section_and_six_dim_notes(tmp_path):
    db = make_db(tmp_path)
    pid = add_paper(
        db,
        sections=[
            ("Front Matter", "摘要文本，不应产生解读"),
            ("1 Introduction", "引言内容"),
            ("2 Method", "方法内容"),
        ],
    )
    gw = FakeGateway()

    result = asyncio.run(interpret_paper(pid, db=db, gateway=gw))

    # 2 节解读 + 1 六维 = 3 条 notes；Front Matter 被跳过
    notes = db.execute(
        "SELECT note_type, content FROM notes WHERE paper_id = ?", (pid,)
    ).fetchall()
    assert sorted(n["note_type"] for n in notes) == [
        "section_analysis",
        "section_analysis",
        "six_dim",
    ]
    assert [s["section"] for s in result["sections"]] == [
        "1 Introduction",
        "2 Method",
    ]
    assert result["sections"][0]["note"] == "## 本节解读"
    # 六维返回结构 + note 是 markdown 标题结构
    assert tuple(result["six_dim"]) == SIX_KEYS
    six_note = next(n["content"] for n in notes if n["note_type"] == "six_dim")
    assert "## 背景" in six_note
    assert "## 局限" in six_note
    # gateway 调用形态：每节一次 strong/2048，六维一次 strong/4096
    assert [c["max_tokens"] for c in gw.calls] == [2048, 2048, 4096]
    assert all(c["tier"] == "strong" for c in gw.calls)


def test_interpret_retries_on_bad_json(tmp_path):
    db = make_db(tmp_path)
    pid = add_paper(db, sections=[("1 Introduction", "引言内容")])
    gw = FakeGateway(six_dim_replies=[BAD_JSON])

    result = asyncio.run(interpret_paper(pid, db=db, gateway=gw))

    # 第一次坏 → 追加"只输出 JSON"重试一次 → 成功
    assert len(gw.six_dim_calls) == 2
    assert "只输出 JSON" in gw.six_dim_calls[1][-1]["content"]
    assert tuple(result["six_dim"]) == SIX_KEYS
    assert (
        db.execute(
            "SELECT COUNT(*) FROM notes WHERE paper_id = ? AND note_type = 'six_dim'",
            (pid,),
        ).fetchone()[0]
        == 1
    )


def test_interpret_raises_after_second_bad_json(tmp_path):
    db = make_db(tmp_path)
    pid = add_paper(db, sections=[("1 Introduction", "引言内容")])
    gw = FakeGateway(six_dim_default=BAD_JSON)

    with pytest.raises(InterpretationError):
        asyncio.run(interpret_paper(pid, db=db, gateway=gw))

    # 两次都坏：状态停在 'reading'；六维失败，但已成功节逐节落库
    # （P2 Task 5 契约 3）——节成果保留，无 six_dim note
    assert paper_status(db, pid) == "reading"
    assert len(gw.six_dim_calls) == 2
    types = [
        r["note_type"]
        for r in db.execute(
            "SELECT note_type FROM notes WHERE paper_id = ?", (pid,)
        )
    ]
    assert types == ["section_analysis"]

    # 无 chunks 的论文直接报 InterpretationError，不产生任何调用
    empty_pid = add_paper(db)
    with pytest.raises(InterpretationError, match="no indexed content"):
        asyncio.run(interpret_paper(empty_pid, db=db, gateway=FakeGateway()))


def test_long_section_truncated(tmp_path):
    db = make_db(tmp_path)
    long_section = "字" * 8000
    pid = add_paper(db, sections=[("2 Method", long_section)])
    gw = FakeGateway()

    asyncio.run(interpret_paper(pid, db=db, gateway=gw))

    prompt = gw.section_prompts[0]
    # 整个 prompt 比原始节文本（8000 字符）短
    assert len(prompt) < 8000
    body = prompt.split(SECTION_TEXT_MARK, 1)[1]
    # 发出的节文本被截到 ≤ 6000 + 截断标记长度，且带截断标记；
    # 下界防"截过头"（错截到 100 字符仍过）
    assert MAX_SECTION_CHARS <= len(body) <= MAX_SECTION_CHARS + len(
        TRUNCATION_MARK
    )
    assert body.endswith(TRUNCATION_MARK)


def test_all_sections_failed_raises(tmp_path):
    db = make_db(tmp_path)
    pid = add_paper(
        db, status="new", sections=[("1 Introduction", "引言"), ("2 Method", "方法")]
    )
    gw = FakeGateway()
    gw.fail_section_markers = ("Introduction", "Method")

    with pytest.raises(InterpretationError, match="all section"):
        asyncio.run(interpret_paper(pid, db=db, gateway=gw))

    # 全部节失败：提前抛错，状态停在 'reading'，不进入六维、不写 notes
    assert paper_status(db, pid) == "reading"
    assert gw.six_dim_calls == []
    assert (
        db.execute(
            "SELECT COUNT(*) FROM notes WHERE paper_id = ?", (pid,)
        ).fetchone()[0]
        == 0
    )


def test_status_transitions_reading_then_read(tmp_path):
    db = make_db(tmp_path)
    # 全程成功：new → reading → read
    pid_ok = add_paper(db, status="new", sections=[("1 Introduction", "x")])
    asyncio.run(interpret_paper(pid_ok, db=db, gateway=FakeGateway()))
    assert paper_status(db, pid_ok) == "read"

    # 中途异常（六维两次解析失败）：pushed → reading，且停在 'reading'
    pid_bad = add_paper(db, status="pushed", sections=[("1 Introduction", "x")])
    with pytest.raises(InterpretationError):
        asyncio.run(
            interpret_paper(pid_bad, db=db, gateway=FakeGateway(six_dim_default=BAD_JSON))
        )
    assert paper_status(db, pid_bad) == "reading"


def test_failed_section_noted_and_continues(tmp_path):
    db = make_db(tmp_path)
    pid = add_paper(
        db,
        sections=[
            ("1 Introduction", "引言"),
            ("2 Method", "会失败的方法节"),
            ("3 Experiments", "实验"),
        ],
    )
    gw = FakeGateway()
    gw.fail_section_markers = ("2 Method",)

    result = asyncio.run(interpret_paper(pid, db=db, gateway=gw))

    # 失败节记录占位解读，其余节正常，整体仍成功
    method = next(s for s in result["sections"] if s["section"] == "2 Method")
    assert "解读失败" in method["note"]
    assert "fake gateway exploded" in method["note"]
    # 综合 prompt 中失败节是元信息而非材料：不含原始错误文本
    six_prompt = gw.six_dim_calls[0][-1]["content"]
    assert "（本节解读失败，请基于其余章节综合）" in six_prompt
    assert "fake gateway exploded" not in six_prompt
    assert [s["note"] for s in result["sections"] if s["section"] != "2 Method"] == [
        "## 本节解读"
    ] * 2
    assert paper_status(db, pid) == "read"
    assert (
        db.execute(
            "SELECT COUNT(*) FROM notes WHERE paper_id = ?", (pid,)
        ).fetchone()[0]
        == 4
    )
