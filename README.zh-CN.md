# Firework

**通过现有智能体与 Skills 发现、阅读和管理研究资料的工作台。**

[English](README.md) · [使用指南](docs/usage.md) · [系统架构](docs/架构.md) · [文档目录](docs/README.md) · [后续计划](docs/ROADMAP.md)

Firework 将论文库、PDF 原文、批注与研究会话放在同一工作区。平台负责资料与任务管理，Claude Code 通过固定版本的 Skill 执行阅读、比较、导读和前沿发现。

当前功能基线：业务迁移 **0026**、身份 schema **3**、Runner 协议 **12**、Zotero 插件 **0.1.4**。已实现范围与验证边界见 [当前状态](docs/STATUS.md)。

完整的文档地图、历史需求完成度和待补框架见 [项目总览与需求核对](docs/PROJECT-AUDIT.md)（2026-11-22 核对）。

## 主要功能

- 阅读起始工作台，提供最近论文、领域分类和任务模板。
- 多论文标签、可调整三栏：辅助阅读、PDF 原文、关联智能体会话；恢复页码、缩放、布局和草稿。
- PDF/arXiv/DOI/公开链接导入、研究检索、个人分类树重命名/移动/回收站恢复；卡片显示图片、题名、作者/单位及摘要。
- 正文和补充材料的不可变版本，默认版本选择，以及原件、带批注 PDF、批注 Markdown 下载。
- 持久会话、选区、模板、图片、Enter 发送、进度、取消和基础诊断。
- 明确触发的结构化导读与批注，保存重点、解释、理由和可追溯引文；打开论文不会自动生成。
- 前沿主题、多来源发现、去重、堆叠时间线报告与审批入库；间隔任务默认先暂停。
- Skills ZIP 预检、分类、版本、启停和资源管理；安装不执行任意脚本。
- 账号独立的模型连接、加密 Key、模型/能力声明、角色补充要求和可配置额度。
- Zotero 10.0.6–10.x 插件手动双向书目、分类、标签和 PDF 交换，不调用研究模型。
- 独立账号研究数据库、文件、向量集合和运行空间；当前公开注册关闭，默认仅原管理员登录。

统一知识库、跨任务长期记忆、OCR/完整图像导读、通用 MCP 配置中心、执行方案和 Runner 容器化仍待实现。视觉、1M 和计费预检只是配置检查，不代表真实能力验证。

## 使用顺序

1. 登录后，在用户菜单 → **模型连接** 配置 Anthropic Messages 兼容 API；原管理员也可保留已有连接。
2. 在 **任务额度** 选择默认预设。新预设可关闭 CLI 金额守卫，但仍保留轮次、输出、工具和时长限制。
3. 导入一篇 PDF，从左侧论文进入阅读，先发送一个小问题，再按需启用导读、比较或追踪。
4. 已有会话绑定连接；连接修订或更换服务商后新建会话，历史记录保留。

保存配置、查看论文和下载既有批注不调用研究模型；普通导入、发送任务、确认导读和启用调度可以产生模型用量。完整操作见 [usage.md](docs/usage.md)。

## 架构与安装

```text
浏览器工作台 → FastAPI / 认证与账号工作区
                   ├─ SQLite / PDF / 附件 / Skills
                   ├─ bge-m3 / Qdrant
                   └─ 私有 Socket → 宿主 Runner → Claude Code / 模型 API
                                                   └─ 受限 research MCP 工具
```

前端为 Vue 3/TypeScript，后端为 FastAPI/Python。Compose 提供 app、qdrant、backup，Runner 是单独的宿主用户服务；只启动容器不能运行智能体。当前为单 Web worker，尚非多副本或每账号容器架构。

```sh
git clone https://github.com/FallrainKing/Firework.git
cd Firework
cp .env.example .env
```

启动前需准备 Python 3.12+、Docker/Compose、Claude Code CLI、模型缓存及实际 HTTPS Origin；调整仓库中的固定端口/网卡、路径和服务模板，再交互初始化管理员。生产保留 Secure Cookie，Key 不放普通 `.env`。完整步骤见 [环境与部署](docs/enviroment.md) 和 [开发指南](docs/DEVELOPMENT.md)。

## 文档与贡献

| 文档 | 内容 |
| --- | --- |
| [使用指南](docs/usage.md) | 模型、额度、导入、阅读、追踪、Zotero 和下载 |
| [系统架构](docs/架构.md) | 部署、模块、数据模型与执行边界 |
| [Runner 配置](docs/RUNNER-CONFIGURATION.md) | 已实现参数、修订、凭据和接口 |
| [认证](docs/AUTHENTICATION.md) · [备份恢复](docs/BACKUP-RESTORE.md) | 账号、安全与恢复 |
| [接口](docs/API.md) · [路由清单](docs/API-ROUTES.md) · [Skills](docs/SKILLS.md) | 开发契约 |
| [状态](docs/STATUS.md) · [后续计划](docs/ROADMAP.md) | 当前范围和未完成工作 |

欢迎通过 Issues 提交问题。变更需说明触发条件、实现范围、验证和未覆盖项，并更新对应文档。旧阶段记录通过 Git 历史查阅，不继续维护重复方案。

不要提交 `.env`、凭据、私钥、研究数据、维护会话或备份。部署目录与服务仍保留部分 `research-assistant` 标识。项目尚未声明顶层许可证；公开仓库不等于已授予开源许可，第三方组件遵循各自许可证。

## 外部智能体与执行方案

设置中可管理执行方案、模型目录及内置 MCP 权限，并签发外部智能体专用授权。下载通用论文操作 Skill 后，可由其他兼容智能体查询和修改论文、读取 PDF 页面、管理批注；不调用服务器模型。见 [完整接入设计](docs/EXTERNAL-AGENT-API.md)。
