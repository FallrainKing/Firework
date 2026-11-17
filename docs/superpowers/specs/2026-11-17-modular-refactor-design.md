# 模块化重构设计（前后端解耦 + 功能域后端 + 统一 Claude 执行 + 新前端）

日期：2026-11-17。状态：已与用户逐项确认方向；标注"我的决定"的条目由实现者负责，用户可否决。

## 1. 意图与动机

用户痛点：架构不清晰，后续加功能、做扩展不容易。目标是**模块化和组件化**：
后端按功能域分层、边界明确；前端组件化、可独立演进；界面风格现代化。

## 2. 已确认的决定（用户原话归纳）

1. 前端走**框架 + 构建链**路线（放弃"免构建原生 JS"旧约束）。
2. 后端按功能域划分：数据库、数据/文件存储、runner、用户配置等各自成模块。
3. **所有 LLM 问答统一走服务器已有 Claude（Runner 链路）**，退役直连 LLM Gateway 的旧路径；
   bge-m3 + Qdrant 保留，降级为检索工具的数据源。
4. 旧 `/legacy.html` 页面退役，其能力（问答、精读、比较）由新工作台会话模板覆盖。
5. Claude 执行**不再受 120 秒硬超时**：后台任务 + 实时进度 + 可取消 + 排队。
6. 保持现有前端布局；**增加主题功能，先做白色简约风格**。

## 3. 我的决定（实现者选择，可否决）

- 前端框架：**Vue 3 + Vite + TypeScript + Pinia + vue-router**。单文件组件贴近现有 HTML 结构，迁移对照容易。
- 后端服务层错误用 `core/errors.py::ServiceError(status, detail)`，应用级异常处理器输出与 FastAPI `HTTPException` 完全一致的 `{"detail": ...}`，保证现有测试与前端行为不变。
- Runner 默认并发 **2**（`RESEARCH_AGENT_CONCURRENCY` 可配），排队而非 429 拒绝。
- 阅读/比较/审查类 Skill 放宽护栏：回合数、输出 token 按 Skill 配置；**无硬超时**，保留费用上限作失控护栏。
- `app/rag/`、`app/ingest/`、`app/migrations/` 本轮保持原路径（已是内聚子系统，测试依赖面大）。
- 导入管线中的 LLM 元数据抽取（`ingest/metadata.py` 依赖 Gateway）改为确定性来源：
  arXiv 水印/meta 标签、PDF 内嵌元数据、文件名回退；不再调用 LLM。
- 旧 notes/qa/study/papers-v1/import-v1 路由随 legacy 退役（数据库数据保留，不删表）。
- 主题用 CSS 变量 design tokens 实现，浅色（白色简约）为默认，预留深色主题位；主题选择存 localStorage。
- 分五个计划顺序交付，每个计划独立可测试、可发布。

## 4. 目标与非目标

**目标**
- 后端每个功能域 router（HTTP）→ service（业务）→ repository（SQL）三层；跨域只走 service。
- 前端独立工程（`frontend/`），构建产物由 FastAPI 托管；API 纯 JSON。
- 所有模型调用经 Runner；长任务后台执行、进度可见、可取消。
- 现有 API 路径、数据库结构、用户数据在重构中保持兼容；测试套件持续通过。

**非目标**：多用户认证、跨设备同步、多副本调度（P3 另行立项）；OCR、知识抽取等新研究能力。

**反目标**：重构期间改变现有接口行为；丢失会话/草稿/附件数据；把密钥写进仓库；
为重构引入永久兼容 shim 层。

## 5. 后端目标结构（计划一交付）

```
app/
  core/        config.py（环境配置）db.py（连接+迁移）errors.py（ServiceError+处理器）
  storage/     files.py（附件/上传暂存的落盘、权限、属主、图片头校验）
  papers/      router/schemas/service/repository + assets.py（预览图、单位候选）
  sessions/    router/schemas/service/repository（会话、模板、分类）
  reader/      router/schemas/service/repository + pages.py（文档信息、物理页文本、选区校验）
  imports/     router/schemas/service/repository + sources.py（来源解析）pipeline.py（入库执行）
  agent/       router/schemas/service/repository + catalog.py（Skill 注册表）runner_client.py（socket 客户端）
  schedules/   router/schemas/service/repository（定时任务与调度循环）
  workbench/   router/schemas/service/repository（工作区、草稿、最近阅读、图片接口）
  legacy/      gateway.py、study/、旧 papers/notes/qa/study/import-v1 路由（计划三移除）
  rag/ ingest/ migrations/（保持原样）
  main.py
```

