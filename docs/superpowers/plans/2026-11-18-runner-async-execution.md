# Runner 异步执行模型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude 执行改为后台任务：提交即返回、SSE 实时进度、可取消、按 Skill 配置护栏（阅读/比较类无硬超时）、Runner 并发 2 排队执行。

**Architecture:** Runner 拆为 cli（进程构造）+ jobs（任务引擎：队列/并发/事件/取消/磁盘持久化）+ server（HTTP/SSE 端点，保留旧 `/run` 同步包装至计划三）。app 侧 execute_run 改为"提交 + 消费 Runner SSE + 进度落库"，新增取消与浏览器 SSE 端点；迁移 0008 重建 agent_runs（status CHECK 增加 cancelled、新增 progress_json）。跨域 agent_runs 读取先收敛到 agent.service（计划一遗留债务的前置项）。

**Tech Stack:** Python 3.12、FastAPI、httpx（SSE 流）、asyncio、SQLite、pytest；前端仅最小状态适配（原生 JS）。

**Spec:** `docs/superpowers/specs/2026-11-17-modular-refactor-design.md`（§6 执行模型、§9.1 前置债务）

## Global Constraints

- 全套测试每任务结束通过：`HF_HOME="$PWD/data/hf" HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider`（当前基线 201）。
- 现有 API 路径与响应形状保持兼容；新增端点只增不改。旧 Runner `POST /run` 保留为同步包装（回退兼容：旧 app 镜像 + 新 Runner），计划三移除。
- Skill 护栏精确值：chat/search_library/search_arxiv/paper_discover = 6 回合 / 1024 输出 token / 120s / $0.10；paper_import = 6 / 2048 / 180s / $0.20；paper_read/paper_review/paper_compare = 30 / 8192 / **无硬超时(None)** / $1.00。
- Runner 并发 `RESEARCH_AGENT_CONCURRENCY` 默认 2；queued+running ≥ 8 → 429。
- 取消终止进程组（SIGTERM→3s→SIGKILL），保留已产生用量；不自动重试任何可能已计费的请求。
- 重启中断的运行标记 failed，不自动重放；幂等键沿用。
- 单 Web worker、单 Runner 进程部署不变；data 目录布局不变；`ops/` 敏感文件永不提交。
- 跨域只走 service；sessions/reader 调 agent.service 必须函数内局部导入（agent.service 顶层已 import sessions/reader，防环）。
- 被测试 patch 的模块属性保持调用时经模块解析（`jobs.asyncio.create_subprocess_exec`、`cli.load_environment`、`runner_client.client`）。
- 在独立 worktree 执行；`.venv` 与 `data/hf` 用主仓库绝对路径。

## Review Focus

1. **长任务不被杀**：paper_read 类运行超过旧 120s 限制仍正常完成（Task 4 用可配置短超时替身验证超时分支 + 无超时分支）。
2. **取消真实生效**：cancel 杀死进程组、状态 cancelled、保留部分用量、会话立即解除忙碌（Task 4/6 测试）。
3. **Runner 中途重启/断流**：app 将运行标记 failed 且不自动重放（Task 5 测试断流分支）。
4. **迁移 0008 数据安全**：存在 research_schedules/reader_translations/import_requests 引用行时重建 agent_runs 不丢数据、FK 完整（Task 2 测试）。
5. **并发下的拒绝路径**：队列满 429、会话忙碌 409 不杀死调度循环、不泄漏并发槽（Task 4/6 测试 + 现有 schedules 用例）。

---

### Task 1: 前置债务 — 跨域 agent_runs 读取收敛到 agent.service

**Files:**
- Modify: `app/agent/service.py`、`app/agent/repository.py`、`app/sessions/service.py`、`app/sessions/repository.py`、`app/reader/service.py`、`app/reader/repository.py`
- Test: 现有 `tests/test_task_sessions.py`、`tests/test_reader_imports.py`、`tests/test_workbench.py`（行为不变即验收）

**Interfaces:**
- Produces（agent.service 新增）: `run_count(db, sid) -> int`；`last_run_summary(db, sid) -> Row|None`（status/answer/prompt）；`has_active_run(db, sid) -> bool`；`session_runs(db, sid, before, limit) -> list[Row]`（rowid AS sequence）；`conversation_ids_matching(db, q) -> list[int]`；`runs_by_ids(db, ids) -> dict[str, dict]`（键 run_id，值 {status, answer, error}）
- Consumes: 现有 agent.repository SQL（搬移自 sessions/reader repository）

