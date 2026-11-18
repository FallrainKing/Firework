# Vue 工作台与主题系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Vue 3 前端工程与白色简约主题系统，把首页工作台（导航/标签/任务窗口/比较/定时任务）迁移为组件化实现，并提供智能体运行的实时进度与取消 UI；旧界面原样保留，新界面挂 `/v2/`  additive 交付。

**Architecture:** `frontend/` 独立 Vite + Vue 3 + TS + Pinia 工程，按功能域组织（api/stores/components/views/shared）。开发用 Vite proxy 指向 8600；构建产物由 FastAPI 新增 `/v2` 静态挂载托管（计划五切换根路径）。阅读页/管理/发现页本计划仍以 iframe 嵌入现有页面（计划五 Vue 化），postMessage 保存协议沿用。主题用 CSS 变量 tokens，浅色默认、深色预留。

**Tech Stack:** Vue 3.5+、Vite 7+、TypeScript 5+、Pinia 3+、vue-router 4、Vitest 3+、@vue/test-utils 2+、jsdom。Node v24（服务器已装），npm registry 可达。

**Spec:** `docs/superpowers/specs/2026-11-17-modular-refactor-design.md`（§8 前端、§6 执行模型 UI）

## Global Constraints

- 布局与现有工作台一致：顶部四模块（读论文/论文比较/定时任务/论文库管理）、左侧导航（新建阅读/搜索导入/最近阅读/论文领域）、多论文标签、欢迎起始页。
- 主题 tokens（浅色默认）：`--bg:#ffffff; --surface:#fafafa; --border:#e5e7eb; --text:#111827; --text-muted:#6b7280; --accent:#2563eb; --accent-soft:#eff6ff; --danger:#dc2626; --radius:8px`；间距 4/8/12/16/24/32；系统字体栈；深色主题仅预留 token 占位与切换接口，不做完整深色设计。
- 所有 API 调用经 `src/api/` 类型化客户端；错误取响应 `detail` 字段展示；不直接 fetch 散落在组件里。
- 工作区持久化沿用 `GET/PUT /api/workbench/states/{32hex}`（浏览器 localStorage 存 workspace id，键 `research-workspace-id`，与旧版共用同一工作区数据）。
- 标签上限 20、已加载阅读 iframe 上限 3；释放前经 postMessage 请求保存（协议见 Task 6）。
- 旧前端文件与路由本计划**不删除不修改**（manage.html/discover.html/reader.html 原样被 iframe 复用）；main.py 仅新增 /v2 挂载。
- 后端测试全套保持通过：`HF_HOME="$PWD/data/hf" HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider`（基线 159）。
- 前端测试：`cd frontend && npx vitest run`；每个任务结束前端测试 + 构建（`npx vite build`）通过。
- 独立 worktree 执行；`ops/` 敏感文件永不提交；`frontend/node_modules/`、`frontend/dist/` 入 .gitignore。
- 真实模型验证最小化：进度/取消 UI 用 chat 最小提问验证一次即可。

## Review Focus

1. **工作区数据兼容**：Vue 版与旧版共用同一 workspace id 与 state_json 形状（tabs/layout/active_paper_id/view），互相切换不丢标签/布局（store 测试 + 手动对照）。
2. **iframe 保存协议**：释放阅读视图前 postMessage 请求保存草稿/位置，来源与窗口校验沿用 bridge 协议；丢消息时不静默丢草稿（协议测试）。
3. **SSE 断线重连**：进度流断开后回退轮询 GET run，终态（succeeded/failed/cancelled）必达，取消按钮终态后消失（activity 测试）。
4. **任务窗口就地新增**：新增分类/模板/领域后保留窗口已填内容并选中新项（dialog 测试，对照旧版行为）。
5. **慢网络防重复**：创建会话/提交运行按钮在请求期间禁用，request_key 幂等沿用（api/store 测试）。

---

### Task 1: 工程脚手架 + 主题系统

**Files:**
- Create: `frontend/package.json`、`vite.config.ts`、`tsconfig.json`、`index.html`、`src/main.ts`、`src/App.vue`、`src/router.ts`、`src/shared/theme/tokens.css`、`src/shared/theme/store.ts`、`src/shared/ui/`（Toast.vue、Modal.vue、Button.vue 基础件）、`.gitignore` 追加
- Test: `frontend/src/shared/theme/store.test.ts`

