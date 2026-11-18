# 阅读/管理/发现页 Vue 化与部署切换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把三栏 PDF 阅读页、论文库/会话管理页、搜索导入页迁移为 Vue 组件，根路径切换到 Vue 工作台，退役旧原生页，Docker 多阶段构建前端，完成最终回归。

**Architecture:** PDF 引擎（旧 pdf-view.js 的 PDFReader 类）行为保持地移植为 `pdf-engine.ts`（构造器接收 root/pages 元素替代全局 id）；阅读页成为 ReaderPane 组件，ReadingView 用 `<KeepAlive :max="3">` 替代 iframe 池（deactivated 保存草稿/位置）；chat/sidebar/layout 移植为组件/composable，复用计划四的 api/stores。管理/发现页移植为 LibraryGrid/SessionsManager/ImportPanel/SearchPanel 视图替换 iframe。根切换用 SPA fallback StaticFiles + router base '/'；Dockerfile 加 node 构建阶段。

**Tech Stack:** Vue 3 + Vite + TS + Pinia + Vitest（沿用计划四工程）；PDF.js 沿用 `app/web/vendor/pdfjs`（legacy build，运行时绝对路径 import）；md.js 复制到 `frontend/public/`。

**Spec:** `docs/superpowers/specs/2026-11-17-modular-refactor-design.md`（§8）

## Global Constraints

- 行为对照旧版逐流程保持：`app/web/reader/main.js`（boot/activate/selection/position/bridge）、`chat.js`（ask/watch/draft/attachments/templates）、`sidebar.js`（五 tab/批注 CRUD/译文缓存重试删除撤销）、`layout.js`（拖动/键盘/收起/移动端）、`workspace.js`（会话/论文库管理）、`discovery.js`（导入/搜索）。实现每个任务前必读对应旧文件。
- 主题只用计划四 tokens；布局结构与旧版一致（三栏、顶部工具条、选区浮动条、移动端分区切换 ≤760px）。
- 测试不调用真实模型；PDF 渲染用 fake pdf 对象；全套绿：后端 `HF_HOME="$PWD/data/hf" HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider`（基线 161），前端 `cd frontend && npx vitest run && npx vue-tsc --noEmit && npx vite build`（基线 58）。
- 会话切换 epoch 守卫、PDF generation 守卫、草稿 400ms 防抖、位置 400ms 防抖、request_key 幂等——旧版这些保护必须保留。
- 旧文件退役只在 Task 12（根切换）执行；之前任务旧页面保持可用（/v2 与 / 并存）。
- `ops/` 敏感文件永不提交；独立 worktree；PDF.js vendor 与 md.js 保留服务。

## Review Focus

1. **草稿/位置不丢**：KeepAlive deactivated/卸载、会话切换、标签关闭前 flush 草稿与位置；保存失败有 toast（对照旧版 save-reader 协议语义）。
2. **PDF 渲染管线保真**：generation 守卫取消旧渲染、并发 2 队列、±5 页外驱逐、fit 缩放 ResizeObserver 重排、选区不被驱逐打断。
3. **选区流程**：高亮/批注/加入对话/解释/翻译五动作；file_version 不匹配拒绝定位；译文缓存复用不新增模型调用；失败/取消可重试删除。
4. **会话激活竞态**：快速切换会话 epoch 守卫；未关联论文报错；无会话自动创建 read 会话；原生上下文状态展示。
5. **根切换无死链**：深链 /reader 等 SPA fallback 生效；/vendor、/md.js 可达；旧页面删除后无残留引用（grep）；docker 多阶段构建可复现。

---

### Task 1: reader API 模块

**Files:**
- Create: `frontend/src/api/reader.ts`、`frontend/src/api/reader.test.ts`
- Modify: `frontend/src/api/types.ts`（ReaderDoc/Annotation/Position/TranslationRecord/AnnotationCreate）

**Interfaces:**
- Produces: `readerApi.document(paperId)`、`pageText(paperId, page)`、`annotations(paperId)`、`createAnnotation(body)`、`patchAnnotation(id, body)`、`getState(paperId, conversationId)`、`saveState(paperId, body)`、`translations(paperId)`、`translate(body)`、`setTranslationVisible(id, deleted)`；类型对照 `app/reader/schemas.py`（Context/Annotation/Position/Translation）
- Consumes: 计划四 api/client

- [ ] **Step 1: 写失败测试**（mock fetch：createAnnotation POST 路径/body；translate 返回 cached 标志；getState 查询参数）
- [ ] **Step 2: RED → 实现 → GREEN + typecheck**
- [ ] **Step 3: Commit** `feat: reader api module`

---

### Task 2: PDF 引擎移植

