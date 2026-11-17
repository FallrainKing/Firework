# P2 论文精读 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为论文库增加深度阅读能力：无编号标题解析修复、章节级六维解读（背景/创新/架构/公式/实验/局限）、多篇对比矩阵、笔记 CRUD，全部经 Web 界面可用。

**Architecture:** 新增 `app/study/`（reader.py 解读引擎 + compare.py 对比引擎），复用 P1 的 gateway/store/notes 表与 batch job 基建；深度解读跑后台任务（复用 import_jobs 加 kind 列）；对比走同步路由（单次 LLM 调用）；前端加论文详情视图与对比页（含极简安全 markdown 渲染器）。

**Tech Stack:** 沿用 P1（FastAPI/SQLite/Qdrant/bge-m3/原生 JS）。LLM 用 strong 档（内部网关 glm-5.3）。

**Spec:** `/home/f/research-assistant/docs/superpowers/specs/2026-11-16-personal-ai-research-assistant-design.md`（第七节 P2）

## Global Constraints

- 沿用 P1 环境事实：测试 `.venv/bin/python -m pytest`；docker 命令 `sg docker -c "..."` 包裹；PyPI 用清华源；`.env` 不入 git 不读内容。
- LLM 输出可能含 thinking 块与 markdown；所有新 prompt 要求严格 JSON 时必须做"解析失败重试一次（附加'只输出 JSON'提醒），再失败抛明确异常"。
- 后台任务模式沿 P1：独立 db 连接、finally close、进度实时写库、异常记入 errors 继续或置 failed（绝不让 job 永久卡 running）。
- 事务语义沿 P1：向量操作与 SQLite 写的先后次序不变；本计划基本无向量写（重入库除外）。
- commit 用 `git -c user.name="f" -c user.email="f@localhost" commit`，`feat|fix|test: ...`。
- 现有 71 测试不得回归；每任务全仓 pytest 后再 commit。

## Review Focus

1. **六维 JSON 解析失败**：LLM 返回带 markdown 代码围栏或多余文字时必须重试一次再明报，不能静默存坏笔记。→ Task 3 `test_interpret_retries_on_bad_json`。
2. **超长章节**：单节文本 >6000 字符必须截断后进 prompt（防 token 爆炸），解读仍产出。→ Task 3 `test_long_section_truncated`。
3. **后台解读任务失败**：gateway 全部 provider 失败 → job 置 failed + errors 可见，绝不卡 running。→ Task 5 `test_interpret_job_failure_marks_failed`。
4. **对比参数校验**：paper_ids 含不存在 id 或数量 <2 / >5 → 400。→ Task 5 `test_compare_validates_paper_ids`。
5. **markdown 注入**：LLM/笔记内容含 `<script>` 时前端渲染必须转义（textContent 优先、md 解析器不产生裸 HTML）。→ Task 6 实现约束 + smoke 人工验证（无 pytest 前端能力，在 smoke_test.py 加"笔记含 <script> 后 GET 返回原文不解析"的 API 层断言）。

---

### Task 1: 无编号标题解析修复（遗留专项）

**Files:**
- Modify: `app/rag/pdf_parser.py`（split_sections 增加无编号标题识别）
- Modify: `scripts/reingest_all.py`（无改动预期，验证可跑）
- Test: `tests/test_pdf_parser.py`（新增用例）

**Interfaces:**
- Consumes: 现有 `split_sections(pages) -> list[Section]`、`_in_list_block`、`_HeadingNumbering`（P1 修复波引入）。
- Produces: `split_sections` 识别两类无编号标题并返回相应 Section：(a) 全大写行（≥2 词且全大写，如 "RELATED WORK"）；(b) 已知节名词表整行精确匹配（大小写不敏感全词）：abstract, introduction, background, related work, preliminary/preliminaries, method/methods, approach, model, experiment(s)/experimental setup, results, analysis, discussion, conclusion/conclusions, limitations, acknowledgments/acknowledgements, references, appendix。负例不变：句中含这些词的正文行绝不命中（要求整行仅由该短语构成）。

- [ ] **Step 1: Write the failing tests**（加入 tests/test_pdf_parser.py）

```python
def test_unnumbered_heading_recognized():    # fixture 新增正文行 "Related Work"（独立成行）→ 产出 Section("Related Work", ...)
def test_allcaps_heading_recognized():       # "3 RELATED WORK" 若存在也命中且 title 含 "RELATED WORK"；纯 "RELATED WORK" 行命中
def test_body_sentence_with_keyword_not_heading():  # "The introduction of new methods improved results." 不产出节
def test_known_heading_case_insensitive():   # "Experiments" 命中
```