**Interfaces:**
- Produces: `useThemeStore()`：`{ mode: 'light'|'dark', setMode(m), toggle() }`，localStorage 键 `research-theme`，默认 light，应用方式 `document.documentElement.dataset.theme = mode`；tokens.css 定义 `:root` 与 `[data-theme="dark"]` 占位变量；Vite proxy `/api`→`http://127.0.0.1:8600`；build outDir `dist`，base `/v2/`
- Consumes: 无

- [ ] **Step 1: 脚手架**

`npm create vite@latest frontend -- --template vue-ts` 非交互落地（或手写等价文件），安装 pinia/vue-router/vitest/@vue/test-utils/jsdom。vite.config：base '/v2/'、server.proxy、test 环境 jsdom。App.vue 挂 router-view + Toast 容器 + data-theme 初始化。

- [ ] **Step 2: 写失败测试**

store.test.ts：默认 mode==='light'；setMode('dark') 后 documentElement.dataset.theme==='dark' 且 localStorage 写入；新 store 实例从 localStorage 恢复。

- [ ] **Step 3: RED → 实现 → GREEN**

Run: `cd frontend && npx vitest run` 先 FAIL 后 PASS；`npx vite build` 成功。

- [ ] **Step 4: Commit**

```bash
git add frontend/ .gitignore
git commit -m "feat: vue frontend scaffold with white-minimal theme system"
```

---

### Task 2: 类型化 API 客户端

**Files:**
- Create: `frontend/src/api/client.ts`、`types.ts`、`sessions.ts`、`papers.ts`、`agent.ts`、`workbench.ts`、`schedules.ts`、`imports.ts`
- Test: `frontend/src/api/client.test.ts`、`agent.test.ts`

**Interfaces:**
- Produces: `api<T>(path, {method, body, form}): Promise<T>`（fetch 封装，!ok 时 throw Error(detail)）；类型 `Session/SessionCreate/Template/Category/Paper/Card/Collection/Run/RunCreate/WorkspaceState/Draft/Schedule/ImportRequest`（字段对照后端 schema）；`agentApi.createRun(body: RunCreate): Promise<Run>`（request_key 缺省 crypto.randomUUID hex）、`listRuns(conversationId?)`、`getRun(id)`、`cancelRun(id)`、`runEventsUrl(id)`；`workbenchApi.getState(id)/saveState(id, s)`；`sessionsApi.list/create/get/update/templates/createTemplate/categories/createCategory/sessionRuns`；`papersApi.list/get/collections/createCollection/patch`；`schedulesApi.list/create/enable/run`
- Consumes: Task 1 工程

- [ ] **Step 1: 写失败测试**

client.test：mock fetch 返回 {detail:'冲突'} 409 → throw Error('冲突')；form 上传不设 Content-Type。agent.test：createRun 自动生成 32hex request_key；cancelRun POST 正确路径。

- [ ] **Step 2: RED → 实现 → GREEN**