**Files:**
- Create: `frontend/src/reader/pdf-engine.ts`（自 `app/web/reader/pdf-view.js` 移植）、`frontend/src/reader/pdf-engine.test.ts`
- Modify: `frontend/src/vite-env.d.ts`（declare module '/vendor/pdfjs/legacy/build/pdf.mjs'）

**Interfaces:**
- Produces: `class PDFReader extends EventTarget`，`constructor(root: HTMLElement, pages: HTMLElement)`；方法 `load(info, position)`/`layout()`/`jump(n, flash?)`/`setZoom(v)`/`setMode(m)`/`setAnnotations(items)`/`destroy()`；事件 `page/zoom/selection/ink/erase/rendered`；属性 `currentPage/zoom/color/mode`。渲染管线（queue/pump/renderPage/evict/trackPage/bindInk/captureSelection/paintPage）逻辑逐字保持，仅元素访问改为构造器参数、`$` 依赖移除。
- Consumes: PDF.js 运行时绝对路径 import（/vendor/...）

- [ ] **Step 1: 写失败测试**（fake pdf：numPages/getPage/getViewport/render/streamTextContent stub；jsdom IntersectionObserver/ResizeObserver stub）：load 后 holders 数=numPages；enqueue/pump 并发≤2；generation 变更后旧渲染结果不落地；evict 驱逐 ±5 页外 ready 页但保留选区所在页；jump 钳制页码并发 page 事件。
- [ ] **Step 2: RED → 移植 → GREEN**
- [ ] **Step 3: Commit** `feat: port pdf engine to vue frontend`

---

### Task 3: 布局 composable

**Files:**
- Create: `frontend/src/reader/useReaderLayout.ts`、`useReaderLayout.test.ts`
- Modify: 无（消费 workbench store.layout）

**Interfaces:**
- Produces: `useReaderLayout()`：`{ leftWidth, rightWidth, leftHidden, rightHidden, mobileMode, startDrag(side, event), nudge(side, delta), toggle(side), setMobile(name) }`；拖动 pointer 事件钳制 140–600（后端 Layout 约束）；键盘 ArrowLeft/Right ±20；变更写 wb.setLayout（持久化沿用）；≤760px 移动端分区 left/pdf/chat。
- Consumes: workbench store（计划四）

- [ ] **Step 1: 写失败测试**（钳制/键盘/收起/持久化调用）→ **RED → 实现 → GREEN**
- [ ] **Step 2: Commit** `feat: reader layout composable`

---

### Task 4: ReaderPane 外壳与编排

**Files:**
- Create: `frontend/src/views/ReaderPane.vue`、`frontend/src/views/ReaderPane.test.ts`、`frontend/src/reader/useReaderOrchestrator.ts`
- Modify: 无

**Interfaces:**
- Produces: ReaderPane props `{ paperId, sessionId? }`，emits `open-paper/open-import/session-bound/save-failed`；orchestrator 对照 main.js：boot（profile→document→缺 PDF 错误面板+补充入口→会话选择/自动创建→position→engine.load）、activate epoch 守卫、positionSnapshot/writePosition/savePosition(400ms)、选区五动作（highlight/note/chat/explain/translate，translate 缓存 toast）、ink/erase 事件落批注、jump 版本守卫、工具条（页码/缩放/选择/画笔/橡皮/颜色）。ChatPanel/Sidebar 子组件 Task 5/6 接入（本任务先占位 slot）。
- Consumes: readerApi（T1）、PDFReader（T2）、useReaderLayout（T3）、sessionsApi/workbenchApi

- [ ] **Step 1: 写失败测试**（mock engine/api：boot 缺 PDF 显示补充入口；无会话自动创建 read；activate 快速切换 epoch 守卫只落最后一次；选区 translate 缓存命中 toast 且不调 createRun；file_version 不匹配 jump 拒绝）
- [ ] **Step 2: RED → 实现 → GREEN**
- [ ] **Step 3: Commit** `feat: reader pane shell and orchestration`

---

### Task 5: ChatPanel 组件

**Files:**
- Create: `frontend/src/components/reader/ChatPanel.vue`、`ChatPanel.test.ts`、`frontend/src/reader/useChat.ts`
- Modify: ReaderPane 接入；`frontend/index.html` 加 `<script src="/md.js">`；`frontend/public/md.js`（自 app/web/md.js 复制）；`vite-env.d.ts` declare `window.mdRender`

**Interfaces:**
- Produces: 对照 chat.js：会话 runs 渲染（状态/进度/用量/原文上下文/图片/工具来源核对按钮）、ask（request_key 幂等 + localStorage pending 恢复）、watch（2s 轮询至终态，含 cancelled）、草稿 400ms 防抖保存/恢复（文字+选区+附件）、图片上传（≤3、预览、移除）、模板填入、失败/取消重新编辑、flushDraft/restoreDraft 暴露给编排器。
- Consumes: agentApi/workbenchApi/sessionsApi、readerApi

