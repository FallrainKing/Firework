# 项目文档目录

更新：2026-11-19。本次增加认证与账号隔离，基于 `e25954e`；业务迁移至 0013，独立身份 schema 1，Runner 协议 5。

## 当前维护文档

| 文档 | 用途 |
| --- | --- |
| [认证与多账号](AUTHENTICATION.md) | 登录/注册限制、隔离、初始化和安全恢复 |
| [使用指南](USER-GUIDE.md) | 添加论文、阅读、导读、会话、图片、追踪和技能管理 |
| [系统架构](架构.md) | 当前职责、代码目录、数据、接口边界和执行链 |
| [环境与部署](enviroment.md) | 当前环境与新机器部署差异、运行与排障 |
| [开发指南](DEVELOPMENT.md) | 开发环境、测试、变更与发布流程 |
| [接口说明](API.md) | 业务 API、状态、幂等、证据和错误处理 |
| [完整路由清单](API-ROUTES.md) | 从当前应用 OpenAPI 提取的 HTTP 路由 |
| [Skills 开发](SKILLS.md) | ZIP 结构、工具权限、版本与导读接入 |
| [项目状态](STATUS.md) | 已实现能力、最近验证和当前限制 |
| [后续计划](ROADMAP.md) | 未完成事项、建议顺序和验收条件 |
| [备份恢复](BACKUP-RESTORE.md) | 成套备份、停写、恢复与回退 |
| [变更记录](CHANGELOG.md) | 最近代码提交与能力变更 |

根目录的 `架构.md`、`enviroment.md` 和任务说明保留为兼容入口；正文以本目录维护文档为准，不再维护重复副本。

## 专项设计和验收证据

- [导读批注实现验收](Skill导读与批注实现验收.md)：已实现接口、唯一真实最小验证及成本。
- [导读批注接口设计](Skill驱动导读批注接口设计.md)、[功能策划](自动导读与智能批注功能策划.md)：包含未来规划，当前能力以实现验收为准。
- [前沿追踪设计](前沿追踪与论文库导航设计方案.md)、[实施计划](前沿追踪实施计划.md)、[实现验收](前沿追踪实现与验收记录.md)。
- [发布一致性修复记录](release-consistency-fix-2026-11-19.md)、[早期阅读导入验收](reader-imports-acceptance-2026-11-17.md)。
- [早期 Agent MVP](AGENT-MVP.md)、[任务会话方案](TASK-SESSIONS.md)：历史实现背景，具体接口和额度以当前文档/代码为准。
- [导读 JSON Schema 设计参考](contracts/paper-guide-v1.schema.json)、[示例](contracts/paper-guide-v1.example.json)。运行时权威模型为 `app/reader/guides/schemas.py`，通过其 JSON Schema 注册工具。

## 历史材料

重整前的主说明、状态和环境副本保存在 [归档说明](archive/2026-11-19-before-handbook/README.md)。`superpowers/` 保留早期设计与阶段计划，其中的旧模型网关、旧页面、验收数字和执行安排均不是当前承诺。

维护规则：功能变化同步更新状态、架构或对应指南；运行事实标日期；示例与真实验收分开；未执行的测试或恢复演练不标通过。完整接口清单可从运行实例 `/openapi.json` 重新生成，并核对 `/docs`。
