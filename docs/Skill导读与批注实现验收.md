# Skill 导读与批注：实现与验收

日期：2026-11-19；基于 `cf8f62f`，功能提交 `5dac0d7`。

## 用户操作与触发边界

打开具备全文的论文，在右侧输入框显示“试试：自动批注 / 阅读论文”。选择自动批注仅展开配置，可改阅读要求、选择兼容技能、调整材料页数和重点数量；点击“确认生成批注”才调用智能体。阅读论文也先确认，再创建绑定论文的阅读会话并调用现有阅读 Skill。

打开、刷新、切换标签、恢复导读、显示解释和切换 AI 图层均不创建模型任务。无全文沿用现有补充全文流程。当前没有首次打开、导入后或定时自动生成导读策略。

## 实现与复用

- 复用现有 Agent Run、原生执行会话、取消、工具配额、Skill 注册版本和费用记录。
- 新增 `paper_guide` 技能。兼容上传技能提供 context/material/submit 三种工具并满足输出额度后可被选择，锁定版本与内容哈希。技能负责内容判断，平台没有另写总结算法。
- 复用现有 `reader_annotations`、查询、删除/恢复、PDF.js 绘制与位置跳转，来源区分 user、ai、ai_adopted。
- 内容与解释统一通过 Marked + DOMPurify 显示。导读包含问题、核心思路、贡献与边界、路线、重点、为什么重要、解释、作者主张/证据/AI解释区分、建议问题、覆盖与缺口。
- 原始 AI 内容独立保存，采纳为个人副本后可编辑。删除的 AI 标记刷新不复活，失败记录可移除。AI 图层可独立隐藏，设置按论文保存。
- 模型返回证据块与短引文；材料工具从绑定版本的 PDF 提取真实字符与坐标，唯一匹配才生成矩形。歧义、整块说明或无法匹配只生成页级笔记和页边标记，禁止猜坐标。
- 执行会话与原讨论分开；用户原讨论、未发送内容和人工批注保留。只有 Run 成功且产物通过校验才事务发布；失败保留上次可用版本。

## 接口

| 接口 | 用途 |
| --- | --- |
| GET `/api/reader/guide-skills` | 列出当前可用于导读的技能和额度 |
| POST `/api/reader/papers/{id}/guide-runs` | 必填 confirmed:true、PDF版本与请求键；创建或复用任务 |
| GET `/api/reader/papers/{id}/guide` | 当前有效结果、最新任务、覆盖、费用和旧版本数量 |
| GET `/api/reader/papers/{id}/guides` | 最近 30 个历史任务 |
| POST `/api/reader/guide-runs/{id}/cancel` | 通过既有 Agent 机制停止 |
| PATCH `/api/reader/guide-runs/{id}` | 隐藏已结束记录，执行中须先停止 |
| POST `/api/reader/guide-items/{id}/adopt` | 幂等生成可编辑个人副本 |
| internal POST `/api/internal/reader-guide/context` | 绑定任务、文件、目录和上限 |
| internal POST `/api/internal/reader-guide/material` | 有界真实文本、材料及证据块 ID |
| internal POST `/api/internal/reader-guide/submit` | 严格验证 paper-guide/v1，暂存结构化结果 |

内部工具以现有私有令牌和运行 ID 授权，校验任务、Skill 和当前 PDF 版本；终态/取消后的工具写入被拒绝。前端 API 不接受模型自定数据库主键、矩形或文件路径。

请求示例：

```json
{"confirmed":true,"file_version":"<当前PDF的SHA-256>","request_key":"<本次唯一键>","skill_id":"paper_guide","reading_goal":"理解核心方法及证据","max_pages":6,"max_items":6}
```

结构化字段见 `app/reader/guides/schemas.py`；该严格 Pydantic 模型是运行时验证与工具 JSON Schema 的共同来源。不同请求键但相同论文、文件、技能版本/哈希与配置复用同一任务；失败后不自动重跑。

## 数据与发布

迁移 `0013_reader_guides.sql` 新增 reader_guide_tasks、reader_guide_blocks、reader_guide_items、reader_guide_adoptions；reader_annotations 增加 origin、guide_task_id、guide_item_id、derived_from。不重建论文或丢弃人工批注。

状态：dispatching → queued/running → staging → published/partial；失败、取消或拒绝终止，不盲目重新执行。PDF 换版的产物不激活在当前原文。历史任务提供查询 API，历史版本选择界面尚未完成。

生产分支 `release/frontier-workbench-20261119`，Runner 协议 4。备份 `/home/f/.local/state/research-assistant/backups/before-reader-guides-20261119-185306/app.db`；回退镜像 `research-assistant-app:before-reader-guides-20261119`。回退同步 app 与 Runner；没有推送 Git 远端。

## 验证与边界

- 前端：181 项通过，生产构建通过。新增测试验证展示建议、选择配置和取消均不执行，只有确认才调用。
- 后端相关：158 项通过，覆盖真实字符定位、重复句消歧、规范化、非法材料/锚点/坐标/覆盖拒绝、授权、取消后迟到写入、重复提交、幂等采纳、删除后不恢复、换版隔离、会话/迁移/技能/前沿追踪回归。
- 生产健康与发布检查 5/5 通过，包括论文库、模板、工作区持久化、Runner 协议兼容。
- Chrome 实际打开论文和配置后，guide_tasks 与 purpose=guide 的 Agent Run 均为 0；确认前没有触发。

本轮只实现 PDF 文字材料，最多 6 页，默认 6 个重点、可选 1–10 个；默认技能工具最多 6 次、240 秒、6000 输出 token、预算配置 $0.20。没有图像/OCR/代码工具，不把图注文字当成看图，不声称全部论文已覆盖。完整 kelip 六站、Nature 全文材料链、图表区域提取和跨论文批注复用留待后续。

## 唯一真实最小验证

使用 Chrome 中的“确认生成批注”实际触发，选择现有论文 7《Attention is All you Need》，仅第 1、9 页、最多 2 个重点。打开论文和展开配置前后任务计数均为 0；确认后只有一个任务和一个 Agent Run。

| 项目 | 实际记录 |
| --- | --- |
| 导读任务 | `ffd8b8da510f4910aacea32ea362bec7` |
| Agent Run | `bcd8742894e9427fbb3d1649877a915d` |
| 结果 | partial：仅所选 2 页，未读图、未读代码 |
| 结构化重点 | 2 条，均包含重点理由、解释及证据 |
| 原文投影 | 4 个唯一匹配的文本引文高亮；2 处 block 证据保存为页级笔记 |
| 费用 | CLI 估算 `$0.13426625`，非核实账单 |

真实结果同时包含精确引文与整块说明，因此界面显示“部分引文已高亮，另有页级证据”；不把整个重点误称为无法定位，也不把整块说明画成精确高亮。该显示修正另加 1 项服务端测试通过，后端通过的相关测试合计 159 项（原 158 + 新 1）。后续界面检查复用该结果，没有再次调用模型。

最终 Chrome 验收观察到导读、原文高亮、页边标记、点击标记展开解释、输入框触发建议；刷新后仍只有 1 个任务和 1 个 Run。另修复侧栏在组件挂载前已恢复 tab 时未同步的问题，增加恢复导读页的回归测试。截图保存于本地交付目录《手动触发导读与批注.png》。
