# 接口与调用约定

更新：2026-11-21，依据当前已注册 OpenAPI。交互文档 `/docs`，机器描述 `/openapi.json`，完整路径见 [路由清单](API-ROUTES.md)。字段的最终定义以各域 schemas.py 与 OpenAPI 为准。

公网使用 HTTPS 与应用网页登录；旧 Basic Auth 已关闭。服务端登录会话绑定独立账号工作区。当前只允许原管理员登录，公开注册关闭；认证接口、Cookie、CSRF 和账号管理详见 [认证说明](AUTHENTICATION.md)。`/api/internal/*` 为 Runner 受限工具使用，前端不得获取其私有令牌。

业务 API 要求有效会话，写请求另需 X-CSRF-Token；401 应回到登录页。文件、SSE、头像和资料查询同样隔离，客户端指定其他工作区不会改变访问范围。

## 1. 业务分组

| 领域 | 主要路径 | 用途 |
| --- | --- | --- |
| 认证与账号 | `/api/auth/*`、`/api/admin/accounts` | 登录、退出、密码修改、关闭注册及管理员账号管理 |
| Runner 配置 | `/api/me/runner/connections`、`/api/me/runner/budgets` | 账号私有连接、凭据、额度、默认和本地预检，见 [Runner 配置](RUNNER-CONFIGURATION.md) |
| 健康与 Agent | `/health`、`/api/agent/status`、`/api/agent/runs` | 可用性、协议、执行、查询、取消和事件 |
| 会话 | `/api/sessions`、`/api/sessions/templates`、`/api/sessions/categories` | 任务上下文、模板、分类与归档 |
| 论文库 | `/api/library/papers`、`/api/library/collections` | 列表、卡片、分类、编辑与缩略图 |
| 导入 | `/api/imports/source`、`/api/imports/upload` | 多来源提交、状态、重试与补充全文 |
| 阅读 | `/api/reader/papers/{paper_id}`、`/api/reader/annotations` | PDF、页面、批注、位置和译文 |
| 导读 | `/api/reader/guide-skills`、`/api/reader/papers/{pid}/guide-runs` | 兼容 Skill、明确触发与结果 |
| 工作区 | `/api/workbench/states/{ident}`、`drafts/{sid}/{pid}`、`images` | 布局/标签、草稿与附件 |
| Skills | `/api/skills`、`/api/skills/imports` | 安装、版本、默认版本、分类、审计、最小验证 |
| 前沿 | `/api/frontier/topics`、`reports`、`candidates`、`projects` | 主题、报告、发现、审批和项目库 |
| 调度 | `/api/workbench/schedules` | 默认停用的间隔任务，启停及执行一次 |
| 用户 | `/api/me`、`/api/me/preferences`、`/api/me/avatar` | 当前账号资料、偏好与头像 |

列表不共享一套分页协议：论文/技能列表采用 offset/limit，前沿报告与候选使用各自返回的 next_cursor；沿用返回游标，不自行拼接或假设跨列表通用。

## 2. 会话与执行

论文删除为可恢复操作：`DELETE /api/library/papers/{paper_id}` 移入回收站；`POST /api/library/papers/{paper_id}/restore` 恢复；`GET /api/library/papers?trashed=true` 查询回收站（仍支持搜索、分类和分页）。操作按认证工作区隔离、需要 CSRF，重复删除/恢复幂等；未知 ID 返回 404，关联执行中/排队 Run 或待处理导入返回 409。物理文件、分类关系、会话和批注不删除，不传播 Zotero 删除。

创建会话只准备上下文，不等于发送。示意 JSON（不在文档检查中执行）：

```json
{"title":"方法阅读","template_id":"read","paper_ids":[7]}
```

随后明确发送至 `POST /api/agent/runs`：

```json
{"conversation_id":123,"prompt":"请基于已读取的材料解释方法，并说明覆盖范围。","purpose":"chat","request_key":"client-unique-key"}
```

返回 202 后使用返回的 Run ID 查询 `/api/agent/runs/{run_id}` 或订阅 `GET .../events`。浏览器 SSE 是 `data: <JSON快照>`，终态 succeeded/failed/cancelled 后结束；并非逐字模型 token 流。取消使用 `POST .../{run_id}/cancel`。