- [ ] **Step 2: Run** `pytest tests/test_pdf_parser.py -v` — Expected: 新增 4 FAIL，存量 11 PASS 不动
- [ ] **Step 3: 实现**（节名词表常量 `_UNNUMBERED_HEADINGS`；整行 strip 后等于表内短语（大小写不敏感）或全大写行且词数≥2 且无行尾标点；不进入编号状态机、不推进编号）
- [ ] **Step 4: Run** 全仓 `pytest -v` — Expected: PASS（71+4=75）
- [ ] **Step 5: 重入库**（容器内 `sg docker -c "docker compose exec app python scripts/reingest_all.py"`）后 DB 验证：paper #3 (Flow Matching)、#4 (OpenVLA) 出现 ≥3 个真实节名（如 Introduction/Method/Experiments），不再整篇 Front Matter。把 DB 验证输出写入报告。
- [ ] **Step 6:** commit `fix: unnumbered heading detection in section splitter`

---

### Task 2: 笔记 CRUD API

**Files:**
- Create: `app/api/notes.py`（挂到 create_app）
- Test: `tests/test_api_notes.py`

**Interfaces:**
- Consumes: `notes` 表（核对 0001_init.sql 实际列：预期 paper_id/type/content/created_at——以迁移 SQL 为准）、`app.state.db`。
- Produces: `GET /api/papers/{paper_id}/notes` → `{"notes":[{"id","paper_id","note_type","content","created_at"}...]}`（created_at DESC）；`POST /api/papers/{paper_id}/notes` body `{"note_type": str, "content": str}` → `{"note_id": int}`（paper_id 不存在 → 404；note_type 限 `annotation|chat_summary|six_dim` → 否则 400）；`DELETE /api/notes/{note_id}` → `{"deleted": true}`（不存在 → 404）。**Ruling R1：列名与 CHECK 以迁移 SQL 为权威**——notes 表实为 `note_type`，CHECK 值 `section_analysis|annotation|chat_summary`；六维解读需新增 `six_dim` 值（Task 5 的 migration 0002 重建 notes 表扩 CHECK，保留存量行）；用户笔记复用既有 `annotation`；Task 3 的章节解读复用既有 `section_analysis`。NOTE_TYPES 常量集合暴露为 `app.api.notes.NOTE_TYPES`（Task 3 引用）。

- [ ] **Step 1: Write the failing tests**（6 个：list 空/非空、create 成功、create 非法 type 400、create 不存在 paper 404、delete 成功、delete 不存在 404；TestClient + monkeypatch app.state.db 风格沿 tests/test_api_papers.py）
- [ ] **Step 2: Run** — Expected: FAIL
- [ ] **Step 3: 实现**（async def 路由碰 db，沿 P1 惯例）
- [ ] **Step 4: Run** 全仓 — Expected: PASS（75+6=81）
- [ ] **Step 5:** commit `feat: notes CRUD api`

---

### Task 3: 深度解读引擎

**Files:**
- Create: `app/study/__init__.py`, `app/study/reader.py`
- Test: `tests/test_reader.py`

