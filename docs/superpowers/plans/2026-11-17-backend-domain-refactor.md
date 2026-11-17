# 后端功能域重组 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `app/` 重组为功能域 × 三层（router/service/repository）结构，行为与接口完全不变，全套测试持续通过。

**Architecture:** 纯结构性重构：逐域搬移 + 分层，跨域只走 service，SQL 全部下沉 repository，服务层错误统一 `ServiceError`。旧模块路径不留永久 shim——每个任务内同步更新 app/tests/agent_runner/scripts 的全部引用。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、SQLite（WAL）、pytest。

**Spec:** `docs/superpowers/specs/2026-11-17-modular-refactor-design.md`（§5 目标结构、§9 约束）

## Global Constraints

- 所有现有 HTTP 路径、请求/响应形状、状态码、错误文案**逐字不变**（现有测试即验收标准）。
- 数据库 schema 与 `app/migrations/` 不变；本计划不新增迁移。
- Runner 协议不变；`agent_runner/` 仅更新 import 路径。
- 每个任务结束运行全套测试并通过：
  `HF_HOME="$PWD/data/hf" HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider`
- service 层：不写 SQL、不接收 `Request`、抛 `ServiceError(status, detail)`；router 层可抛 `HTTPException`。
- 跨域只 import 对方 service/schemas；reader↔agent 的循环用**函数内局部导入**。
- 被测试 monkeypatch 的模块属性（`client`、`create_run`、`os` 等）必须保持"调用时经模块属性解析"（`module.fn()` 而非 `from module import fn` 后直接调用）。
- 搬移后 `grep -rn "<旧路径>" app/ tests/ agent_runner/ scripts/` 必须无残留（legacy 内部引用除外）。
- 永不 `git add` `ops/public-access-credentials.txt`、`ops/tunnel.log`、`ops/tunnel.sh`；按文件清单 add。
- 在独立 worktree/分支执行（superpowers:using-git-worktrees）；`.venv` 与 `data/hf` 用主仓库绝对路径。

## Review Focus

1. **错误响应形状漂移**：`ServiceError` 处理器必须输出与 `HTTPException` 完全一致的 `{"detail": ...}` 与状态码 → Task 1 新增测试钉住。
2. **monkeypatch 失效**：搬移后调用点若用 `from x import fn` 绑定旧名字，测试替身静默失效 → 每个任务全套测试 + Task 3/5 显式检查调用方式。
3. **迁移目录丢失**：`core/db.py` 的 `MIGRATIONS_DIR` 必须仍指向 `app/migrations/` → Task 1 测试断言新库迁移全部应用。
4. **Runner import 断裂**：`agent_runner` 引用 `app.agent_catalog`/`app.reader_store`/`app.config` → Task 1/2/3 同步更新，test_agent_mvp/test_workbench 覆盖。
5. **附件权限/属主回归**：root 运行时 chown 到数据目录属主的逻辑搬入 storage 后不得丢失 → Task 5 保留并retarget test_workbench 的 os patch 测试。

---

### Task 1: core — 配置、数据库、错误基建

**Files:**
- Create: `app/core/__init__.py`、`app/core/config.py`（自 `app/config.py` 搬移）、`app/core/db.py`（自 `app/db.py` 搬移）、`app/core/errors.py`
- Modify: `app/main.py`（import 路径 + 注册错误处理器）、全部引用 `app.config`/`app.db` 的 app/tests/agent_runner/scripts 文件
- Delete: `app/config.py`、`app/db.py`
- Test: `tests/test_core_errors.py`（新建）

**Interfaces:**
- Produces: `app.core.config.Settings`（签名不变）；`app.core.db.get_conn(settings: Settings | None = None) -> sqlite3.Connection`；`app.core.errors.ServiceError(status: int, detail: str)`（属性 `.status`、`.detail`）；`app.core.errors.register_error_handlers(app: FastAPI) -> None`
- Consumes: 无

- [ ] **Step 1: 写失败测试**

