# LLM 统一与 Legacy 退役 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除直连 LLM Gateway 的全部旧路径（旧路由/旧页面/精读比较引擎/旧导入 job），所有模型调用只经 Claude Runner；导入元数据完全确定性化。

**Architecture:** 纯退役 + 收敛：v2 导入路径（imports.pipeline）本就不经 LLM（arXiv Atom / Crossref / pymupdf 内嵌元数据），只需删除 legacy 包、旧前端页、ingest 中的 LLM 上传路径与旧 job 批处理；Runner 删除旧同步 /run 包装；精读能力由强化后的 paper_read SKILL.md 承载。数据库表全部保留（不删数据、无新迁移）。

**Tech Stack:** Python 3.12、FastAPI、httpx、pytest；原生 JS 前端（仅删除）。

**Spec:** `docs/superpowers/specs/2026-11-17-modular-refactor-design.md`（§7 LLM 统一、§9.1 债务）

## Global Constraints

- 全套测试每任务结束通过：`HF_HOME="$PWD/data/hf" HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider`（当前基线 223）。
- **不新增迁移、不删除任何数据库表**（notes/knowledge_map/interest_profile/llm_usage/push_log/import_jobs 数据保留）。
- 保留域（agent/sessions/papers/reader/imports/workbench/schedules）的 API 路径与响应形状不变。
- bge-m3 + Qdrant 保留为检索工具数据源；main 仍初始化 RAG 栈。
- `ops/` 敏感文件永不提交；独立 worktree 执行；`.venv`/`data/hf` 用主仓库绝对路径。
- 退役顺序保证每个任务结束系统可启动：先删调用方（路由/页面），再删被调方（gateway/引擎/批处理）。

## Review Focus

1. **上传导入仍可用且无 LLM**：v2 上传路径确定性元数据（pymupdf 内嵌 + 文件名回退），test_reader_imports 上传用例与冒烟保持绿。
2. **无残留 gateway 引用导致启动崩溃**：main lifespan、ingest TYPE_CHECKING、conftest 全部清理；create_app() 可构建（test_route_surface）。
3. **arXiv/DOI 导入元数据不变**：Atom API / Crossref 路径与其测试原样保留。
4. **Runner 只剩异步协议**：/run 删除后 app 与测试全部走 /runs + events；health 形状更新无残留断言。
5. **数据保留**：旧表不删、已有论文/批注/会话可读（reader/sessions 测试绿，迁移数量不变）。

---

### Task 1: Runner 移除旧同步 /run 包装

**Files:**
- Modify: `agent_runner/server.py`（删 /run、_lock；health 去 busy）、`tests/test_runner_jobs.py`、`tests/test_agent_mvp.py`、`tests/test_task_sessions.py`、`tests/test_workbench.py`
- Test: 上述迁移后的用例

**Interfaces:**
- Produces: Runner 仅 `POST /runs`、`GET /runs/{id}`、`GET /runs/{id}/events`、`POST /runs/{id}/cancel`、`GET /health`（无 busy 字段，含 concurrency/queued/running）
- Consumes: 计划二引擎（jobs.JobEngine）

- [ ] **Step 1: 迁移测试（RED）**

- `test_runner_jobs.py::test_legacy_run_wrapper_and_http_protocol` 改名 `test_http_protocol`，删除 /run 段，其余保留。
- `test_agent_mvp.py::test_runner_rejects_search_without_real_tool_success`：POST /runs → 202，GET /runs/{id} 取 result，断言 failed + usage 10。
- `test_task_sessions.py::test_native_missing_transcript_is_not_silently_replayed`：POST /runs（native_ready=True）→ GET result.error 含 '原生会话文件缺失'。
- `test_task_sessions.py::test_native_resume_uses_same_workspace_and_session_id`：probe 内改用 `engine.submit` + `await job['task']` + `engine.get(...)['result']`（不再调 server.run）。
- `test_workbench.py::test_runner_native_image_stream_preserves_session_scope`：POST /runs → 轮询 GET /runs/{id} 至终态；captured args/stdin 断言不变。
- grep 确认无其他 `/run`、`busy` 断言残留。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_runner_jobs.py tests/test_agent_mvp.py tests/test_task_sessions.py tests/test_workbench.py -q`
Expected: 迁移用例 FAIL（/run 仍在但断言改向 /runs 的已通过？以实际为准：未删 /run 前新断言应已绿——本任务 RED 体现在删除后旧断言不存在；若全绿则直接进 Step 3 删除并复跑）

- [ ] **Step 3: 删除 /run 与 _lock**

server.py 删除 `@app.post('/run')` 整个函数、`_lock`、health 的 `'busy'` 键。RunRequest 保留（/runs 用）。

- [ ] **Step 4: 运行测试**

Run: 四文件 + 全套
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_runner/server.py tests/
git commit -m "refactor: remove legacy synchronous runner endpoint"
```

---

### Task 2: Legacy 路由/页面/Gateway 退役