- [ ] **Step 1: 基线**

Run: `.venv/bin/python -m pytest tests/test_task_sessions.py tests/test_reader_imports.py tests/test_workbench.py -q`
Expected: PASS（记录数量）

- [ ] **Step 2: 搬移与改道**

sessions.repository 的 `run_count/last_run/has_active_run/session_runs` SQL 搬入 agent.repository；sessions.service 对应调用改为函数内 `from ..agent import service as agent_service`。`search_sessions` 的 q 搜索 EXISTS 子查询改为：service 先 `agent_service.conversation_ids_matching(db, q)`，repository 按 id 列表过滤（空列表 → 空结果，保持原语义）。reader.repository 的 translations 两条 JOIN 改为只查 `reader_translations t.*`；reader.service 用 `agent_service.runs_by_ids` 合并 status/answer/error 字段（list_translations 与 find_cached_translation 两处，输出形状逐字不变）。sessions.repository 不再出现 agent_runs 表名。

- [ ] **Step 3: 运行测试**

Run: 基线三文件 + 全套
Expected: PASS，数量一致；`grep -n "agent_runs" app/sessions/repository.py app/reader/repository.py` 无结果

- [ ] **Step 4: Commit**

```bash
git add app/agent app/sessions app/reader
git commit -m "refactor: converge cross-domain agent_runs reads into agent service"
```

---

### Task 2: Skill 护栏配置 + 迁移基建 + 0008

**Files:**
- Modify: `app/agent/catalog.py`（SKILLS 每条加护栏字段）、`app/core/db.py`（迁移期间关闭 FK）
- Create: `app/migrations/0008_agent_async.sql`
- Test: `tests/test_db_migrations.py`（追加）、`tests/test_agent_mvp.py`（catalog 断言追加）

**Interfaces:**
- Produces: SKILLS 条目形状 `{name, tools, max_calls, max_turns, max_output_tokens, timeout_s, max_budget_usd}`（值见 Global Constraints）；agent_runs 新列 `progress_json TEXT NOT NULL DEFAULT '{}'`；status CHECK 含 `'cancelled'`
- Consumes: 无

- [ ] **Step 1: 写失败测试**

`tests/test_db_migrations.py` 追加：
```python
def test_0008_preserves_rows_and_foreign_keys(tmp_path):
    #  fresh db → 插入 conversation、agent_run、research_schedules(last_run_id=run)、
    #  reader_translations(run_id=run)、import_requests(run_id=run) →
    #  重新 get_conn 触发迁移后：行数不变、progress_json=='{}'、
    #  PRAGMA foreign_key_check 为空、可 INSERT status='cancelled' 的运行
```
`tests/test_agent_mvp.py` 追加 `test_catalog_budgets`：断言 chat 与 paper_read 的四个护栏字段精确值（paper_read timeout_s is None）。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_db_migrations.py tests/test_agent_mvp.py::test_catalog_budgets -q`
Expected: FAIL（cancelled 违反 CHECK / 缺字段）

- [ ] **Step 3: 实现**

`core/db.py::_apply_migration`：executescript 前 `conn.execute("PRAGMA foreign_keys=OFF")`，finally 恢复 `ON`（迁移脚本是可信 DDL；SQLite 表重建的标准前提）。`0008_agent_async.sql` 按 SQLite 12 步重建：新表含原 19 列（顺序：id, request_key, conversation_id, skill, skill_version, prompt, status, answer, model, usage_json, tool_calls_json, metadata_json, cli_estimated_cost_usd, error, created_at, finished_at, context_json, purpose, attachment_ids_json）+ progress_json，CHECK 五状态；`INSERT INTO agent_runs_new SELECT *, '{}' FROM agent_runs`；DROP/RENAME；重建 `idx_agent_runs_conversation`。catalog 按精确值加字段。

- [ ] **Step 4: 运行测试**

Run: 两文件 + 全套
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/agent/catalog.py app/core/db.py app/migrations/0008_agent_async.sql tests/test_db_migrations.py tests/test_agent_mvp.py
git commit -m "feat: per-skill budgets and agent_runs async migration"
```

---

### Task 3: Runner CLI 构造提取（cli.py）