`tests/test_core_errors.py::test_service_error_response_matches_http_exception`：用 `api_client` 建 app 后 `app.add_api_route` 两条临时路由，分别抛 `ServiceError(409, '冲突文案')` 与 `HTTPException(409, '冲突文案')`，断言两者 `status_code` 与 `json()` 完全相等。另写 `test_migrations_dir_resolves`：`from app.core.db import MIGRATIONS_DIR; assert MIGRATIONS_DIR.is_dir() and len(list(MIGRATIONS_DIR.glob('*.sql'))) >= 7`；`test_fresh_db_applies_all_migrations(tmp_path)`：`get_conn(Settings(data_dir=tmp_path, qdrant_url='unused'))` 后 `schema_migrations` 行数等于迁移文件数。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_core_errors.py -q`
Expected: FAIL（`app.core` 不存在）

- [ ] **Step 3: 搬移并实现**

`app/config.py` → `app/core/config.py`、`app/db.py` → `app/core/db.py`（内容不变；`core/db.py` 的 `MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"`）。新建 `app/core/errors.py`：

```python
class ServiceError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail

def register_error_handlers(app):
    from fastapi.responses import JSONResponse
    @app.exception_handler(ServiceError)
    async def _handle(request, exc):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)
```

`app/main.py`：import 改为 `from .core.config import Settings`、`from .core.db import get_conn`，`create_app()` 内调用 `register_error_handlers(app)`。grep 更新全部 `app.config`/`app.db` 引用（含 `agent_runner/tools.py` 的 `from app.config import Settings`、conftest、各测试）。删除旧文件。

- [ ] **Step 4: 运行测试**

Run: `.venv/bin/python -m pytest tests/test_core_errors.py tests/test_db_migrations.py -q` 然后全套（Global Constraints 命令）
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/core app/main.py tests/test_core_errors.py <其余被更新文件清单>
git commit -m "refactor: extract core config/db/errors with ServiceError"
```

---

### Task 2: sessions 域

**Files:**
- Create: `app/sessions/{__init__,router,schemas,service,repository}.py`（自 `app/api/sessions.py` 拆分）
- Modify: `app/main.py`、`app/api/agent.py`、`app/api/reader.py`、`app/api/workbench.py`、`app/api/imports_v2.py`（对 sessions 的引用）、`tests/test_task_sessions.py`、`tests/test_agent_mvp.py`
- Delete: `app/api/sessions.py`

**Interfaces:**
- Produces: `app.sessions.service.require_session(db, session_id: int) -> sqlite3.Row`；`session_view(db, row) -> dict`；`create_session(db, body: SessionCreate) -> dict`（返回 `{'session': ..., 'starting_prompt': ...}`）；`list_sessions(db, *, q, kind, paper_id, category_id, archived, limit) -> dict`；`app.sessions.schemas.SessionCreate/SessionPatch/TemplateCreate/Name`
- Consumes: `app.core.errors.ServiceError`；`app.agent_catalog.SKILLS/KINDS`（暂用旧路径，Task 3 更新）

- [ ] **Step 1: 基线**

Run: `.venv/bin/python -m pytest tests/test_task_sessions.py tests/test_agent_mvp.py -q`
Expected: PASS（记录数量）

- [ ] **Step 2: 拆分实现**

schemas.py 放 4 个 Pydantic 模型（原样）。repository.py 收纳全部 SQL（会话/模板/分类的查、插、改，函数名按操作命名，如 `find_session(db, ident)`、`insert_session(db, fields) -> int`、`list_templates(db)`）。service.py 搬业务规则（校验、事务、`require_session`/`session_view`/`create_session`），`HTTPException` 全部改 `ServiceError`（状态码与文案逐字保留）。router.py 只做参数绑定 + 调 service，prefix `/api/sessions` 不变。`session_runs` 路由中对 `agent.view` 的引用保持函数内局部导入。更新 main.py 与所有跨模块引用、测试 import。删除旧文件。

- [ ] **Step 3: 运行测试**

Run: 基线两文件 + 全套
Expected: PASS，数量与基线一致

- [ ] **Step 4: Commit**

```bash
git add app/sessions app/main.py <引用更新清单>
git commit -m "refactor: sessions domain with router/service/repository"
```

---

### Task 3: reader 域（含 pages 与选区校验）

**Files:**
- Create: `app/reader/{__init__,router,schemas,service,repository}.py`、`app/reader/pages.py`（自 `app/reader_store.py` 搬移）
- Modify: `app/main.py`、`app/api/agent.py`（Context/validate_context 引用）、`app/api/workbench.py`（linked/Context）、`agent_runner/tools.py`（`from app.reader_store import read_page` → `from app.reader.pages import read_page`）、`tests/test_reader.py`、`tests/test_reader_imports.py`、`tests/test_workbench.py`
- Delete: `app/api/reader.py`、`app/reader_store.py`

**Interfaces:**
- Produces: `app.reader.schemas.Context/Annotation/AnnotationPatch/Position/Translation/TranslationVisibility`（原样）；`app.reader.service.linked(db, sid: int, pid: int) -> None`、`paper(db, ident) -> Row`、`annotation_view(row) -> dict`；`app.reader.pages.document_info(settings, row) -> dict`、`pdf_file(settings, row) -> tuple[Path, str]`、`read_page(settings, row, page: int) -> dict`、`validate_context(settings, db, ctx: dict, conversation_id) -> dict`（签名均不变）
- Consumes: `app.sessions.service.require_session`；`app.api.agent.RunCreate/create_run`（translate 路由内**函数内局部导入**，Task 4 改指新路径）

- [ ] **Step 1: 基线**

Run: `.venv/bin/python -m pytest tests/test_reader.py tests/test_reader_imports.py tests/test_workbench.py -q`
Expected: PASS

- [ ] **Step 2: 拆分实现**

pages.py 整体搬移 reader_store（纯函数，不改逻辑）。schemas/service/repository/router 按 Task 2 同样规则拆分 api/reader.py；translate 的 create_run 调用保持函数内局部导入且经模块属性调用。更新全部引用（含 agent_runner/tools.py）。删除旧文件。

- [ ] **Step 3: 运行测试**

Run: 基线三文件 + 全套
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/reader app/main.py agent_runner/tools.py <引用更新清单>
git commit -m "refactor: reader domain, pages module and selection validation"
```