规则：
- router 只做参数校验与调用 service；service 不写 SQL、不接收 `Request`；repository 只写 SQL。
- service 抛 `ServiceError`；router 可抛 `HTTPException`。
- 跨域循环依赖（reader↔agent）用函数内局部导入化解。
- 测试 monkeypatch 的模块属性（`client`、`create_run`、`os` 等）搬移后仍须通过模块属性在调用时解析。

## 6. 执行模型（计划二交付）

- Runner 新协议：`POST /runs` 提交即返回；`GET /runs/{id}` 查状态；
  `GET /runs/{id}/events` SSE 进度（CLI stream-json 的 tool_use/文本增量）；`POST /runs/{id}/cancel` 取消。
- Runner 内部队列 + 并发 2；取消终止进程组并保留已产生用量。
- 护栏按 Skill 配置（catalog 增加 `max_turns`/`max_output_tokens`/`timeout_s`/`max_budget_usd`）：
  chat 类沿用 6 回合/1024 token/120s；paper_read/review/compare 放宽（如 30 回合/8192 token/无硬超时）。
- app 侧 `agent_runs` 增加进度字段与 `cancelled` 状态（迁移 0008）；重启中断标记失败、不自动重放；幂等键沿用。
- 前端会话内展示排队/运行/进度/取消；旧同步接口在新前端切换后移除。

## 7. LLM 统一（计划三交付）

- 移除 `legacy/gateway.py`、study 引擎与旧路由；`/legacy.html` 退役。
- 能力映射：论文库问答→`search_library`；精读→`paper_read`（强化 SKILL.md 提示词）；比较→`paper_compare`。
- `ingest/metadata.py` 去 LLM 化（见 §3）；`Settings.llm_providers` 等 Gateway 配置废弃。
- RAG 栈仅作为 `library_search` 等工具的数据源保留。

## 8. 前端（计划四、五交付）

- `frontend/`：Vue 3 + Vite + TS；目录按功能域（workbench/reader/library/sessions/agent/schedules/shared）。
- 布局不变：顶部四模块、左侧导航、多论文标签、三栏阅读（PDF.js 沿用内置 vendor 副本）。
- 主题：`shared/theme` tokens（CSS 变量），默认白色简约——白底、中性灰层次、单一强调色、
  细边框、充足留白、系统字体栈；深色主题预留。
- 状态：Pinia stores 对应后端域；API 层统一封装（fetch + 类型化客户端）。
- 构建与部署：Docker 多阶段（node 构建 → FastAPI 托管 dist）；开发用 Vite proxy 指向 8600。
- 计划四：工程骨架 + 主题系统 + 首页/标签/任务窗口；计划五：阅读页/管理/发现页 + legacy 退役 + 部署切换。

## 9. 约束

- 单 Web worker、单 Runner 部署不变；数据目录布局不变。
- 每个计划结束时全套测试通过；部署前备份（沿用 ops/backup.sh 与快照惯例）。
- `ops/public-access-credentials.txt`、`ops/tunnel.*` 永不提交。
- 真实模型验证用最小材料、短输出，控制用量。

## 9.1 计划一遗留债务（计划二前置）

- 跨域只读 JOIN 仍留在部分 repository（sessions/reader→agent_runs，agent→papers/conversations/import_requests，schedules→conversations/papers，workbench→papers）。计划二改动 `agent_runs` 结构前，把这些读取收敛到属主域 service。
- imports/schedules service 仍 import `fastapi.HTTPException` 用于捕获过渡期错误，计划二/三移除。
- workbench.service 自带 `repo.paper_exists`，与 papers.service.paper_exists 不一致，顺手对齐。
- 部署后须补跑 `scripts/smoke_test.py`（计划一在 worktree 执行，未对运行镜像冒烟）。

## 10. 计划路线

1. `2026-11-17-backend-domain-refactor.md` — 后端功能域三层重组（纯重构，行为不变）。
2. 计划二：Runner 异步执行模型 + app 运行编排 + SSE。
3. 计划三：LLM 统一到 Claude，legacy 退役。
4. 计划四：Vue 前端骨架 + 主题 + 工作台。
5. 计划五：阅读/管理/发现页迁移 + 部署切换 + 最终回归。