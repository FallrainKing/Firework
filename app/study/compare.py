"""多篇论文对比引擎（论文精读 P2 Task 4）。

流程（sqlite 读与 embed 一律经 asyncio.to_thread，不阻塞事件循环——
P1 教训：bge-m3 CPU 推理会卡死 loop，reader.py/pipeline.py 同例）：

① 读 papers 元数据（id/title/abstract，按 paper_ids 顺序；缺失即报错）；
② 检索 query：question 非空（strip 后）用 question embed 一次、各篇共用
   该向量；为空则逐篇用"标题+摘要"批量 embed；
③ 每篇 store.search(top_k=6, paper_id=...)，片段以 [P{n}|页码] 标号
   （n 为 paper_ids 内序号，1 起）；
④ 一次 strong 调用（max_tokens=4096），要求输出 Markdown 对比表格
   （方法/核心思想/实验设置/结果/局限 × 各论文列）+ 引用标记穿插正文；
⑤ matrix 原样返回；[P{n}|页码] 标记映射回 citations（同 P1 qa 的映射
   语义：重复去重、越界丢弃、无有效标记时全部片段附上）。

生产接线（API 路由如何传入 db/embedder/store/gateway）是 Task 5 的事；
本模块只依赖这些注入的协作者。
"""

from __future__ import annotations

import asyncio
import re
import sqlite3

from ..rag.vector_store import SearchHit

#: 每篇论文检索的片段数（brief 固定 top_k=6）
TOP_K_PER_PAPER = 6
#: 一次 strong 调用的输出上限（brief 固定 4096）
MAX_TOKENS = 4096
#: 一篇片段都没有时的占位对比结果（不调 gateway）
NO_CONTENT_MATRIX = "未找到相关内容，无法对比。"

#: 答案中的引用标记，如 [P1|3] = 论文1第3页。Markdown 表格单元格内的
#: 规范转义写法是 [P1\|3]（竖线会破坏表格），竖线前的反斜杠可选匹配。
_MARKER_RE = re.compile(r"\[P(\d+)\\?\|(\d+)\]")

_SYSTEM_PROMPT = (
    "你是一位科研助手。用户会提供多篇论文的元信息与带 [P{n}|页码] 标号的"
    "检索片段，请基于这些材料对论文做横向对比。引用某篇论文的片段时，"
    "在对应位置自然插入其 [P{n}|页码] 标记（例如 [P1|3] 指论文1第3页），"
    "不要凭空编造材料之外的内容。在 Markdown 表格单元格内也请直接写"
    " [P{n}|页码]（竖线无需转义），以 [P{n}|页码] 的字面形态出现。"
)


# ---------------------------------------------------------------------------
# sqlite 同步助手（一律经 asyncio.to_thread 调用）
# ---------------------------------------------------------------------------