**Files:**
- Delete: `app/legacy/`（整包）、`app/web/legacy.html`、`app/web/app.js`、`app/web/style.css`、`tests/test_llm_gateway.py`、`tests/test_api_qa.py`、`tests/test_api_study.py`、`tests/test_api_notes.py`、`tests/test_api_papers.py`、`tests/test_compare.py`、`tests/test_reader.py`（测的是 legacy study.reader）
- Modify: `app/main.py`（删 legacy 路由 include、LLMGateway import、app.state.gateway）、`app/config.py`（删 llm_providers/llm_fast/llm_strong 与 from_env 的 LLM_PROVIDERS 解析）、`tests/conftest.py`（删 FakeGateway 与 gateway patch；api_client 改为无参工厂）、引用 api_client(gateway) 的剩余测试
- Test: `tests/test_route_surface.py`、`tests/test_app_health.py`、`tests/test_db_migrations.py`（Settings 相关断言更新）

**Interfaces:**
- Produces: `Settings(data_dir, qdrant_url)`（无 LLM 字段）；`api_client()` 无参 fixture；create_app 不含 /api/qa、/api/study、/api/notes、/api/papers、/api/import、/legacy.html
- Consumes: 无

- [ ] **Step 1: 更新测试（RED）**

conftest：删 FakeGateway 类与 `monkeypatch.setattr(main,'LLMGateway',...)`；`_make()` 无参。test_db_migrations 的 `test_settings_*llm*` 三个用例删除，`test_settings_from_env` 去掉 LLM 断言。test_route_surface 追加断言：`'/api/qa' not in paths and '/api/study/interpret' not in paths`（以实际旧路径为准，grep 基线 openapi）。grep 其余 `api_client(` 调用点改无参。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_route_surface.py tests/test_db_migrations.py -q`
Expected: FAIL（legacy 路由仍在 / Settings 仍有 LLM 字段）

- [ ] **Step 3: 删除与清理**

按 Files 清单删除；main.py 删 `from .legacy import ...`、五个 include、`from .legacy.gateway import LLMGateway`、`app.state.gateway=...`。config.py 删三字段与解析/校验分支。确认 `grep -rn "legacy\|LLMGateway\|llm_providers" app/ tests/ scripts/ --include="*.py"` 仅剩 ingest 的 TYPE_CHECKING 引用（Task 3 清理）与文档。

- [ ] **Step 4: 运行测试**

Run: 全套
Expected: PASS（数量下降属预期——legacy 用例删除；记录准确数量）

- [ ] **Step 5: Commit**

用显式文件清单 add（删除用 `git rm` 已暂存）：`git add app/main.py app/config.py tests/conftest.py tests/test_db_migrations.py tests/test_route_surface.py <其余引用更新文件>`，确认 `git status --short` 无 ops/ 文件后提交：
```bash
git commit -m "refactor: retire legacy gateway, study engines, old routers and pages"
```

---

### Task 3: Ingest 去 LLM 残留 + 服务层框架解耦

**Files:**
- Delete: `app/ingest/batch.py`、`tests/test_api_import.py`
- Modify: `app/ingest/pipeline.py`（删 ingest_from_upload/_extract_metadata/_METADATA_PROMPT/_FIRST_PAGE_CHARS/_FALLBACK_ABSTRACT_CHARS/TYPE_CHECKING gateway）、`app/main.py`（删 fail_interrupted_jobs 调用与 import）、`tests/test_pipeline.py`（删 _FakeGateway/_upload/上传路径用例，保留 ingest_paper/ingest_arxiv/dedup 用例）、`app/imports/service.py` 与 `app/schedules/service.py`（删 fastapi.HTTPException import 与捕获）、`tests/test_reader_imports.py::test_full_queue_keeps_import_visible_and_retryable`（替身改抛 ServiceError）、`app/workbench/service.py` + `app/workbench/repository.py`（paper_exists 改经 papers.service，删自有 SQL）
- Test: 上述 + 全套

**Interfaces:**
- Produces: ingest 仅 `ingest_paper`/`ingest_arxiv`/`download_arxiv_pdf`/`_parse_and_embed` 等确定性函数；imports/schedules service 无 fastapi import
- Consumes: `papers.service.paper_exists`（计划一已有）

- [ ] **Step 1: 更新测试（RED）**

test_full_queue 替身 `raise ServiceError(429,'Queue full; please wait')`（from app.core.errors）。test_pipeline 删上传用例后应绿；新增 `test_ingest_module_has_no_llm`：`import app.ingest.pipeline as p; assert not hasattr(p,'ingest_from_upload')`。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py::test_ingest_module_has_no_llm tests/test_reader_imports.py::test_full_queue_keeps_import_visible_and_retryable -q`
Expected: FAIL

- [ ] **Step 3: 删除与解耦**

按 Files 清单执行。imports/service.start_import 的 `except (HTTPException, ServiceError)` → `except ServiceError`；schedules/service.schedule_loop 同理（删 HTTPException import）。workbench.save_workspace 的 `repo.paper_exists` → `papers_service.paper_exists`（函数内局部导入防环）。