---

### Task 4: agent 域（catalog、runner 客户端、运行编排）

**Files:**
- Create: `app/agent/{__init__,router,schemas,service,repository}.py`、`app/agent/catalog.py`（自 `app/agent_catalog.py`）、`app/agent/runner_client.py`
- Modify: `app/main.py`、`app/reader/service.py`（translate 局部导入改指 `app.agent.service`/`app.agent.schemas`）、`app/sessions/service.py` 与 `app/sessions/router.py`（`app.agent_catalog` → `app.agent.catalog`）、`app/api/workbench.py`、`app/api/imports_v2.py`、`agent_runner/server.py`（`from app.agent_catalog import SKILLS` → `from app.agent.catalog import SKILLS`）、`tests/test_agent_mvp.py`、`tests/test_task_sessions.py`、`tests/test_reader_imports.py`
- Delete: `app/api/agent.py`、`app/agent_catalog.py`

**Interfaces:**
- Produces: `app.agent.catalog.SKILLS/TEMPLATES/KINDS`；`app.agent.runner_client.client() -> httpx.AsyncClient`；`app.agent.schemas.RunCreate`；`app.agent.service.view(row) -> dict`、`create_run(body: RunCreate, state) -> dict`、`execute_run(run_id: str, state) -> None`、`init_agent_state(app)`、`close_agent_state(app)`
- Consumes: `app.sessions.service.require_session`；`app.reader.schemas.Context`；`app.reader.pages.validate_context`；`app.api.workbench.image_rows`（函数内局部导入，Task 6 改指新路径）

**注意**：`create_run` 签名由 `(body, request)` 改为 `(body, state)`（state = `request.app.state`）。三个调用方（reader translate、imports start_import、workbench fire_schedule）传 `request.app.state`。测试替身 `full(*a, **kw)` 不受影响。`execute_run` 内调用 `runner_client.client()` 必须经模块属性（测试 patch `app.agent.runner_client.client`）。

- [ ] **Step 1: 基线**

Run: `.venv/bin/python -m pytest tests/test_agent_mvp.py tests/test_task_sessions.py tests/test_reader_imports.py -q`
Expected: PASS

- [ ] **Step 2: 拆分实现**