**Files:**
- Create: `agent_runner/cli.py`
- Modify: `agent_runner/server.py`（搬出 load_environment/current_model/image_blocks/args 构造，/run 暂调 cli）
- Test: 现有 runner 用例（patch 目标改 `agent_runner.cli.load_environment` 等）

**Interfaces:**
- Produces: `cli.load_environment() -> dict`；`cli.current_model(env, vision=False) -> str`；`cli.image_blocks(body, runtime: Path) -> list[dict]`；`cli.build_args(skill: dict, model: str, session_id: str, resume: bool, mcp: dict, skill_md: str, has_images: bool) -> list[str]`（--max-turns/--max-budget-usd 取 skill 护栏；输出恒为 stream-json + --verbose；has_images 时加 --input-format stream-json）；`cli.build_input(body, history, resume) -> bytes`（文本/图片两种输入）
- Consumes: `app.agent.catalog.SKILLS`

- [ ] **Step 1: 基线**

Run: `.venv/bin/python -m pytest tests/test_agent_mvp.py tests/test_task_sessions.py tests/test_workbench.py -q`
Expected: PASS

- [ ] **Step 2: 提取**

纯搬移 + 参数化：server.py 的 env/model/image/args/input 逻辑移入 cli.py，行为逐字保留（除输出格式恒为 stream-json——/run 包装在 Task 4 适配解析）。`CLAUDE_CODE_MAX_OUTPUT_TOKENS` 改为按 skill 注入（在 build env 时）。现有测试 patch 目标 retarget；`server.RUNTIME` 保留（Task 4 引擎用）。

- [ ] **Step 3: 运行测试**

Run: 基线三文件 + 全套
Expected: PASS（/run 仍同步返回；其结果解析本步暂兼容 json 与 stream-json 两种输出）

- [ ] **Step 4: Commit**

```bash
git add agent_runner/cli.py agent_runner/server.py tests/
git commit -m "refactor: extract runner CLI construction with per-skill budgets"
```

---

### Task 4: Runner 任务引擎 + 新协议

**Files:**
- Create: `agent_runner/jobs.py`
- Modify: `agent_runner/server.py`（新端点 + /run 包装 + health 扩展）
- Test: `tests/test_runner_jobs.py`（新建）

**Interfaces:**
- Produces:
  - `jobs.JobEngine(runtime: Path, concurrency: int)`；`async start()`（磁盘 queued/running 状态标记 failed='Runner restarted'）；`async submit(run_id, skill_id, body: dict) -> dict`（{'run_id','status'}；满 → raise `jobs.QueueFull`）；`get(run_id) -> dict|None`（{'run_id','status','progress','result'}）；`async cancel(run_id) -> dict|None`；`async events(run_id) -> AsyncIterator[dict]`（回放 events.jsonl + 直播至终态）；`async close()`
  - 磁盘：`runs/<id>/status.json`、`events.jsonl`、`result.json`（终态完整 payload，形状与旧 /run 返回一致，status 可为 cancelled）
  - 事件帧形状（events 迭代器与 SSE 一致）：进度 `{'type':'progress','event':<CLI assistant/tool 事件子集>}`；终态 `{'type':'result','result':<完整 payload>}`
  - HTTP：`POST /runs` 202；`GET /runs/{id}`；`GET /runs/{id}/events`（SSE `data: {json}\n\n`）；`POST /runs/{id}/cancel`；`GET /health` 增加 concurrency/queued/running；`POST /run` = submit + 等待终态返回 result（旧形状）
- Consumes: `cli.*`（Task 3）；SKILLS 护栏（Task 2）

- [ ] **Step 1: 写失败测试**