Run: `npx vitest run`；`npx vue-tsc --noEmit` 类型检查通过。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/
git commit -m "feat: typed api client for all backend domains"
```

---

### Task 3: 工作区 store（标签/布局/持久化）

**Files:**
- Create: `frontend/src/stores/workbench.ts`、`frontend/src/stores/library.ts`
- Test: `frontend/src/stores/workbench.test.ts`

**Interfaces:**
- Produces: `useWorkbenchStore()`：state `{ workspaceId, tabs: Tab[], activePaperId, view: 'read'|'compare'|'schedules'|'library', layout }`；actions `load()`（GET state，缺失用默认）、`openPaper(paperId, sessionId?)`（复用已有标签否则新增，≤20）、`closeTab(paperId)`、`activate(paperId)`、`setView(v)`、`setLayout(partial)`；持久化：变更后 debounce 500ms PUT（失败 toast 不丢状态）；`useLibraryStore()`：recent（GET /api/workbench/recent）、collections+papers、createCollection、refresh
- Consumes: `workbenchApi`、`papersApi`（Task 2）；Tab/Layout 形状与后端 Workspace schema 逐字一致

- [ ] **Step 1: 写失败测试**

workbench.test：openPaper 去重/上限 20/激活；closeTab 不删后端数据；load 恢复 tabs+layout；saveState 调用参数形状 === 后端 schema（对照 fixtures）；debounce 合并多次变更为一 PUT。

- [ ] **Step 2: RED → 实现 → GREEN + Commit**

```bash
git add frontend/src/stores/
git commit -m "feat: workspace store with compatible persistence"
```

---

### Task 4: 外壳布局 + 欢迎页 + 库/导入 iframe 视图

**Files:**
- Create: `frontend/src/components/TopNav.vue`、`SideNav.vue`、`PaperTabs.vue`、`frontend/src/views/WorkbenchView.vue`（按 store.view 切换四个 section）、`WelcomeView.vue`、`ReadingView.vue`（标签容器骨架）、`LibraryView.vue`（iframe `/manage.html?embed=1`）、`ImportOverlay.vue`（iframe `/discover.html`，返回按钮关闭）、`frontend/src/shared/ui/EmptyState.vue`
- Modify: `src/router.ts`（单路由 `/` → WorkbenchView；视图切换走 store.view，与旧版一致且随工作区持久化，不用 URL 路由）
- Test: `frontend/src/components/PaperTabs.test.ts`、`WelcomeView.test.ts`

**Interfaces:**
- Produces: TopNav 四按钮绑定 store.setView + aria-current；SideNav 新建阅读（emit('new-task')）、搜索导入（emit('open-import') → ImportOverlay）、最近阅读列表（点击 openPaper）、领域列表（collection 展开论文）、新增领域（emit('new-domain')）；PaperTabs 渲染 tabs + 加号 + 关闭 + 首页按钮，激活态；WelcomeView 起始表单（textarea ≤3000 + 选择/导入论文 + 开始阅读）、模板网格（GET templates，点击 emit('use-template', t)）、比较多篇/独立讨论入口；LibraryView/ImportOverlay 仅 iframe 封装（页面本身计划五迁移）
- Consumes: workbench/library stores（Task 3）

- [ ] **Step 1: 写失败测试**

PaperTabs.test：渲染 tabs、点击激活、关闭 emit、加号 emit。WelcomeView.test：模板渲染、提交 emit 携带问题文本、空问题禁用提交。

- [ ] **Step 2: RED → 实现 → GREEN**

组件样式只用 tokens 变量；布局对照 index.html 结构（work-top/work-layout/work-sidebar/work-main）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ frontend/src/views/ frontend/src/router.ts
git commit -m "feat: workbench shell layout and welcome view"
```

---

### Task 5: 任务窗口（会话/模板/分类/领域/论文 + 就地新增）

**Files:**
- Create: `frontend/src/components/TaskDialog.vue`、`PaperPicker.vue`、`frontend/src/stores/sessions.ts`
- Test: `frontend/src/components/TaskDialog.test.ts`

**Interfaces:**
- Produces: TaskDialog props `{ mode: 'read'|'compare'|'chat'|'review', templateId?, paperIds? }`，emits `created(session, startingPrompt)`/`close`；内部：选已有会话或新建（标题/模板/分类/论文）；模板/分类/领域支持就地新增（调 createTemplate/createCategory/createCollection 后刷新列表并选中新项，**保留已填内容**）；PaperPicker 搜索论文 + 上传/导入入口（emit 到 discover iframe）+ 无全文提示；创建调 sessionsApi.create，请求期间按钮禁用；compare 模式强制 ≥2 篇
- Consumes: sessionsApi/papersApi（Task 2）、library store

- [ ] **Step 1: 写失败测试**

TaskDialog.test：选模板填充 starting_prompt；就地新增分类后原输入保留且新分类选中；compare 模式 1 篇时创建禁用；创建中按钮 disabled；created emit 形状。

- [ ] **Step 2: RED → 实现 → GREEN + Commit**

```bash
git add frontend/src/components/TaskDialog.vue frontend/src/components/PaperPicker.vue frontend/src/stores/sessions.ts
git commit -m "feat: task dialog with inline creation flows"
```

---

### Task 6: 阅读 iframe 集成与保存协议

**Files:**
- Create: `frontend/src/components/ReaderFrame.vue`、`frontend/src/shared/bridge.ts`
- Modify: `ReadingView.vue`（iframe 池管理）
- Test: `frontend/src/shared/bridge.test.ts`

**Interfaces:**
- Produces: bridge 协议（与旧 workbench/app.js 一致，实现前 `git show HEAD:app/web/workbench/app.js` 核对消息名）：父→子 `{type:'research-save-request'}`，子→父 `{type:'research-saved', paperId, sessionId}`；消息校验 event.origin === location.origin 且 source 属于已注册 iframe；ReaderFrame props `{paperId, sessionId}`，src `/reader.html?paper_id=&session_id=`；ReadingView 维护 ≤3 个挂载 iframe（LRU），释放前 await save-request（超时 2s 兜底放行并 toast 提示），标签切换不卸载已加载帧
- Consumes: workbench store；现有 reader.html（不修改）

- [ ] **Step 1: 写失败测试**