catalog.py 原样搬移。runner_client.py 只含 `client()` 与 `SOCKET_DEFAULT`。repository.py 收纳 agent_runs/conversations 相关 SQL。service.py 搬 `view/init_agent_state/close_agent_state/create_run/execute_run` 及校验规则（HTTPException→ServiceError）。router.py 保留 `/api/agent` 全部路由。测试 patch 目标更新：`agent.client` → `app.agent.runner_client.client`；`agent.create_run` → `app.agent.service.create_run`。更新全部引用，删除旧文件。

- [ ] **Step 3: 运行测试**

Run: 基线三文件 + 全套
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/agent app/main.py agent_runner/server.py app/reader/service.py <引用更新清单>
git commit -m "refactor: agent domain with catalog, runner client and run orchestration"
```

---

### Task 5: storage — 文件落盘与图片校验

**Files:**
- Create: `app/storage/{__init__,files}.py`
- Modify: `tests/test_workbench.py`（os patch 目标，Task 6 才改调用方；本任务先建模块与测试）
- Test: `tests/test_storage_files.py`（新建）

**Interfaces:**
- Produces: `app.storage.files.image_header(data: bytes) -> tuple[str, int, int]`（mime/宽/高，校验逻辑自 api/workbench.py 原样搬移）；`save_attachment(settings, ident: str, data: bytes) -> Path`（写 `data/attachments/<ident>`，chmod 600，root 时 chown 到 data_dir 属主，目录 700）；`attachment_path(settings, ident: str) -> Path`
- Consumes: `app.core.config.Settings`

- [ ] **Step 1: 写失败测试**

`tests/test_storage_files.py`：PNG 头解析返回 `('image/png', w, h)`；超尺寸/非 PNG/JPEG 抛 `ValueError`（文案逐字沿用）；`save_attachment` 后文件存在、mode 0o600、目录 0o700；monkeypatch `app.storage.files.os.geteuid` 为 0、`os.chown` 记录调用，断言 chown 目标为 data_dir 属主（复刻 test_workbench.py:98-99 的断言）。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_storage_files.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

自 `app/api/workbench.py` 搬 `image_header` 与 upload_image 中的落盘/权限段为 `save_attachment`；`attachment_path` 返回路径。逻辑逐字保留（含 JPEG SOF 解析）。

- [ ] **Step 4: 运行测试**

Run: `.venv/bin/python -m pytest tests/test_storage_files.py -q` + 全套
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/storage tests/test_storage_files.py
git commit -m "refactor: storage module for attachment files and image validation"
```

---

### Task 6: workbench 域（工作区、草稿、图片接口）

**Files:**
- Create: `app/workbench/{__init__,router,schemas,service,repository}.py`
- Modify: `app/main.py`、`app/agent/service.py`（image_rows 局部导入改 `from app.workbench.service import image_rows`）、`tests/test_workbench.py`
- Delete: `app/api/workbench.py` 中工作区/草稿/图片部分（schedules 部分留待 Task 7；若同文件不便拆分，本任务把 schedules 段暂留为 `app/api/workbench.py` 残余并在 Task 7 删除）

**Interfaces:**
- Produces: `app.workbench.service.image_rows(db, ids: list[str], sid: int, paper_id: int | None = None) -> list[Row]`、`attachment_view(row) -> dict`；`app.workbench.schemas.Tab/Layout/Workspace/Draft`
- Consumes: `app.storage.files.*`；`app.reader.service.linked`；`app.reader.schemas.Context`；`app.sessions.service.require_session`

- [ ] **Step 1: 基线**

Run: `.venv/bin/python -m pytest tests/test_workbench.py -q`
Expected: PASS

- [ ] **Step 2: 拆分实现**

upload_image 路由改为调 `storage.files.image_header` + `save_attachment`（pymupdf 解码校验留在 service）；get_image 用 `attachment_path`。工作区/草稿/repository 按同规则拆分。test_workbench 的 `workbench.os` patch 改指 `app.storage.files.os`。更新 agent/service.py 局部导入。

- [ ] **Step 3: 运行测试**