RunCreate 允许最多 3 个 contexts 和 3 个 attachment_ids；上下文继承文件版本、物理页、引文和归一化矩形。图片先经 multipart 上传并绑定会话/论文，再传附件 ID，不传任意本地路径。

`request_key` 用于幂等，不同语义请求不要重用；发生网络不确定时先查已有任务，不能用新请求键盲目重试。

## 3. 导读与批注

`GET /api/reader/papers/{pid}/guide` 读取已有任务/有效产物，可能协调已结束任务发布，但不创建模型任务。打开论文只调用查询。

用户确认后的 `POST .../guide-runs`：

```json
{"confirmed":true,"file_version":"<当前PDF的64位SHA-256>","request_key":"guide-client-key","skill_id":"paper_guide","reading_goal":"理解方法和关键证据","max_pages":2,"max_items":2}
```

先从 `GET /api/reader/papers/{paper_id}` 获取真实 file_version，不使用占位值调用。可选择 /guide-skills 返回的 skill_version_id；缺失/false 的 confirmed 被拒绝。

- 同论文/文件/技能版本及哈希/配置优先复用在途或成功任务；响应中的 cached 表明复用。
- 内部 context/material/submit 将任务、Run、Skill、PDF 和材料清单绑定；提交后先 staging，Run 成功才发布。
- 精确 text 锚点唯一匹配才高亮；block 或歧义仅页级定位；混合状态保留两种证据。
- 原始 AI 批注不直接编辑内容/颜色；通过 `POST /api/reader/guide-items/{ident}/adopt` 带 request_key 采纳为个人副本。
- `PATCH /api/reader/annotations/{ident}` 的 deleted 支持移除/恢复。隐藏任务使用 `PATCH /api/reader/guide-runs/{ident}` 的 hidden；执行中先 cancel。

运行时结构以 `app/reader/guides/schemas.py` 为准，注册工具使用该模型生成的 JSON Schema；当前不接受图像 asset 锚点。扩展规则见 [Skills 开发](SKILLS.md)。

## 4. 导入与审批

`POST /api/imports/source` 的 channel 为 auto/arxiv/doi/url，带 value、request_key，可带 collection_id、target_paper_id；后者用于补充现有论文全文。PDF 用 multipart，字段为 file/request_key，可带同样目标字段。导入返回请求状态，不能只凭 HTTP 202 判断全文已保存。

前沿主题 POST 创建后默认暂停。执行使用 `/api/frontier/topics/{ident}/runs` 带 request_key。批准使用 `/api/frontier/topics/{topic_id}/items/{entity_id}/decision`，带 action、revision、request_key，可选 collection_ids/fulltext/confirm_distinct。action 为 approve/ignore/reopen。

批量审批返回逐项结果，不假设全部成功；revision 冲突需重新读取最新候选再决定。全文获取和批准书目不同，缺全文仍走补充入口。

## 5. 错误、版本和费用

| 状态 | 常见含义与处理 |
| --- | --- |
| 400 | 业务参数/范围/关联不合法，修正后明确重试 |
| 401 | 会话缺失或失效，返回网页登录；响应不含浏览器密码挑战 |
| 403 | 内部授权或任务范围不匹配，不能通过更换任意 ID 绕过 |
| 404 | 资源或可用文件不存在 |
| 409 | 版本、并发修订、请求键语义或执行状态冲突，先重新查询 |
| 422 | 请求或结构化产物校验失败，查看 detail，不接受模型伪造字段 |
| 429 | 来源/工具/额度上限等限制，检查返回原因 |

错误体可能包含字符串或结构化 detail，客户端不能假设全部为固定文本。Run、导读、导入和前沿有不同状态集合，不将所有 partial 都转换成 succeeded。

用量和 cli_estimated_cost_usd 属于执行记录；未知费用不能显示为零，不可当作核实账单。当前协议兼容由 `/api/agent/status` 判断，不使用页面版本号推测。

## 文件、版本与批注下载

