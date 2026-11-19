# 接口与调用约定

依据：2026-11-19 / `13956f9` 的已注册 OpenAPI。交互文档 `/docs`，机器描述 `/openapi.json`，完整路径见 [路由清单](API-ROUTES.md)。字段的最终定义以各域 schemas.py 与 OpenAPI 为准。

现有部署由外层访问认证保护；业务为单用户上下文。不要从本地用户资料接口推断已实现账号/租户权限。`/api/internal/*` 为 Runner 受限工具使用，前端不得获取其私有令牌。

## 1. 业务分组

| 领域 | 主要路径 | 用途 |
| --- | --- | --- |
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
| 用户 | `/api/me`、`/api/me/preferences`、`/api/me/avatar` | 单用户资料、偏好与头像 |

列表不共享一套分页协议：论文/技能列表采用 offset/limit，前沿报告与候选使用各自返回的 next_cursor；沿用返回游标，不自行拼接或假设跨列表通用。

## 2. 会话与执行

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

运行时结构见 `app/reader/guides/schemas.py`；[契约附件](contracts/paper-guide-v1.schema.json) 为设计参考，当前不接受图像 asset 锚点。完整例证见 [导读验收](Skill导读与批注实现验收.md)。

## 4. 导入与审批

`POST /api/imports/source` 的 channel 为 auto/arxiv/doi/url，带 value、request_key，可带 collection_id、target_paper_id；后者用于补充现有论文全文。PDF 用 multipart，字段为 file/request_key，可带同样目标字段。导入返回请求状态，不能只凭 HTTP 202 判断全文已保存。

前沿主题 POST 创建后默认暂停。执行使用 `/api/frontier/topics/{ident}/runs` 带 request_key。批准使用 `/api/frontier/topics/{topic_id}/items/{entity_id}/decision`，带 action、revision、request_key，可选 collection_ids/fulltext/confirm_distinct。action 为 approve/ignore/reopen。

批量审批返回逐项结果，不假设全部成功；revision 冲突需重新读取最新候选再决定。全文获取和批准书目不同，缺全文仍走补充入口。

## 5. 错误、版本和费用

| 状态 | 常见含义与处理 |
| --- | --- |
| 400 | 业务参数/范围/关联不合法，修正后明确重试 |
| 403 | 内部授权或任务范围不匹配，不能通过更换任意 ID 绕过 |
| 404 | 资源或可用文件不存在 |
| 409 | 版本、并发修订、请求键语义或执行状态冲突，先重新查询 |
| 422 | 请求或结构化产物校验失败，查看 detail，不接受模型伪造字段 |
| 429 | 来源/工具/额度上限等限制，检查返回原因 |

错误体可能包含字符串或结构化 detail，客户端不能假设全部为固定文本。Run、导读、导入和前沿有不同状态集合，不将所有 partial 都转换成 succeeded。

用量和 cli_estimated_cost_usd 属于执行记录；未知费用不能显示为零，不可当作核实账单。当前协议兼容由 `/api/agent/status` 判断，不使用页面版本号推测。