- [ ] **Step 4: 运行测试**

Run: 全套
Expected: PASS；`grep -rn "fastapi" app/imports/service.py app/schedules/service.py app/workbench/service.py` 无结果

- [ ] **Step 5: Commit**

```bash
git add app/ingest app/main.py app/imports/service.py app/schedules/service.py app/workbench tests/
git commit -m "refactor: remove LLM upload path and legacy batch jobs, decouple services from fastapi"
```

---

### Task 4: 冒烟重写 + 配置文档

**Files:**
- Modify: `scripts/smoke_test.py`（重写为管理链路冒烟，零模型调用）、`.env.example`（删 LLM_PROVIDERS/LLM_FAST/LLM_STRONG 段）、`README.md`（部署步骤去掉 LLM 密钥；冒烟描述更新）、`docker-compose.yml`（如有 LLM 专用 env 则删；env_file .env 保留）
- Test: 冒烟脚本对运行服务执行（部署后）；本任务内以 `python -c "import ast; ast.parse(open('scripts/smoke_test.py').read())"` + 干跑校验

**Interfaces:**
- Produces: 冒烟步骤 = /health → /api/library/papers → /api/sessions/templates → /api/workbench/states/{id} PUT/GET → /api/agent/status（runner 在线）；任一步失败退出码 1；幂等
- Consumes: 保留域 API

- [ ] **Step 1: 重写冒烟**

按 Interfaces 步骤重写；删除上传/QA/interpret/compare/notes 步骤与 20 分钟 LLM 宽容重试（管理链路 5s 超时、3 次重试即可）。workspace id 用固定 32 位 hex 探针，PUT 后 GET 比对再恢复原值。

- [ ] **Step 2: 配置与 README**

.env.example 删 LLM 段并注明"模型凭据由宿主机 Claude 配置提供，app 无需 LLM 密钥"。README 部署第 2 步改为只需 DATA_DIR/QDRANT 等基础项；冒烟段落更新。

- [ ] **Step 3: 校验 + Commit**

Run: `.venv/bin/python -c "import ast; ast.parse(open('scripts/smoke_test.py').read())"` + 全套
```bash
git add scripts/smoke_test.py .env.example README.md docker-compose.yml
git commit -m "docs: model-free smoke test and deployment without LLM keys"
```

---

### Task 5: 精读能力强化（paper_read SKILL.md）

**Files:**
- Modify: `skills/paper_read/SKILL.md`（version 0.3.0；追加精读协议段）、`skills/paper_compare/SKILL.md` 与 `skills/paper_review/SKILL.md`（核对证据边界表述，缺则补）
- Test: `tests/test_agent_mvp.py` 追加 `test_skill_docs_cover_deep_reading`

- [ ] **Step 1: 写失败测试**

```python
def test_skill_docs_cover_deep_reading():
    from pathlib import Path
    text = Path('skills/paper_read/SKILL.md').read_text()
    for kw in ('研究问题', '贡献边界', '覆盖范围', '证据', '作者陈述'):
        assert kw in text
```
（'研究问题' 与 '贡献边界' 为新增段关键词，现有文档不含 → RED 确定。）

- [ ] **Step 2: 运行确认失败 → 强化 SKILL.md**

追加"精读协议"段：首轮声明本次覆盖范围（读了哪些 chunk/页）；按 研究问题→方法→实验→局限→贡献边界 组织；区分作者陈述/模型推断/未核验；原始页证据用 [论文N，第M页]；不编造实验与引用；图表未读取时明确说明。version 升 0.3.0。compare/review 核对"不编造、问题可回原文"表述。

- [ ] **Step 3: 运行测试 + Commit**

Run: 全套
```bash
git add skills/ tests/test_agent_mvp.py
git commit -m "feat: deep-reading protocol in paper_read skill"
```

---

### Task 6: 收尾 — 文档、结构核验、全量回归

**Files:**
- Modify: `架构.md`（§1/§2/§5/§8 移除 legacy 描述与旧接口行，§7 数据模型注明旧表保留不服务，§10 更新）、`enviroment.md`（LLM 配置段改为 Runner-only）、设计文档（§7 标记完成、§9.1 勾销 HTTPException/paper_exists 债务）
- Test: 全套

- [ ] **Step 1: 结构核验**

Run: `grep -rn "app\.legacy\|LLMGateway\|llm_providers\|ingest_from_upload\|fail_interrupted_jobs" app/ tests/ scripts/ agent_runner/ --include="*.py"`
Expected: 无结果。`ls app/web/` 无 legacy.html/app.js/style.css。迁移文件数仍为 8。

- [ ] **Step 2: 全套回归**

Run: Global Constraints 命令
Expected: PASS，记录准确数量

- [ ] **Step 3: 文档更新并提交**

```bash
git add 架构.md enviroment.md docs/superpowers/specs/2026-11-17-modular-refactor-design.md
git commit -m "docs: LLM unified through runner, legacy retired"
```