# 项目状态总览

> 个人 AI 科研助手平台 — 规划、执行进度、里程碑与遗留项
> 更新：2026-11-17

## 一、总体规划（四阶段）

来源：`docs/superpowers/specs/2026-11-16-personal-ai-research-assistant-design.md`（已批准的设计文档）

| 阶段 | 内容 | 状态 | 计划文档 |
|---|---|---|---|
| **P1** | 骨架 + LLM 网关 + 论文库（含批量导入） | ✅ 已验收 | `plans/2026-11-16-p1-skeleton.md` |
| **P2** | 论文精读（六维解读/对比矩阵/笔记） | ✅ 已验收 | `plans/2026-11-17-p2-deep-reading.md` |
| **P3** | 前沿雷达 + 钉钉推送（每日日报/周报） | 🔲 待开工 | 待编写 |
| **P4** | AI 导师（知识地图/学习计划）+ 备份恢复演练 | 🔲 待开工 | 待编写 |

执行方式（已确立）：子代理驱动开发——每任务"独立实现者 → 独立评审员 → 修复循环（≤5 轮）→ 范围化复审"，阶段末最强模型全分支终审 + 修复波。

## 二、已完成功能清单

### P1（骨架 + 网关 + 论文库）
- Web 工作台（手机可用，原生 JS 免构建 SPA）
- 论文入库三通道：PDF 上传 / arXiv 链接 / 文件夹批量导入（进度可见、跨源判重、元数据补全）
- 全文检索问答：中文提问 → 带原文页码引用；跨语言（中文查英文论文）
- LLM 网关：GLM + DeepSeek 双提供商、fast/strong 分档、故障转移、thinking 块解析、空文本自动换路、`llm_usage` 记账
- 向量层：本地 bge-m3（CPU）+ Qdrant
- 自动备份：每日 02:00 SQLite + Qdrant 快照，保留 14 份
- 无人值守基础：开机自启、合盖不休眠、qdrant healthcheck、启动自愈重试（10×10s）、任务清扫、迁移事务化
- 公网入口：https://paper.matchesai.vip（见 `ENVIRONMENT.md`）

### P2（论文精读）
- 六维深度解读：背景/创新/架构/公式/实验/局限（后台 job，分钟级，进度轮询）
- 章节级解读（逐节落库，重跑幂等、失败保留旧成果）
- 多篇对比矩阵：2-5 篇 + 可选问题，五维对比 + [P{n}|页码] 引用溯源（markdown 表格转义兼容）
- 笔记系统：用户批注（annotation/chat_summary）+ AI 产物（section_analysis/six_dim）CRUD
- 无编号标题解析修复（OpenVLA/Flow Matching 型论文）+ 表格表头伪节护栏
- 安全 markdown 渲染器（先转义后解析，XSS 双断言验证）
- 网关硬化：`LLMExhaustedError` 归因（per-provider attempts → 502）、`busy_timeout=5000`、迁移事务化

## 三、验收证据（摘要）

| 验收项 | P1 | P2 |
|---|---|---|
| pytest | 71 全绿 | 117 全绿 |
| 真实论文 | Diffusion Policy 上传 15s 问答带页码 | BAKU 六维解读（公式维含 L1/注意力/FiLM） |
| 对比/推送 | 批量导入 4 篇无重复、重启持久化 | "VLA/DP/FM 区别" 4087 字符矩阵 + 13 跨页引用 |
| 端到端 | 冒烟 4/4 | 冒烟 7/7（含 XSS 探针与真实 LLM 步骤） |

## 四、遗留项（已知、非阻塞）

**P3 开工前建议处理**
- （终审已修 4 项 Important：迁移原子化、重跑保留旧笔记、LLMExhaustedError→502、compare 独立连接）

**可带走的 deferred minors（择机处理）**
- qa 路由网关穷尽仍笼统 500（需单独 catch LLMExhaustedError 归 502）
- 前端：面板归属竞态（轮询期间切论文）、409/轮询失败后按钮需手动刷新恢复
- smoke 探针在失败路径可能残留（try/finally 清理）
- import_jobs 表无清理机制（长期重跑线性增长）
- 解析器：相邻无编号标题首节被拒、全大写论文标题成首节、词内冒号正则口径、小数点切句
- compare：paper_ids 无去重上限细节（API 已限 2-5 篇）、回退 citations 无上限
- 6 号论文（BAKU）仅 5 个聚合节——无编号标题保守策略的误拒面，P3 精读质量观察点

## 五、验收期间发现并修复的真缺陷（记录价值）

1. **thinking 模型 token 饥饿**：glm-5.3 的 thinking+text 共享 max_tokens；对比任务 4096 预算被 thinking 耗尽 → text 为空。修复：预算提升（16384/32768 重试）+ 空文本守卫。
2. **glm-5.3 thinking 量随预算膨胀**（16384 预算时 thinking 3 万字符）→ 小预算稳定饥饿。根治：网关层"空文本 = 可重试故障"→ 自动故障转移到 deepseek-latest（全预算正常）。**此行为详见 `ENVIRONMENT.md`，P3 配置 fast 档时必须规避。**