`tests/test_runner_jobs.py`（fake CLI 进程沿用现有 spawn 替身模式，patch `jobs.asyncio.create_subprocess_exec` 与 `cli.load_environment`，`JobEngine(tmp_path, concurrency)`）：
- `test_submit_streams_progress_and_result`：fake proc 输出 assistant/tool_use/result 三行 stream-json → submit 后 events 含 progress 与终态 result；result.json payload status succeeded、usage 保留
- `test_no_hard_timeout_for_reading_skill`：monkeypatch SKILLS 使 paper_read timeout_s=None、chat timeout_s=0.1；fake proc sleep 0.3s 后输出 result → paper_read succeeded、chat failed（同一替身两种护栏）
- `test_timeout_skill_fails`：上例 chat 分支断言进程被杀（替身记录 killpg）、status failed、error 含超时文案
- `test_cancel_kills_and_preserves_usage`：运行中 cancel → 进程组收到 SIGTERM（替身记录）、status cancelled、result 含已收到的部分 usage
- `test_concurrency_and_queue`：concurrency=1 时第二个 submit 排队（status queued），第一个完成后第二个 running；queued+running≥8 → QueueFull
- `test_restart_marks_interrupted_failed`：磁盘 status.json running → start() 后 get 返回 failed
- `test_legacy_run_wrapper_sync`：POST /run 仍返回旧形状 payload

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_runner_jobs.py -q`
Expected: FAIL（jobs 模块不存在）

- [ ] **Step 3: 实现**

引擎要点：每 job 一个 asyncio task；semaphore(concurrency) 在 spawn 前获取；stdout 逐行解析 stream-json，assistant/tool 事件追加 events.jsonl 并更新内存 progress；result 事件 → 沿用旧 payload 构建与校验逻辑（session_id 不匹配/search 无成功工具/空文本 → failed，逐字搬移）；timeout_s 非 None 用 asyncio.wait_for 包裹整个监控；CancelledError → stop_process → cancelled payload（usage 取已收到的 result 事件否则 {}）；终态写 result.json/status.json。SSE 端点用 StreamingResponse，先回放磁盘事件再订阅内存队列（asyncio.Queue per job，终态后关闭）。/run 包装：submit + await 终态事件 + 返回 result。

- [ ] **Step 4: 运行测试**

Run: tests/test_runner_jobs.py + 基线三文件 + 全套
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_runner/jobs.py agent_runner/server.py tests/test_runner_jobs.py
git commit -m "feat: runner job engine with queue, SSE progress, cancel and per-skill timeouts"
```

---

### Task 5: app 运行编排 v2（提交 + 消费 SSE + 进度落库）

**Files:**
- Modify: `app/agent/service.py`（execute_run 重写、view 加 progress、init_agent_state 去 semaphore）、`app/agent/repository.py`（update_progress、finish_run 支持 cancelled）、`app/agent/router.py`（status limits）
- Test: `tests/test_agent_mvp.py`、`tests/test_task_sessions.py`、`tests/test_reader_imports.py`、`tests/test_workbench.py`（MockTransport 改新协议）

**Interfaces:**
- Produces: `execute_run(run_id, state)`：POST runner `/runs` → 流式 GET `/runs/{id}/events`；progress 事件节流写 `agent_runs.progress_json`（工具事件或距上次 ≥1s）；终态 result → 现有 finish 逻辑（status 含 cancelled）；断流/未知 run → failed（沿用原文案）。`view(row)` 输出含 `progress`。status_view limits：`{'concurrency': <runner health>, 'max_queued': 8, 'skills': {id: 四护栏}, 'cost_verified': False}`
- Consumes: Runner 新协议（Task 4）；progress_json 列（Task 2）

- [ ] **Step 1: 更新测试为新协议（RED）**

现有 MockTransport handler 改为：`/health` 不变；`POST /runs` → 202 {'run_id','status':'queued'}；`GET /runs/{id}/events` → SSE 字节流（progress 一帧 + result 一帧，payload 用原 canned result）；`GET /runs/{id}` → 终态。新增 `test_progress_persisted_during_run`（断言运行中 GET run 含 progress）与 `test_stream_break_marks_failed_no_retry`（handler 断流 → failed，原文案）。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_agent_mvp.py -q`
Expected: FAIL（execute_run 仍 POST /run）

- [ ] **Step 3: 实现**

execute_run 按 Interfaces 重写；httpx 流式读取 SSE（`client.stream('GET', ...)`，读超时 None）；去掉 app semaphore（Runner 门控并发）；create_run 的 cap 8 与会话忙碌检查不变；finish_run 写 cancelled 状态。

- [ ] **Step 4: 运行测试**

Run: 四个测试文件 + 全套
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/agent tests/
git commit -m "feat: app orchestration submits runner jobs and persists streaming progress"
```

---

### Task 6: 取消 + 浏览器 SSE + 启动清理

**Files:**
- Modify: `app/agent/router.py`、`app/agent/service.py`、`app/agent/repository.py`
- Test: `tests/test_agent_mvp.py`（追加取消用例）