bridge.test：伪造 MessageEvent，origin 不符/source 未注册 → 忽略；合法 saved 消息 resolve 对应等待；save-request 超时兜底。

- [ ] **Step 2: RED → 实现 → GREEN**

手动验证：vite dev 打开 /v2/，打开论文标签→切换→关闭，草稿/位置经旧 reader 保存（对照旧版行为）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ReaderFrame.vue frontend/src/shared/bridge.ts frontend/src/views/ReadingView.vue
git commit -m "feat: reader iframe pool with save protocol"
```

---

### Task 7: 比较与定时任务视图

**Files:**
- Create: `frontend/src/views/CompareView.vue`、`SchedulesView.vue`、`frontend/src/components/ScheduleDialog.vue`、`frontend/src/stores/schedules.ts`
- Test: `frontend/src/views/SchedulesView.test.ts`、`CompareView.test.ts`

**Interfaces:**
- Produces: CompareView 比较会话列表（sessionsApi.list kind=comparison，展示 last_status/preview/论文数）+ 新建（TaskDialog mode=compare）+ 点击打开关联论文标签（store.openPaper 多标签同会话）；SchedulesView 列表（标题/会话/间隔/enabled/next_at/last_run 状态）+ 启停 PATCH + 手动执行 POST run + ScheduleDialog 新建（选会话/提示词/间隔，默认暂停）
- Consumes: sessionsApi/schedulesApi、TaskDialog、workbench store

- [ ] **Step 1: 写失败测试**

SchedulesView.test：渲染列表、启停调用 enable、执行调用 run 并刷新 last_run；新建默认 enabled=false。CompareView.test：新建入口打开 dialog；点击会话打开其论文标签。

- [ ] **Step 2: RED → 实现 → GREEN + Commit**

```bash
git add frontend/src/views/ frontend/src/components/ScheduleDialog.vue frontend/src/stores/schedules.ts
git commit -m "feat: compare and schedules views"
```

---

### Task 8: 运行活动面板（进度 + 取消）

**Files:**
- Create: `frontend/src/components/ActivityPanel.vue`、`frontend/src/stores/activity.ts`
- Test: `frontend/src/stores/activity.test.ts`

**Interfaces:**
- Produces: `useActivityStore()`：轮询 GET /api/agent/runs（2s，仅面板可见时）取 queued/running；对 running run 订阅 SSE `/api/agent/runs/{id}/events`（EventSource），progress 帧更新 `run.progress`；SSE error → 回退 2s 轮询 getRun；终态后移出活动列表并 toast；`cancel(id)` 调 cancelRun，按钮终态后消失；ActivityPanel 挂 SideNav 底部，展示 skill/进度摘要（tools/text）/取消按钮
- Consumes: agentApi（Task 2）

- [ ] **Step 1: 写失败测试**

activity.test（mock EventSource/fetch）：progress 帧更新；SSE 断线回退轮询至终态；cancelled 终态正确展示；cancel 调用后按钮禁用至终态。

- [ ] **Step 2: RED → 实现 → GREEN**

手动验证（最小模型用量）：/v2/ 建 chat 会话发"回复 OK"→ 面板显示进度 → 取消 → 显示已取消。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ActivityPanel.vue frontend/src/stores/activity.ts
git commit -m "feat: live run activity panel with progress and cancel"
```

---

### Task 9: /v2 挂载 + 回归 + 文档

**Files:**
- Modify: `app/main.py`（dist 存在时 mount '/v2' StaticFiles(html=True)，在 catch-all 之前）、`.gitignore`（frontend/dist 忽略但构建产物部署时生成）、`架构.md`/`enviroment.md`（前端入口增 /v2 说明）、`README.md`（frontend 开发命令）
- Test: `tests/test_route_surface.py` 追加 /v2 挂载存在性（dist 缺失时跳过挂载的分支测试）

- [ ] **Step 1: 写失败测试**

test_v2_mount：构建 dist 后 create_app 路由含 /v2；dist 不存在时不挂载且 /health 正常。

- [ ] **Step 2: RED → 实现 → GREEN**

`cd frontend && npx vite build` → 后端全套 + 前端全套通过。手动：浏览器 /v2/ 完整走一遍 新建阅读→标签→任务窗口→比较→定时任务→活动面板；手机宽度抽查。

- [ ] **Step 3: Commit**

```bash
git add app/main.py tests/test_route_surface.py 架构.md enviroment.md README.md .gitignore
git commit -m "feat: serve vue workbench at /v2 alongside legacy ui"
```