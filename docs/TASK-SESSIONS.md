> 历史专项记录：当前实现、接口与额度以 [文档目录](README.md)、[架构](架构.md) 和 [项目状态](STATUS.md) 为准。

# 任务会话与图文论文库（2026-11-17）

## 设计参考

参考 [siteboon/claudecodeui](https://github.com/siteboon/claudecodeui) 的会话管理思路，具体查看了 `server/modules/database/repositories/sessions.db.ts` 中应用会话 ID 与 `provider_session_id` 的映射，以及 Claude runtime/session provider 的恢复逻辑。本次独立实现，没有引入该项目源码或完整终端/文件编辑权限。

## 一个任务，一个可延续会话

- 管理主键：SQLite `conversations.id`；原生主键：`native_session_id`（UUID）。
- 会话保存 kind、skill、template_id、category_id、标题、置顶、归档、起步草稿和关联论文。
- 单轮执行保存在 `agent_runs`；多个执行属于同一个会话。
- 首轮 Claude 使用 `--session-id`，后续使用同一 UUID 的 `--resume`，工作目录固定在 `data/agent/sessions/<UUID>`。
- 本项目原生会话单独保存在 `data/agent/claude-config`，不导入或修改用户私人 Claude 会话。
- 不再关闭原生持久化，不再把最近两轮拼接当作完整会话延续。
- 原生会话标记为已建立但文件丢失时，明确失败，禁止悄悄新开会话假装延续。
- 历史 MVP 记录保留；首次继续时最多导入最近 20 轮成功记录，每条内容上限 2,000 字。旧版未保存原生上下文，无法恢复其隐藏工具状态。
- 消息可分页加载，分类搜索覆盖标题、历史问题和回答；归档可恢复。

原生恢复仍受模型上下文窗口、Claude 自动压缩、工具权限与提供商额度限制，不保证模型永久保留所有细节。科研知识仍需独立证据化管理。

## 起步模板

内置：阅读论文、对比论文、审查论文、发现论文、检索论文库、自由讨论。用户可保存自定义模板，选择已注册 Skill 和起步提示词。

模板先创建管理会话，不自动消耗模型额度；“创建并开始”或会话发送才触发 Agent。阅读/审查至少关联一篇论文，对比至少两篇。会话的 Skill 固定，不在同一上下文中无提示切换任务权限。

本次阅读/审查/比较提供基础 Skill，使用只读 `paper_read` 获取已有索引文本。每次最多八块、每轮最多四次工具调用，返回范围和 has_more；图表未读取，旧页码未核验。它是可继续的工作入口，不是完整高质量全文审稿的验收结果。

## 论文管理

新论文库展示原始 PDF 首页图、题目、作者、单位、摘要与多分类标签。真实 PDF 预览按文件修改信息缓存，不生成虚构插图。

- `paper_collections` 与 `paper_collection_items` 支持一篇论文属于多个分类。
- 可搜索标题、作者、单位、原摘要和简要摘要。
- 可编辑标题、作者、单位、简要摘要、所属分类；版本号避免覆盖他人的新修改。
- 单位候选只取 PDF 首页原文，拆分编号和明显非单位行；标 `pdf_first_page_unverified`，不推断作者与单位的逐一关系。用户保存确认后标 user。
- 没有单位显示“待补全”；摘要默认原摘要节选，不冒充中文 AI 总结。
- 单篇卡片可创建阅读/审查会话，多选可创建对比会话。

## 管理接口

- `/api/sessions/templates`：读取模板、保存自定义模板。
- `/api/sessions/categories`：会话分类。
- `/api/sessions`：创建、按类型/分类/历史内容查找会话。
- `/api/sessions/{id}`：详情、改标题、置顶、归档、归类。
- `/api/sessions/{id}/runs`：分页历史。
- `/api/library/collections`：论文分类。
- `/api/library/papers`：图文卡片、检索、分页。
- `/api/library/papers/{id}`：资料与分类修改。
- `/api/library/papers/{id}/thumbnail`：受控 PDF 首页图片。
- `/api/library/papers/{id}/refresh-card`：生成预览、提取未确认单位。

## 用量与启动

`usage` 展示本轮 token，原生 session 的 `modelUsage/total_cost_usd` 可能累计；新结果 metadata 标 cost_scope=native_session_cumulative，界面禁止将每轮累计估算简单相加作为账单。

继续使用现有模型连接，未新增密钥；默认输出每轮上限 1,024 tokens，最多六个 turns，120 秒超时。不自动重试模型执行。CLI 金额估算的第三方计价仍未知。

Compose 现在默认 `HF_HUB_OFFLINE=1` 使用已缓存模型，避免启动时访问镜像并被限流阻塞。新机器首次下载必须设置 `HF_HUB_OFFLINE=0`，完成缓存后恢复 1；服务器现有缓存已验证。

## 备份与恢复

`ops/backup.sh` 现在在原有 DB/Qdrant 备份之外，归档本项目 `agent/claude-config` 与 `agent/sessions`，保留 14 份；新会话归档权限仅拥有者可读写。

恢复时要同时恢复 DB 中原生 ID 映射、上述会话目录，并保持宿主项目路径一致。只恢复 DB 不足以让 Claude `--resume` 找到原生历史。正在执行的 turn 仍无自动断点重试，避免重复计费。

## 验证

测试使用 fake 模型，覆盖会话创建/草稿/分类/归档/固定 Skill、分页、native ID 与 resume 参数、原生文件丢失、卡片元数据版本、PDF 路径边界、单位来源与错误行过滤、多分类、私有备份。

另做低用量真实验证：两个独立 CLI 进程恢复同一验证词；网页创建分类阅读会话、读取真实论文材料，重启 API 和 Runner 后继续同一会话。保留任务和使用量作为证据。