**Interfaces:**
- Produces: `POST /api/agent/runs/{run_id}/cancel`：终态 → 409 '任务已结束'；Runner 返回 cancelled/404 → 本地标记 cancelled（error='已取消'）；Runner 离线 → 503 'Runner 离线，无法取消'。`GET /api/agent/runs/{run_id}/events`：StreamingResponse，每秒轮询本库 run，状态/progress 变化即发 `data: {json}`，终态发末帧关闭。`service.cancel_run(db, run_id, state) -> dict`
- Consumes: Runner cancel（Task 4）；execute_run 终态处理（Task 5）

- [ ] **Step 1: 写失败测试**

`test_cancel_running_run`：MockTransport runner cancel → cancelled；POST cancel 后 run 状态 cancelled、会话可立即新建 run（忙碌解除）。`test_cancel_finished_conflict`：succeeded run → 409。`test_cancel_runner_offline_503`。`test_app_sse_emits_terminal`：对已完成 run 请求 events → 首帧即终态。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_agent_mvp.py -k cancel -q`
Expected: FAIL（404/405）

- [ ] **Step 3: 实现**

cancel_run：running/queued 均经 Runner cancel 确认；Runner 404（重启丢失）→ 本地 cancelled；execute_run 收到 cancelled 终态正常落库。SSE 端点只读自己库（不代理 Runner 连接），单 worker 下安全。

- [ ] **Step 4: 运行测试**

Run: tests/test_agent_mvp.py + 全套
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/agent tests/test_agent_mvp.py
git commit -m "feat: run cancellation and browser SSE progress endpoint"
```

---

### Task 7: 前端最小适配（cancelled 终态）

**Files:**
- Modify: `app/web/reader/chat.js`（watch 终态集合 + states 映射）、其他含状态映射处（grep `'succeeded'` 定位，如 workbench/manage 的 last_status 展示）
- Test: 无 JS 测试基建——手动验证步骤 + 现有全套不回归

- [ ] **Step 1: 定位与修改**

`grep -rn "succeeded" app/web/ --include="*.js" --include="*.html"`：chat.js watch 的终态判断加 'cancelled'；states 映射加 `cancelled:'已取消'`；其余展示处同步。running 状态展示 `run.progress` 摘要（若有，一行文本，不改布局）。

- [ ] **Step 2: 手动验证**

worktree 内起隔离实例（不碰生产 data/）：
```bash
V=$(mktemp -d); mkdir -p $V/agent
.venv/bin/python -m uvicorn agent_runner.server:app --uds $V/agent/runner.sock &
DATA_DIR=$V QDRANT_URL=':memory:' HF_HOME=/home/f/research-assistant/data/hf HF_HUB_OFFLINE=1 \
  AGENT_RUNNER_SOCKET=$V/agent/runner.sock .venv/bin/python -m uvicorn app.main:app --port 8601 &
```
浏览器开 `http://127.0.0.1:8601`，建 chat 会话发最小提问（如"回复 OK"）→ 运行中点取消（或直接 POST cancel API）→ 界面显示"已取消"、输入框解除忙碌。验证后 kill 两个进程、删除 $V。记录结果。

- [ ] **Step 3: 全套回归 + Commit**

```bash
git add app/web/
git commit -m "feat: frontend handles cancelled runs and progress summary"
```

---

### Task 8: 收尾 — 文档、结构核验、全量回归

**Files:**
- Modify: `架构.md`（§5.4 执行约束更新为新护栏/并发/取消/SSE）、`enviroment.md`（执行限制段）、`docs/superpowers/specs/2026-11-17-modular-refactor-design.md`（§9.1 债务勾销 agent_runs 项）
- Test: 全套

- [ ] **Step 1: 结构核验**

Run: `grep -rn "agent_runs" app/sessions/ app/reader/`（应无）；`grep -n "Semaphore" app/agent/service.py`（应无）；旧 `/run` 仅存于 server.py 包装与测试。

- [ ] **Step 2: 全套回归**

Run: Global Constraints 命令
Expected: PASS，记录准确数量

- [ ] **Step 3: 文档更新并提交**

```bash
git add 架构.md enviroment.md docs/superpowers/specs/2026-11-17-modular-refactor-design.md
git commit -m "docs: async execution model, budgets and cancellation"
```