def _fetch_papers(
    db: sqlite3.Connection, paper_ids: list[int]
) -> list[sqlite3.Row]:
    rows: list[sqlite3.Row] = []
    for paper_id in paper_ids:
        row = db.execute(
            "SELECT id, title, abstract FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"paper {paper_id} not found")
        rows.append(row)
    return rows


def _paper_query(row: sqlite3.Row) -> str:
    """无 question 时的逐篇检索 query：标题 + 摘要。"""
    return f"{row['title']}\n{row['abstract'] or ''}"


# ---------------------------------------------------------------------------
# prompt 构造（中文）
# ---------------------------------------------------------------------------


def _build_prompt(
    question: str,
    papers: list[sqlite3.Row],
    hits_by_paper: list[list[SearchHit]],
) -> str:
    parts: list[str] = []
    if question:
        parts.append(f"对比问题：{question}")
    else:
        parts.append("请对以下论文进行全面对比。")
    parts.append("")
    for n, (row, hits) in enumerate(zip(papers, hits_by_paper), start=1):
        parts.append(f"【论文{n}】标题：{row['title']}")
        if row["abstract"]:
            parts.append(f"摘要：{row['abstract']}")
        if hits:
            parts.append("检索片段：")
            for hit in hits:
                parts.append(f"[P{n}|{hit.page}]（{hit.section}）\n{hit.text}")
        else:
            parts.append("（该论文无可用检索片段，仅基于元信息对比）")
        parts.append("")
    parts.append(
        "请用中文输出一个 Markdown 对比表格：第一列为对比维度，依次是"
        "方法、核心思想、实验设置、结果、局限；其余每篇论文各占一列。"
        "表格之后可补充对比分析正文，引用片段时使用其 [P{n}|页码] 标记。"
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# citation 映射（语义同 P1 qa：重复去重、越界丢弃、无有效标记全量附上）
# ---------------------------------------------------------------------------


def _map_citations(
    matrix: str,
    papers: list[sqlite3.Row],
    hits_by_paper: list[list[SearchHit]],
) -> list[dict]:
    """[P{n}|页码]（表格内可为转义形态 [P{n}\|页码]）→ citations。

    - 出现顺序保序（同 P1 qa）；
    - 同一 (n, 页码) 的重复标记只记一次；
    - 论文序号越界、或该篇检索片段里没有这个页码的标记直接丢弃；
    - 答案没有任何有效标记时，全部检索片段附上（论文顺序，篇内按
      chunk_index 排序保证确定性——qdrant 返回按相似度排序，不稳定）。
    """
    cited: list[tuple[int, SearchHit]] = []  # (论文序号 n, 命中片段)
    seen: set[tuple[int, int]] = set()  # (n, 页码)
    for match in _MARKER_RE.finditer(matrix):
        n = int(match.group(1))
        page = int(match.group(2))
        if not 1 <= n <= len(hits_by_paper):
            continue
        if (n, page) in seen:
            continue
        for hit in hits_by_paper[n - 1]:
            if hit.page == page:
                seen.add((n, page))
                cited.append((n, hit))
                break
    if not cited:
        for n, hits in enumerate(hits_by_paper, start=1):
            for hit in sorted(hits, key=lambda h: h.chunk_index):
                cited.append((n, hit))
    return [
        {"paper_id": hit.paper_id, "page": hit.page, "quote": hit.text}
        for _n, hit in cited
    ]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


async def compare_papers(
    paper_ids: list[int],
    question: str | None,
    *,
    db: sqlite3.Connection,
    embedder,
    store,
    gateway,
) -> dict:
    """横向对比多篇论文，返回 {"matrix": markdown, "citations": [...]}。

    matrix 是 gateway 返回的 Markdown 对比表格原文；citations 把答案中的
    [P{n}|页码] 标记映射回检索片段（paper_id/page/quote）。
    """
    if not paper_ids:
        return {"matrix": "", "citations": []}

    # ① 元数据（to_thread：跨线程使用连接依赖 check_same_thread=False）
    papers = await asyncio.to_thread(_fetch_papers, db, paper_ids)

    # ② 检索 query：question 优先；为空则逐篇"标题+摘要"
    query = (question or "").strip()
    if query:
        vectors = await asyncio.to_thread(embedder.embed, [query])
        query_vectors = [vectors[0]] * len(papers)
    else:
        query_vectors = await asyncio.to_thread(
            embedder.embed, [_paper_query(row) for row in papers]
        )

    # ③ 每篇各自 top_k 检索（qdrant 同步客户端，同样不占事件循环）
    hits_by_paper: list[list[SearchHit]] = []
    for vector, row in zip(query_vectors, papers):
        hits = await asyncio.to_thread(
            store.search, vector, TOP_K_PER_PAPER, row["id"]
        )
        hits_by_paper.append(list(hits))

    if not any(hits_by_paper):
        return {"matrix": NO_CONTENT_MATRIX, "citations": []}

    # ④ 一次 strong 调用生成对比表格
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_prompt(query, papers, hits_by_paper)},
    ]
    reply = await gateway.chat(messages, tier="strong", max_tokens=MAX_TOKENS)
    matrix = str(reply["text"])

    # ⑤ 标记映射回 citations
    return {
        "matrix": matrix,
        "citations": _map_citations(matrix, papers, hits_by_paper),
    }