**Interfaces:**
- Consumes: `LLMGateway.chat(messages, tier="strong", max_tokens=...) -> {"text",...}`；`get_conn()` 读 papers/chunks_meta；`NOTE_TYPES`。
- Produces: `async def interpret_paper(paper_id: int, *, db: sqlite3.Connection, gateway, embedder_unused=None) -> dict`，返回 `{"six_dim": {background, innovation, architecture, formulas, experiments, limitations: str}, "sections": [{"section": str, "note": str}...]}`。流程（全部 to_thread 包裹 sqlite 读）：① 读论文行 + chunks_meta 按 section 聚合文本，每节超 6000 字符截断（保头部）；无编号节聚合后 Front Matter 跳过；② 每节一次 strong 调用（max_tokens=2048）生成该节中文解读，**顺序执行不并发**（避免网关并发压测自己），节间失败记录 "（本节解读失败：{err}）" 继续；③ 六维综合：全部节解读拼入一次 strong 调用（max_tokens=4096），要求严格 JSON 六键；解析失败重试一次（追加"只输出 JSON"），再失败抛 `InterpretationError`；④ 写 notes：每节 `note_type='section_analysis'`，六维 `note_type='six_dim'`（content 为 markdown；Ruling R1：列名 note_type，六维 CHECK 值由 Task 5 migration 0002 扩展——Task 3 写 six_dim 前先在测试里用临时连接建含 six_dim 的表结构，生产等 Task 5 落迁移）；⑤ papers.status：进入时置 'reading'（若为 new/pushed），全部成功后置 'read'。
- 辅助：`_extract_json(text: str) -> dict`（剥 ```json 围栏后 json.loads）。

- [ ] **Step 1: Write the failing tests**（fake gateway 类返回预设 JSON/markdown）

```python
def test_interpret_writes_section_and_six_dim_notes():  # 2 节论文 → notes 3 条（2 section_note + 1 six_dim），fake 返回合法 JSON
def test_interpret_retries_on_bad_json():               # fake 第一次返回 "抱歉..."，第二次合法 JSON → 成功且 gateway 调用次数含重试
def test_interpret_raises_after_second_bad_json():      # 两次都坏 → InterpretationError，papers.status 停在 'reading'，无 six_dim note
def test_long_section_truncated():                      # 构造 8000 字符节 → 发给 gateway 的 prompt 长度 < 该节原长（断言 fake 收到的文本被截到 ~6000）
def test_status_transitions_reading_then_read():        # 全程成功 → 'read'；中途异常 → 'reading'
def test_failed_section_noted_and_continues():          # 某节 gateway 抛错 → 该节 note 内容含 "解读失败"，其余节正常，整体成功
```

- [ ] **Step 2: Run** — Expected: FAIL
- [ ] **Step 3: 实现 app/study/reader.py**（prompt 中文；六维 JSON 键名固定 background/innovation/architecture/formulas/experiments/limitations）
- [ ] **Step 4: Run** 全仓 — Expected: PASS（81+6=87）
- [ ] **Step 5:** commit `feat: chapter-level six-dimension interpretation engine`

---

### Task 4: 对比引擎

**Files:**
- Create: `app/study/compare.py`
- Test: `tests/test_compare.py`

**Interfaces:**
- Consumes: `Embedder.embed`、`VectorStore.search(vector, top_k, paper_id)`（每篇 top_k=6）、`LLMGateway.chat(tier="strong", max_tokens=4096)`、db 读 papers 元数据。
- Produces: `async def compare_papers(paper_ids: list[int], question: str | None, *, db, embedder, store, gateway) -> dict` 返回 `{"matrix": str(markdown), "citations": [{"paper_id","page","quote"}]}`。检索 query：question 非空用 question embed；为空用"论文标题+abstract"逐篇 embed。片段标号 `[P{n}|页码]`（n 为 paper_ids 内序号 1 起）；答案中标记映射回 citations（同 P1 qa 的映射语义：重复去重、越界丢弃、无标记时全部片段为 citations）。

- [ ] **Step 1: Write the failing tests**

```python
def test_compare_with_question_uses_question_embedding():   # fake embedder 记录调用文本 → question 非空时调用文本为 question
def test_compare_without_question_uses_title_abstract():    # question=None → 调用文本含各篇标题
def test_compare_citations_mapped():                        # fake gateway 返回含 [P1|2] 标记 → citations 正确映射页码与片段
def test_compare_matrix_is_markdown_with_all_papers():      # fake 返回 markdown → matrix 原样返回
```

- [ ] **Step 2: Run** — Expected: FAIL
- [ ] **Step 3: 实现**（prompt 要求输出 markdown 对比表格：方法/核心思想/实验设置/结果/局限 × 各论文列；真实 embedder + :memory: qdrant 沿 conftest ingest_stack 模式）
- [ ] **Step 4: Run** 全仓 — Expected: PASS（87+4=91）
- [ ] **Step 5:** commit `feat: multi-paper comparison engine with citations`

---

### Task 5: 解读/对比 API 路由

**Files:**
- Modify: `app/api/__init__.py`（KNOWN 异常注册 `InterpretationError` → 502）、`app/main.py`（挂新路由）
- Modify: `app/migrations/`（新增 `0002_jobs_kind_and_notes_sixdim.sql`：`ALTER TABLE import_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'import'`；重建 notes 表扩 CHECK 加入 `'six_dim'`（保留存量行与索引——SQLite 改 CHECK 需建新表搬数据））
- Modify: `app/api/import.py`（kind 写入 'import'；`POST /api/papers/{paper_id}/interpret` 创建 kind='interpret' 的 job：path=`interpret:{paper_id}`，total=1）
- Create: `app/api/study.py`（interpret job 创建 + 轮询复用 + compare 同步路由）
- Modify: `app/ingest/batch.py`（新增 `async def run_interpretation(job_id, paper_id, db, gateway)`：调 interpret_paper，完成 done=1；异常 errors=[str(e)] + failed=1——job 必有终态）
- Test: `tests/test_api_study.py`

**Interfaces:**
- Produces: `POST /api/papers/{paper_id}/interpret` → `{"job_id": int}`（paper 不存在 404；已有 running 的同论文 interpret job → 409）；`GET /api/import/jobs/{id}` 沿 P1 契约（interpret 完成后 notes 可经 Task 2 路由取）；`POST /api/compare` body `{"paper_ids": [int...], "question": str|null}` → `{"matrix": str, "citations": [...]}`；校验：数量 <2 或 >5 → 400，任一 id 不存在 → 400（Review Focus #4）。
- Consumes: Task 3/4 全部签名、P1 batch job 模式。

- [ ] **Step 1: Write the failing tests**（9 个：interpret 创建 job 202/404/409；fake gateway 跑 run_interpretation → job done 且 notes 存在；gateway 全挂 → job failed errors 非空（Review Focus #3）；compare 成功/数量校验 400/不存在 id 400）
- [ ] **Step 2: Run** — Expected: FAIL
- [ ] **Step 3: 实现**（migration + 路由 + run_interpretation；compare 同步 await compare_papers）
- [ ] **Step 4: Run** 全仓 — Expected: PASS（91+9=100）
- [ ] **Step 5:** commit `feat: interpret job api + compare endpoint`

---

### Task 6: 前端精读视图 + 对比页 + 冒烟扩展

**Files:**
- Modify: `app/web/index.html`, `app/web/app.js`, `app/web/style.css`（论文详情视图、对比页、笔记区）
- Create: `app/web/md.js`（极简安全 markdown 渲染器）
- Modify: `scripts/smoke_test.py`（新增步骤 5/6/7）
- Test: 无 pytest（前端）；smoke 承担验证

**Interfaces:**
- Consumes: Task 2/5 全部路由。
- Produces: ① 论文列表点击 → 详情面板：元数据 + "生成深度解读"按钮（POST interpret → 轮询 job → 完成后渲染六维卡片 + 章节解读列表 + 状态徽标 reading/read）+ 笔记列表（添加/删除，textarea）；② 对比入口：列表多选（checkbox，2-5 篇）+ 可选问题框 → "生成对比" → matrix markdown 渲染 + 引用卡片；③ `md.js`：**先整体 HTML 转义再解析**，仅支持 标题/粗斜体/列表/表格/代码围栏/链接文本（不产生裸 HTML 标签——Review Focus #5）；④ job 轮询沿 P1 的 30 分钟停滞防御；⑤ smoke 新步骤：POST /api/papers/{id}/notes 含 `<script>alert(1)</script>` 的 content → GET notes 返回原文（API 层不转义不解析，断言原样返回）；interpret 一篇（fake 不行——真实 LLM，宽容重试 40×30s 沿 qa 模式）→ job done → GET notes 出现 six_dim；POST /api/compare [2,3] → matrix 非空。

- [ ] **Step 1: 实现 md.js + 详情/对比前端**（对照 app/api/study.py 与 notes 路由核实字段名）
- [ ] **Step 2: 扩展 smoke_test.py**（7 步结构，幂等）
- [ ] **Step 3: 验证** `sg docker -c "docker compose up -d --build"` → `scripts/smoke_test.py` 7/7 PASS；浏览器/手机实测详情页与对比页
- [ ] **Step 4:** commit `feat: deep-reading web ui + compare page + smoke steps`

---

### Task 7: P2 验收（controller 直执）

- [ ] **Step 1:** pytest 全绿（~100）。
- [ ] **Step 2:** 上传一篇真实新论文（具身智能相关，如 arXiv 最新 VLA 论文）→ 触发深度解读 → 核对六维解读质量（背景/创新/架构/公式/实验/局限各维有实质内容且引用节名真实）。
- [ ] **Step 3:** 对 Diffusion Policy + Flow Matching + RT-2/OpenVLA 执行对比："VLA、Diffusion Policy 和 Flow Matching 有什么区别" → 验收结构化讲解 + 引用页码。
- [ ] **Step 4:** 笔记 CRUD 演示 + XSS 注入内容显示安全。
- [ ] **Step 5:** 演示给用户，P2 完成。