- [ ] **Step 1: 写失败测试**（ask 幂等键复用 pending；watch 终态停止；草稿防抖合并；附件超限拒绝；重新编辑恢复 prompt/附件）
- [ ] **Step 2: RED → 实现 → GREEN**
- [ ] **Step 3: Commit** `feat: reader chat panel`

---

### Task 6: Sidebar 组件

**Files:**
- Create: `frontend/src/components/reader/ReaderSidebar.vue`、`ReaderSidebar.test.ts`
- Modify: ReaderPane 接入

**Interfaces:**
- Produces: 对照 sidebar.js：五 tab（outline/notes/highlights/translations/info）；目录点击 jump；批注列表删除/撤销（软删除）；高亮列表定位；译文列表（成功渲染 markdown、失败/取消重试、删除/撤销、缓存标志）；论文信息（标题/作者/单位/摘要/版本）；onTab 触发位置保存；setTab/tab 暴露。
- Consumes: readerApi、mdRender（window）

- [ ] **Step 1: 写失败测试**（tab 切换 emit；译文失败显示重试且调用 translate；删除调用 setTranslationVisible(true) 并可撤销；批注删除后列表刷新）
- [ ] **Step 2: RED → 实现 → GREEN**
- [ ] **Step 3: Commit** `feat: reader sidebar`

---

### Task 7: ReadingView 切换 KeepAlive

**Files:**
- Modify: `frontend/src/views/ReadingView.vue`（iframe 池 → `<KeepAlive :max="3">` + ReaderPane）、`frontend/src/views/ReadingView.test.ts`、`frontend/src/views/WorkbenchView.vue`（shell bridge 移除 reader 部分）
- Delete: 无（bridge.ts 保留给 manage/discover iframe 至 Task 11）

**Interfaces:**
- Produces: ReadingView 按 (paperId, sessionId) key 渲染 ReaderPane；KeepAlive max=3 LRU；onDeactivated flush 草稿+位置（orchestrator 暴露 flush()）；会话重绑定改 key 触发重建；open-paper/open-import emit 上抛 workbench；save-failed → toast。
- Consumes: ReaderPane（T4-6）

- [ ] **Step 1: 改写测试**（≤3 缓存实例；第 4 篇触发最旧 deactivated flush；重绑定 session 重建；home 不销毁缓存）
- [ ] **Step 2: RED → 实现 → GREEN**
- [ ] **Step 3: Commit** `feat: replace reader iframe pool with keepalive panes`

---

### Task 8: LibraryGrid 与论文编辑

**Files:**
- Create: `frontend/src/views/manage/LibraryGrid.vue`、`frontend/src/components/manage/PaperEditDialog.vue`、对应测试
- Modify: 无

**Interfaces:**
- Produces: 对照 workspace.js 论文库页：卡片网格（缩略图/标题/作者/摘要/分类 chips/缺全文标志）、搜索、分类筛选（含未分类）、编辑对话框（标题/作者/单位/简介/分类多选，metadata_version 乐观锁冲突提示刷新）、补充 PDF 入口（emit open-import(target)）、阅读入口（emit open-paper）。
- Consumes: papersApi、workbenchApi（upload 入口转 ImportPanel）

- [ ] **Step 1: 写失败测试**（卡片渲染；编辑提交带 metadata_version；409 冲突提示；分类筛选调用参数）
- [ ] **Step 2: RED → 实现 → GREEN**
- [ ] **Step 3: Commit** `feat: library grid and paper edit dialog`

---

### Task 9: SessionsManager 与模板管理

**Files:**
- Create: `frontend/src/views/manage/SessionsManager.vue`、`frontend/src/components/manage/TemplateManager.vue`、对应测试
- Modify: 无

**Interfaces:**
- Produces: 对照 workspace.js 会话页：会话列表（分类筛选/搜索/归档切换/置顶）、打开会话（有论文→open-paper 多标签；无论文→会话详情 runs 视图）、会话内 runs 历史（分页 before）、模板管理（列表/新增/编辑 builtin 不可改）。
- Consumes: sessionsApi、TaskDialog（计划四）

- [ ] **Step 1: 写失败测试**（归档切换调用 update；打开有论文会话 emit open-paper；runs 分页 next_before）
- [ ] **Step 2: RED → 实现 → GREEN**
- [ ] **Step 3: Commit** `feat: sessions manager and template management`

---

### Task 10: ImportPanel 与 SearchPanel