Run: tests/test_workbench.py + 全套
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/workbench app/main.py app/agent/service.py tests/test_workbench.py <清单>
git commit -m "refactor: workbench domain backed by storage module"
```

---

### Task 7: schedules 域

**Files:**
- Create: `app/schedules/{__init__,router,schemas,service,repository}.py`
- Modify: `app/main.py`（`workbench.schedule_loop` → `schedules.service.schedule_loop`）、`tests/test_workbench.py`（定时任务相关用例 import）
- Delete: `app/api/workbench.py`（残余 schedules 段）

**Interfaces:**
- Produces: `app.schedules.service.fire_schedule(ident: int, db, state) -> dict`、`schedule_loop(app) -> None`、`next_time(hours: int) -> str`；`app.schedules.schemas.Schedule/Enable`
- Consumes: `app.agent.service.create_run`（函数内局部导入）、`app.agent.schemas.RunCreate`、`app.sessions.service.require_session`

- [ ] **Step 1: 基线**

Run: `.venv/bin/python -m pytest tests/test_workbench.py -q`
Expected: PASS

- [ ] **Step 2: 拆分实现**

schedules 段自 workbench 搬出；`fire_schedule` 签名 `(ident, request)` → `(ident, db, state)`，router 与 schedule_loop 调用点同步（loop 内用 `app.state.db` 与 `app.state`）。"提交前推进 next_at"逻辑逐字保留。

- [ ] **Step 3: 运行测试**

Run: tests/test_workbench.py + 全套
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/schedules app/main.py tests/test_workbench.py
git commit -m "refactor: schedules domain split from workbench"
```

---

### Task 8: papers 域（论文卡片与分类）

**Files:**
- Create: `app/papers/{__init__,router,schemas,service,repository}.py`、`app/papers/assets.py`（自 `app/library_assets.py`）
- Modify: `app/main.py`、`tests/test_agent_mvp.py`（library import）、其他引用 `app.library_assets`/`app.api.library` 处
- Delete: `app/api/library.py`、`app/library_assets.py`

**Interfaces:**
- Produces: `app.papers.service.require_paper(db, paper_id) -> Row`、`card(db, row) -> dict`；`app.papers.assets.preview_path(settings, pdf_path)`、`affiliation_candidates(settings, pdf_path)`（签名不变）；`app.papers.schemas.CollectionCreate/PaperPatch`
- Consumes: `app.core.errors.ServiceError`

- [ ] **Step 1: 基线**

Run: `.venv/bin/python -m pytest tests/test_agent_mvp.py tests/test_api_papers.py -q`
Expected: PASS

- [ ] **Step 2: 拆分实现**

按同规则拆分 api/library.py；assets.py 原样搬移 library_assets。`metadata_version` 乐观锁、affiliation_source/summary_source 规则逐字保留。

- [ ] **Step 3: 运行测试**

Run: 基线两文件 + 全套
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/papers app/main.py <引用更新清单>
git commit -m "refactor: papers domain with cards, collections and assets"
```

---

### Task 9: imports 域

**Files:**
- Create: `app/imports/{__init__,router,schemas,service,repository}.py`、`app/imports/sources.py`（自 `app/paper_sources.py`）、`app/imports/pipeline.py`（自 `app/import_service.py`）
- Modify: `app/main.py`、`tests/test_reader_imports.py`、其他引用处
- Delete: `app/api/imports_v2.py`、`app/paper_sources.py`、`app/import_service.py`

**Interfaces:**
- Produces: `app.imports.pipeline.process_import(row, db, settings, embedder, store) -> dict`（不变）；`app.imports.sources.normalize_doi/public_url/fetch_pdf/parse_arxiv_html/MAX_PDF_BYTES`（不变）；`app.imports.service.start_import(ident, db, state) -> dict`、`import_view(row) -> dict`、`validate_targets(db, collection_id, target)`；router 含 `/api/imports` 与 `/api/internal` 两个 APIRouter
- Consumes: `app.sessions.service.create_session`、`app.sessions.schemas.SessionCreate`、`app.agent.service.create_run`（函数内局部导入）、`app.ingest.metadata.extract_arxiv_id`

- [ ] **Step 1: 基线**

Run: `.venv/bin/python -m pytest tests/test_reader_imports.py tests/test_api_import.py -q`
Expected: PASS

- [ ] **Step 2: 拆分实现**

sources/pipeline 原样搬移（测试 patch `import_service.doi_metadata` 等改指 `app.imports.pipeline.*`；`paper_sources.public_url` 改指 `app.imports.sources.public_url`）。internal execute 路由的令牌校验、绑定校验、80s 超时逐字保留。`start_import` 签名 `(ident, request)` → `(ident, db, state)`。

- [ ] **Step 3: 运行测试**

Run: 基线两文件 + 全套
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/imports app/main.py tests/test_reader_imports.py <清单>
git commit -m "refactor: imports domain with sources, pipeline and internal execute"
```

