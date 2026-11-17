"""深度解读引擎：逐节中文解读 + 六维综合（论文精读 P2 核心）。

流程（全部 sqlite 操作经 asyncio.to_thread，节解读顺序执行不并发）：

① 读论文行 + chunks_meta 按 section 聚合文本（chunk_idx 排序拼接，
   每节超 6000 字符保头部截断；Front Matter 跳过；无内容报错）；
② 删除该 paper 旧的 section_analysis/six_dim notes（先删后写，重跑幂等
   ——契约 2）；
③ 每节一次 strong 调用生成中文解读，失败记录占位继续；成功节立即落
   section_analysis note（逐节落——契约 3：六维失败时已解读的节成果
   保留，job 仍 failed 但 notes 有节级产出）；
④ 六维综合一次 strong 调用，要求严格 JSON；解析失败追加"只输出 JSON"
   重试一次，再失败抛 InterpretationError；
⑤ 全部成功时写失败节占位 note + 六维 six_dim note（content 为 markdown）；
⑥ papers.status：进入时无条件置 'reading'（不限 new/pushed——重解读也
   应显示进度，立即 commit），全部成功后 → 'read'；任何异常路径不推到
   'read'。

Ruling R1：notes 列名 note_type；six_dim 的 CHECK 值由 Task 5 的 0002
迁移补进 schema（已落地）。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any

from app.rag.pdf_parser import FRONT_MATTER_TITLE

MAX_SECTION_CHARS = 6000
TRUNCATION_MARK = "\n…[截断]"
#: 失败节占位解读的前缀；六维综合 prompt 据此把它标为元信息而非材料
SECTION_FAIL_PREFIX = "（本节解读失败："

SIX_KEYS = (
    "background",
    "innovation",
    "architecture",
    "formulas",
    "experiments",
    "limitations",
)

#: 六维 note 的 markdown 标题结构（"## 背景"等）
_SIX_HEADINGS = (
    ("background", "## 背景"),
    ("innovation", "## 创新点"),
    ("architecture", "## 方法架构"),
    ("formulas", "## 关键公式"),
    ("experiments", "## 实验分析"),
    ("limitations", "## 局限性"),
)


class InterpretationError(Exception):
    """解读流程无法完成（无内容 / 六维 JSON 两次解析失败等）。"""


# ---------------------------------------------------------------------------
# sqlite 同步助手（一律经 asyncio.to_thread 调用）
# ---------------------------------------------------------------------------


def _fetch_paper(
    db: sqlite3.Connection, paper_id: int
) -> sqlite3.Row | None:
    return db.execute(
        "SELECT id, title, status FROM papers WHERE id = ?", (paper_id,)
    ).fetchone()


def _fetch_chunks(db: sqlite3.Connection, paper_id: int) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT section, chunk_idx, text FROM chunks_meta"
        " WHERE paper_id = ? ORDER BY chunk_idx",
        (paper_id,),
    ).fetchall()


def _set_status(db: sqlite3.Connection, paper_id: int, status: str) -> None:
    db.execute(
        "UPDATE papers SET status = ? WHERE id = ?", (status, paper_id)
    )
    db.commit()


def _delete_old_notes(db: sqlite3.Connection, paper_id: int) -> None:
    """契约 2：重跑幂等——开始时删除旧的节解读与六维 notes（先删后写）。"""
    db.execute(
        "DELETE FROM notes WHERE paper_id = ?"
        " AND note_type IN ('section_analysis', 'six_dim')",
        (paper_id,),
    )
    db.commit()


def _insert_note(
    db: sqlite3.Connection, paper_id: int, note_type: str, content: str
) -> None:
    db.execute(
        "INSERT INTO notes (paper_id, note_type, content) VALUES (?, ?, ?)",
        (paper_id, note_type, content),
    )
    db.commit()


# ---------------------------------------------------------------------------
# 聚合与 JSON
# ---------------------------------------------------------------------------


def _aggregate_sections(rows: list[sqlite3.Row]) -> list[tuple[str, str]]:
    """按 section 分组、chunk_idx 升序拼接文本；Front Matter 跳过。

    每节超过 MAX_SECTION_CHARS 保头部截断并追加标记，避免单节 prompt
    超长；返回 (节名, 节文本) 列表，保持文档出现顺序。
    """
    grouped: dict[str, list[tuple[int, str]]] = {}
    for row in rows:
        section = row["section"] or "未命名节"
        if section == FRONT_MATTER_TITLE:
            continue
        grouped.setdefault(section, []).append((row["chunk_idx"], row["text"]))
    sections: list[tuple[str, str]] = []
    for section, chunks in grouped.items():
        chunks.sort(key=lambda item: item[0])
        text = "\n".join(chunk for _, chunk in chunks)
        if len(text) > MAX_SECTION_CHARS:
            text = text[:MAX_SECTION_CHARS] + TRUNCATION_MARK
        sections.append((section, text))
    return sections


def _extract_json(text: str) -> dict:
    """剥 ```json 围栏后 json.loads；再失败退回首个 { 到末个 } 的切片。"""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    try:
        return json.loads(s)
    except ValueError:
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            return json.loads(s[start : end + 1])
        raise


def _validate_six_dim(data: Any) -> dict[str, str]:
    """必须是含六个 str 字段的对象，否则按"解析失败"走重试路径。"""
    if not isinstance(data, dict):
        raise ValueError(f"six-dim JSON is {type(data).__name__}, not an object")
    missing = [k for k in SIX_KEYS if not isinstance(data.get(k), str)]
    if missing:
        raise ValueError(f"six-dim JSON missing keys: {missing}")
    return {k: data[k] for k in SIX_KEYS}


# ---------------------------------------------------------------------------
# prompt 构造（中文；节 prompt 不含 "JSON"，六维 prompt 必含——便于网关侧区分）
# ---------------------------------------------------------------------------


def _section_prompt(section: str, text: str) -> str:
    return (
        "你正在精读一篇论文的一个章节。"
        "请用中文解读本节，覆盖该节的研究背景/方法细节/公式含义/实验设计"
        "（以实际内容为准），以 Markdown 格式输出解读。\n\n"
        f"【节名】{section}\n\n"
        f"【节文本】\n{text}"
    )


def _six_dim_prompt(title: str, sections: list[dict]) -> str:
    parts = [
        f"论文标题：{title}",
        "",
        "以下是这篇论文各章节的中文解读：",
        "",
    ]
    for item in sections:
        parts.append(f"【{item['section']}】")
        if item["note"].startswith(SECTION_FAIL_PREFIX):
            # 失败节的占位是元信息而非材料，不喂给模型
            parts.append("（本节解读失败，请基于其余章节综合）")
        else:
            parts.append(item["note"])
        parts.append("")
    parts.append(
        "请基于以上章节解读，对这篇论文做六维综合分析。严格输出一个 JSON"
        "对象（不要围栏、不要任何多余文字），包含且仅包含以下六个键："
        "background、innovation、architecture、formulas、experiments、"
        "limitations。每个维度的值用中文写 2-4 句话。"
    )
    return "\n".join(parts)


def _six_dim_markdown(six: dict[str, str]) -> str:
    """六维 note 的 markdown 正文（## 标题结构）。"""
    return "\n\n".join(
        f"{heading}\n\n{six[key]}" for key, heading in _SIX_HEADINGS
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


async def interpret_paper(
    paper_id: int,
    *,
    db: sqlite3.Connection,
    gateway,
    embedder_unused=None,
) -> dict:
    """深度解读一篇论文：逐节解读 + 六维综合，写 notes 并流转状态。

    返回 {"six_dim": {六键: str}, "sections": [{"section", "note"}]}。
    """
    paper = await asyncio.to_thread(_fetch_paper, db, paper_id)
    if paper is None:
        raise InterpretationError(f"paper {paper_id} not found")

    # ⑥ 进入时无条件置 reading（立即 commit，失败也可见；重解读也显示进度）
    await asyncio.to_thread(_set_status, db, paper_id, "reading")

    # ② 删除旧解读 notes：先删后写，重跑幂等（契约 2）
    await asyncio.to_thread(_delete_old_notes, db, paper_id)

    # ① 聚合章节文本
    chunk_rows = await asyncio.to_thread(_fetch_chunks, db, paper_id)
    sections = _aggregate_sections(chunk_rows)
    if not sections:
        raise InterpretationError("paper has no indexed content")

    # ③ 逐节解读：顺序执行（不并发，避免压测网关），失败记录占位继续；
    #    成功节立即落 note（契约 3：六维失败时已成功节成果保留）
    section_notes: list[dict] = []
    failed_section_notes: list[dict] = []
    for section, text in sections:
        try:
            reply = await gateway.chat(
                [{"role": "user", "content": _section_prompt(section, text)}],
                tier="strong",
                max_tokens=2048,
            )
            note = reply["text"]
        except Exception as exc:  # noqa: BLE001 — 单节失败不拖垮整篇
            note = f"{SECTION_FAIL_PREFIX}{exc}）"
            failed_section_notes.append({"section": section, "note": note})
        else:
            await asyncio.to_thread(
                _insert_note, db, paper_id, "section_analysis", note
            )
        section_notes.append({"section": section, "note": note})

    # 全部节失败：没有材料可综合，提前失败（状态停在 'reading'；
    # 没有成功节，故无 note 落库）
    if all(item["note"].startswith(SECTION_FAIL_PREFIX) for item in section_notes):
        raise InterpretationError("all section interpretations failed")

    # ③ 六维综合：解析失败追加"只输出 JSON"重试一次，再失败抛错
    messages = [
        {"role": "user", "content": _six_dim_prompt(paper["title"], section_notes)}
    ]
    six: dict[str, str] | None = None
    last_error: Exception | None = None
    for _attempt in range(2):
        reply = await gateway.chat(messages, tier="strong", max_tokens=4096)
        try:
            six = _validate_six_dim(_extract_json(reply["text"]))
            break
        except ValueError as exc:
            last_error = exc
            messages = messages + [
                {"role": "assistant", "content": reply["text"]},
                {"role": "user", "content": "只输出 JSON，不要任何其他文字。"},
            ]
    if six is None:
        raise InterpretationError(
            f"six-dim synthesis failed after retry: {last_error}"
        )

    # ⑤ 全部成功：补写失败节占位 note + 六维 note
    for item in failed_section_notes:
        await asyncio.to_thread(
            _insert_note, db, paper_id, "section_analysis", item["note"]
        )
    await asyncio.to_thread(
        _insert_note, db, paper_id, "six_dim", _six_dim_markdown(six)
    )

    # ⑥ 全部成功 → read
    await asyncio.to_thread(_set_status, db, paper_id, "read")

    return {"six_dim": six, "sections": section_notes}
