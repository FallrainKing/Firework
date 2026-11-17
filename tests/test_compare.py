"""Task 4: 多篇论文对比引擎 — compare_papers.

沿 conftest ingest_stack 模式：真 bge-m3 embedder（session fixture）+
:memory: Qdrant + 独立 sqlite db。compare_papers 约定把 sqlite 读和
embed 都包进 asyncio.to_thread（工作线程用连接），因此测试自建
check_same_thread=False 的连接（与 tests/test_reader.py 做法一致）；
生产接线（app 启动时如何建连接）是 Task 5 的事。

片段标号 [P{n}|页码]：n 为 paper_ids 内序号（1 起）。citation 映射语义
同 P1 qa：重复去重、越界丢弃、无有效标记时全部片段附上。
"""

from __future__ import annotations

import asyncio
import sqlite3

from qdrant_client import QdrantClient

from app.config import Settings
from app.db import get_conn
from app.rag.vector_store import ChunkPoint, VectorStore
from app.study.compare import compare_papers

TITLE_A = "对比论文甲：强化学习方法"
ABSTRACT_A = "论文甲的摘要：提出一种基于强化学习的训练技巧。"
TITLE_B = "对比论文乙：监督对比方法"
ABSTRACT_B = "论文乙的摘要：提出一种监督对比学习框架。"

#: 各篇已知页码的 chunk 文本（页码即引用映射的断言依据）
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