**Files:**
- Create: `frontend/src/views/discover/ImportPanel.vue`、`SearchPanel.vue`、对应测试
- Modify: 无

**Interfaces:**
- Produces: 对照 discovery.js：来源表单（auto/arxiv/doi/url + 分类 + 目标论文预填 target_paper_id）、上传表单（多文件 ≤8、30MB 校验、request_key 幂等）、导入记录列表（状态轮询至终态、失败重试）、搜索表单（agent paper_search run + watch + 结果卡片 + 添加到论文库）。
- Consumes: importsApi/agentApi/papersApi

- [ ] **Step 1: 写失败测试**（来源提交带 target_paper_id；导入 watch 终态停止；失败重试调用 retry；搜索结果添加调用 importsApi.source）
- [ ] **Step 2: RED → 实现 → GREEN**
- [ ] **Step 3: Commit** `feat: import and search panels`

---

### Task 11: 工作台集成（替换 iframe）

**Files:**
- Modify: `frontend/src/views/WorkbenchView.vue`、`LibraryView.vue`（→ manage 容器：LibraryGrid/SessionsManager 切换）、`ImportOverlay.vue`（→ ImportPanel/SearchPanel）、`SideNav.vue`
- Delete: `frontend/src/views/LibraryView.vue` 旧 iframe 实现（替换内容）

**Interfaces:**
- Produces: library 视图 = manage 容器（论文库/会话两页切换，session_id 参数直达会话）；导入 overlay = Vue 面板；shell bridge 仅保留必要消息（iframe 全部移除后 bridge 可退役——确认无 iframe 后删除 attachBridge 调用与 bridge.ts 的 reader 协议注释更新）。
- Consumes: T8/T9/T10 组件

- [ ] **Step 1: 写失败测试**（library 视图渲染 LibraryGrid；导入 overlay 渲染 ImportPanel；无 iframe 残留）
- [ ] **Step 2: RED → 实现 → GREEN**
- [ ] **Step 3: Commit** `feat: replace manage and discover iframes with vue views`

---

### Task 12: 根切换 + Docker 多阶段 + 旧页退役

**Files:**
- Modify: `app/main.py`（SPA fallback StaticFiles 挂 /，移除 /v2 与旧 web 挂载）、`frontend/src/router.ts`（base '/'）、`frontend/vite.config.ts`（base '/'）、`Dockerfile`（node:24-alpine 构建阶段 → COPY dist）、`.dockerignore`、`tests/test_route_surface.py`
- Delete: `app/web/index.html`、`app/web/reader.html`、`app/web/reader/`、`app/web/manage.html`、`app/web/discover.html`、`app/web/workspace.js`、`app/web/workspace.css`、`app/web/discovery.js`、`app/web/discovery.css`、`app/web/workbench/`
- Keep: `app/web/vendor/`、`app/web/md.js`（复制到 frontend/public/ 后由 dist 服务）

**Interfaces:**
- Produces: `SPAStaticFiles(StaticFiles)` 404 时回退 index.html（仅非文件路径）；/ 服务 Vue dist；/vendor/* 与 /md.js 由 dist 提供（vendor 复制到 frontend/public/vendor 或保留 app/web/vendor 单独挂载——选择：保留 app/web/vendor 挂载 /vendor，md.js 进 public）；Dockerfile 阶段 1 node 构建 frontend，阶段 2 COPY --from=build dist → app/web（与 vendor 合并）。
- Consumes: 全部前端任务

- [ ] **Step 1: 写失败测试**（SPA fallback：/reader/1 返回 index.html；/vendor/... 不受影响；/health 优先；旧 /reader.html 404）
- [ ] **Step 2: RED → 实现 → GREEN**（后端全套 + 前端全套 + build）
- [ ] **Step 3: grep 退役残留**（`grep -rn "reader.html\|manage.html\|discover.html\|workspace.js\|workbench/app.js" app/ frontend/src/ tests/ scripts/` 无结果）
- [ ] **Step 4: Commit** `feat: switch root to vue workbench, retire legacy pages, multi-stage docker build`

---

### Task 13: 最终回归与验收

**Files:**
- Modify: `架构.md`、`enviroment.md`、`README.md`、设计文档（§8/§10 标记完成）
- Test: 全套 + 冒烟 + 手动验收清单

- [ ] **Step 1: 全套回归**（后端 + 前端 + typecheck + build）
- [ ] **Step 2: 隔离实例验收**（临时 DATA_DIR + 真实 Runner）：/ 深链、阅读打开 PDF、选区高亮/翻译、草稿切换保存、比较会话、定时任务、导入上传、搜索、活动面板取消、移动端宽度抽查。记录结果。
- [ ] **Step 3: 文档更新 + Commit** `docs: vue migration complete, deployment and acceptance`