- `GET /api/library/papers/{paper_id}/documents`：当前文档、版本、默认版本及未解析历史批注。
- `POST /api/library/papers/{paper_id}/document-versions`：multipart 上传 PDF；file、label 必填，可带 document_id，或 role=main/supplement 与 title；source/description 为可选说明。上限 50 MiB、300 页，不支持加密。相同文档和文件哈希复用已有版本。
- `POST /api/library/papers/{paper_id}/document-versions/{version_id}/default`：必须带 confirmed=true 与 expected_version_id（首次可为 null）；只允许正文，冲突或在途任务返回 409。切换会解析、嵌入和更新索引，但不调用研究模型。
- `GET /api/library/papers/{paper_id}/document-versions/{version_id}/annotations`：仅返回该版本有效批注；origin=all/personal/ai，personal 包含已采纳副本。
- `GET /api/library/papers/{paper_id}/document-versions/{version_id}/file`：mode=original/annotated/markdown，origin 同上；仅 original 支持 inline=true 预览。原件与输出均禁止共享缓存，且必须属于当前账号与论文。

旧版会话的材料哈希与默认正文不同后，发送返回 409；会话响应的 stale_paper_ids 标识差异。重新进入阅读时选择或创建当前版本会话，旧原生会话不被覆盖。

## Zotero 交换接口

`POST /api/zotero/pair/start`、`pair/claim` 为无登录的短期配对交换，JSON 且受来源约束；其他非 device 接口要求网页登录，写请求仍需 CSRF。`pair/inspect` 先显示设备身份，`pair/approve` 明确批准；`GET /devices`、`DELETE /devices/{ident}` 管理当前账号授权。

`POST /exports` 接收 `device_id`、`paper_ids`（1–30）与 `request_key`，快照当时元数据和文件版本；同请求键复用任务。`GET /exports` 查最近记录；`POST /exports/{ident}/retry` 仅重排失败任务。

插件只使用 `Authorization: Bearer <device-token>` 调用 `/api/zotero/device/*`：`items` 提交书目，`papers/{pid}/attachments/check` 以来源键和 SHA-256 查询文件，`papers/{pid}/attachments` 用 multipart 上传 PDF（50 MiB/300 页）；`exports/claim` 返回任务、文件清单和 15 分钟租约；下载 `exports/{ident}/files/{vid}` 必须携带 `X-Sync-Lease`；`exports/{ident}/ack` 提交租约、成功/失败、目标库/条目与完整附件映射。同租约的相同终态回执可重复提交，不得据此继续下载文件。账号由服务端路由，插件不能选工作区。

409 表示元数据冲突、失效租约或来源映射冲突，不触发模型和自动覆盖；附件缺失、只读库或配对失效应先排除原因，再人工重试。详细字段以 `app/integrations/zotero/schemas.py` 为准。


当前 Zotero 文件与幂等约定：入站 `items.pdf_hash` 可选，采用正文 SHA-256 精确查重；不进入书目变更指纹。相同内容的不同附件键可关联同一文档版本。首次正文上传直接返回可阅读状态和 `fulltext_indexed`，不等待嵌入；文件列表也返回该标志。当前默认版本尚无索引时，使用既有 `POST .../document-versions/{vid}/default`、`expected_version_id=vid`、`confirmed=true` 明确补建，原文版本不改变。出站任务列表增加论文题名与租约到期信息；不同请求键可复用同一未完成任务，各自仍有持久幂等结果。领取任务时读取最新来源映射，材料内容仍保持排队时的快照。


分类创建 `POST /api/library/collections` 支持 `{name, parent_id}`；`parent_id` 可省略或为 null（顶层），正整数父级必须存在于当前账号工作区，缺失返回 404。同父级名称唯一，重复返回 409；不同父级允许同名。响应包含 ID、父 ID、完整路径和计数。使用既有 parent_id 结构，无新增数据库迁移。


连接与额度通过 `id/revision` 引用参与 Run 创建和请求键幂等校验。已有会话绑定连接，修改账号默认不会切换它；连接修订/停用后需新会话。配置预检不调用模型，响应的能力声明不等于实测。Run 返回 `diagnostics`，用于结束原因、有效额度、连接与预算快照及部分输出；没有独立的追加预算续跑端点。