def setup_stack(tmp_path, embedder):
    """独立 sqlite 连接（check_same_thread=False，to_thread 约定）+ :memory: qdrant。"""
    settings = Settings(data_dir=tmp_path, qdrant_url=":memory:")
    get_conn(settings).close()  # applies 0001_init.sql
    db = sqlite3.connect(settings.db_path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    store = VectorStore(QdrantClient(":memory:"), collection="chunks")
    store.ensure_collection(embedder.dimension)
    return db, store


def add_paper(db, title, abstract) -> int:
    cur = db.execute(
        "INSERT INTO papers (title, abstract, status) VALUES (?, ?, 'read')",
        (title, abstract),
    )
    db.commit()
    return cur.lastrowid


def upsert_chunks(store, embedder, paper_id, chunks):
    """chunks: [(text, page, section)]，chunk_index 按列表顺序 0 起。"""
    vectors = embedder.embed([text for text, _, _ in chunks])
    store.upsert_chunks(
        [
            ChunkPoint(
                paper_id=paper_id,
                chunk_index=i,
                text=text,
                page=page,
                section=section,
                vector=vector,
            )
            for i, ((text, page, section), vector) in enumerate(zip(chunks, vectors))
        ]
    )


def seed_two_papers(db, store, embedder):
    """论文甲（页 2、5 两个片段）+ 论文乙（页 3 一个片段）。"""
    pid_a = add_paper(db, TITLE_A, ABSTRACT_A)
    pid_b = add_paper(db, TITLE_B, ABSTRACT_B)
    upsert_chunks(
        store,
        embedder,
        pid_a,
        [
            (CHUNK_A_P2, 2, "2 Method"),
            (CHUNK_A_P5, 5, "4 Experiments"),
        ],
    )
    upsert_chunks(
        store,
        embedder,
        pid_b,
        [(CHUNK_B_P3, 3, "3 Setup")],
    )
    return pid_a, pid_b


class RecordingEmbedder:
    """包装真 embedder：记录每次 embed 的文本批次，向量照常委托。"""

    def __init__(self, inner):
        self.inner = inner
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return self.inner.embed(texts)


class FakeGateway:
    """固定回复的 gateway double，记录调用形态。"""

    def __init__(self, reply: str = MARKDOWN_REPLY):
        self.reply = reply
        self.calls: list[dict] = []

    async def chat(self, messages, tier="fast", max_tokens=4096, temperature=None):
        self.calls.append(
            {
                "messages": [dict(m) for m in messages],
                "tier": tier,
                "max_tokens": max_tokens,
            }
        )
        return {
            "text": self.reply,
            "thinking": "",
            "provider": "fake",
            "model": "fake",
            "usage": {"input": 0, "output": 0},
        }


def test_compare_with_question_uses_question_embedding(tmp_path, embedder):
    db, store = setup_stack(tmp_path, embedder)
    pid_a, pid_b = seed_two_papers(db, store, embedder)
    rec = RecordingEmbedder(embedder)
    gw = FakeGateway()
    question = "两篇论文的方法有何差异？"

    result = asyncio.run(
        compare_papers(
            [pid_a, pid_b], question, db=db, embedder=rec, store=store, gateway=gw
        )
    )

    # question 非空：只 embed 一次，且调用文本就是 question（不含标题/摘要）
    assert rec.calls == [[question]]
    # gateway 形态：一次 strong / 4096
    assert len(gw.calls) == 1
    assert gw.calls[0]["tier"] == "strong"
    assert gw.calls[0]["max_tokens"] == 4096
    assert result["matrix"] == MARKDOWN_REPLY


def test_compare_without_question_uses_title_abstract(tmp_path, embedder):
    db, store = setup_stack(tmp_path, embedder)
    pid_a, pid_b = seed_two_papers(db, store, embedder)
    rec = RecordingEmbedder(embedder)
    gw = FakeGateway()

    asyncio.run(
        compare_papers(
            [pid_a, pid_b], None, db=db, embedder=rec, store=store, gateway=gw
        )
    )

    # question 为空：一次批量 embed，逐篇 "标题+摘要"
    assert len(rec.calls) == 1
    query_a, query_b = rec.calls[0]
    assert TITLE_A in query_a and ABSTRACT_A in query_a
    assert TITLE_B in query_b and ABSTRACT_B in query_b


def test_compare_citations_mapped(tmp_path, embedder):
    db, store = setup_stack(tmp_path, embedder)
    pid_a, pid_b = seed_two_papers(db, store, embedder)
    reply = (
        "对比正文 [P1|2]，重复标记 [P1|2]，越界页码 [P1|99]，"
        "越界论文 [P9|1]，另一篇 [P2|3]。"
    )
    gw = FakeGateway(reply)

    result = asyncio.run(
        compare_papers(
            [pid_a, pid_b], "对比两篇", db=db, embedder=embedder, store=store, gateway=gw
        )
    )

    # 出现顺序保序；重复去重；越界（页码/论文序号）丢弃
    assert result["citations"] == [
        {"paper_id": pid_a, "page": 2, "quote": CHUNK_A_P2},
        {"paper_id": pid_b, "page": 3, "quote": CHUNK_B_P3},
    ]

    # 无任何有效标记 → 全部检索片段附上（论文顺序，chunk_index 排序）
    gw2 = FakeGateway("这是一段没有任何引用标记的对比正文。")
    result2 = asyncio.run(
        compare_papers(
            [pid_a, pid_b], "对比两篇", db=db, embedder=embedder, store=store, gateway=gw2
        )
    )
    assert result2["citations"] == [
        {"paper_id": pid_a, "page": 2, "quote": CHUNK_A_P2},
        {"paper_id": pid_a, "page": 5, "quote": CHUNK_A_P5},
        {"paper_id": pid_b, "page": 3, "quote": CHUNK_B_P3},
    ]


def test_compare_matrix_is_markdown_with_all_papers(tmp_path, embedder):
    db, store = setup_stack(tmp_path, embedder)
    pid_a, pid_b = seed_two_papers(db, store, embedder)
    gw = FakeGateway(MARKDOWN_REPLY)

    result = asyncio.run(
        compare_papers(
            [pid_a, pid_b], None, db=db, embedder=embedder, store=store, gateway=gw
        )
    )

    # matrix 原样返回
    assert result["matrix"] == MARKDOWN_REPLY
    # prompt：含各篇元信息与 [P{n}|页码] 标号的片段
    prompt = gw.calls[0]["messages"][-1]["content"]
    assert TITLE_A in prompt and TITLE_B in prompt
    assert "[P1|2]" in prompt
    assert "[P1|5]" in prompt
    assert "[P2|3]" in prompt
    # 对比表格要求：维度 × 各论文列
    assert "方法" in prompt
    assert "核心思想" in prompt
    assert "实验设置" in prompt
    assert "局限" in prompt