---

### Task 10: legacy 隔离

**Files:**
- Create: `app/legacy/__init__.py`、`app/legacy/gateway.py`（自 `app/llm/gateway.py`）、`app/legacy/study/`（自 `app/study/`）、`app/legacy/errors.py`（自 `app/api/__init__.py` 的映射助手）、`app/legacy/api_papers.py`、`app/legacy/api_notes.py`、`app/legacy/api_qa.py`、`app/legacy/api_study.py`、`app/legacy/api_import.py`（自对应旧路由）
- Modify: `app/main.py`、`app/ingest/metadata.py` 等对 gateway 的引用、`tests/test_llm_gateway.py`、`tests/test_api_qa.py`、`tests/test_api_study.py`、`tests/test_api_notes.py`、`tests/test_api_papers.py`、`tests/test_compare.py`、`tests/conftest.py`
- Delete: `app/llm/`、`app/study/`、`app/api/`（整包）

**Interfaces:**
- Produces: `app.legacy.gateway.LLMGateway/LLMExhaustedError/LLMHTTPStatusError`；`app.legacy.errors.KNOWN_INGEST_ERRORS/KNOWN_STUDY_ERRORS/ingest_http_error/study_http_error/require_rag_stack`；各旧 router（路径不变）
- Consumes: `app.core.*`、`app.rag.*`、`app.ingest.*`

- [ ] **Step 1: 基线**

Run: `.venv/bin/python -m pytest tests/test_llm_gateway.py tests/test_api_qa.py tests/test_api_study.py tests/test_api_notes.py tests/test_api_papers.py tests/test_compare.py -q`
Expected: PASS

- [ ] **Step 2: 搬移实现**

旧路由与 gateway/study 整体搬入 legacy（内部逻辑不改，仅 import 路径与包内相对引用更新）。`app/api/__init__.py` 助手 → legacy/errors.py。字符串 patch `"app.api.papers.ingest_arxiv"` → `"app.legacy.api_papers.ingest_arxiv"`。conftest 的 `main.LLMGateway` patch 不变（main 仍 import 该名）。`app/ingest/` 对 gateway 的引用改指 legacy（过渡依赖，计划三消除）。删除 `app/api/`、`app/llm/`、`app/study/`。

- [ ] **Step 3: 运行测试**

Run: 基线六文件 + 全套
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/legacy app/main.py app/ingest tests/ <清单>
git commit -m "refactor: isolate legacy gateway/study/routers pending retirement"
```

---

### Task 11: 收尾 — 结构核验、文档、全量回归

**Files:**
- Modify: `app/main.py`（最终 import 清理）、`架构.md`（§2/§4 结构描述更新为新域结构）、`enviroment.md`（入口路径更新）
- Test: 全套 + `scripts/smoke_test.py`（服务运行时）

- [ ] **Step 1: 结构核验**

Run: `grep -rn "app\.api\|app\.config\b\|app\.db\b\|app\.reader_store\|app\.agent_catalog\|app\.library_assets\|app\.paper_sources\|app\.import_service\|app\.llm\|app\.study" app/ tests/ agent_runner/ scripts/`
Expected: 无结果（文档除外）。`find app -name "*.py" | xargs grep -l "db.execute\|db.executemany"` 的结果只允许出现在各域 repository.py、core/db.py、legacy/、ingest/、rag/ 与 agent/service.py 的启动清理（若 Task 4 未下沉则本步下沉到 repository）。

- [ ] **Step 2: 全套回归**

Run: Global Constraints 全套命令
Expected: PASS，记录准确数量（此前记录为 182+，以实际为准）

- [ ] **Step 3: 冒烟（若服务在运行）**

Run: `.venv/bin/python scripts/smoke_test.py`
Expected: 退出码 0

- [ ] **Step 4: 更新文档并提交**

架构.md 增补新目录结构与三层规则；enviroment.md 更新模块入口。

```bash
git add app/main.py 架构.md enviroment.md
git commit -m "refactor: finalize domain structure, verify regression and update docs"
```