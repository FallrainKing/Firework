# 研知 · Research Assistant

面向个人研究的论文发现、管理与阅读工作台。平台管理论文、文件、会话、技能和任务；总结、翻译、审查、比较及前沿报告由服务器已有 Claude Code 智能体通过 Skills 执行。

当前文档核对日期：2026-11-19，代码基线 `13956f9`，数据库迁移至 `0013`，Runner 协议 **4**。发布状态见 [项目状态](docs/STATUS.md)，所有文档入口见 [文档目录](docs/README.md)。

## 已有功能

- 阅读起始工作台：最近阅读、领域分类、任务模板、论文搜索与导入。
- 多论文标签与可调三栏：左侧导读/目录/批注/高亮/译文/信息，中间 PDF，右侧智能体会话；保存阅读位置、布局与草稿。
- 会话管理：每个任务保留原生会话映射，可召回和延续；异步执行、进度、取消及用量记录。
- 明确触发的导读批注：输入框选择“自动批注”或“阅读论文”，修改要求并确认后才执行。打开、刷新、切换论文不会自动调用导读 Skill。
- 论文库：分类、状态、图文卡片、作者单位、摘要及全文补充；支持 PDF、arXiv、DOI、公开 URL 添加。
- 前沿追踪：设定领域、关键词、作者/团队等，调用现有智能体发现论文和 GitHub 项目，去重后形成时间线报告，批准后入库。
- 动态技能库：上传 ZIP、预检、安装、分类、版本、启停、模板与最小验证；本地用户资料、头像和偏好。

当前为单用户部署。论文库、会话与批注已持久化；统一知识条目、跨任务长期记忆、OCR/图像导读和完整 kelip 六站材料链尚未实现。详见 [后续计划](docs/ROADMAP.md)。

## 开始使用

已部署实例访问现有站点；操作步骤见 [使用指南](docs/USER-GUIDE.md)。只有书目信息时先补充 PDF，不进入空白阅读任务。模板选择、图片预览和批注配置本身不会执行模型；发送、确认生成或启用定时执行才会产生任务。

## 部署与开发

本项目需要两部分同时就绪：Docker Compose 中的 app/Qdrant，以及宿主机的私有 Runner。仅启动容器不代表智能体可用。

1. 准备 Docker/Compose、Python 3.12+、现有 Claude CLI 配置及宿主虚拟环境。
2. 按 [环境与部署](docs/enviroment.md) 配置路径、监听地址、模型缓存、Runner 和权限。
3. 构建应用并执行零模型冒烟检查。

```sh
# 已配置宿主 Runner、模型缓存与 .env 的现有环境
# 升级前先确认无执行中任务并备份，完整步骤见部署文档
docker compose up -d --build app
.venv/bin/python scripts/smoke_test.py
```

仓库 Compose 中的 `100.64.0.7` 是当前服务器地址；新机器需修改端口绑定。Compose 默认 `HF_HUB_OFFLINE=1`，新机器没有 bge-m3 缓存时须按部署说明完成首次下载。

```sh
# 前端独立开发；后端仍需在 127.0.0.1:8600 提供 API
cd frontend
npm ci
npm run dev
npm test
npm run build
```

Python 安装、隔离测试与发布步骤见 [开发指南](docs/DEVELOPMENT.md)。生产前端由 Docker 多阶段构建，无需在服务器额外安装 Node；构建镜像使用 Node 24。

## 文档

| 内容 | 入口 |
| --- | --- |
| 功能操作与常见问题 | [使用指南](docs/USER-GUIDE.md) |
| 架构、代码目录、数据模型、任务流 | [系统架构](docs/架构.md) |
| 当前服务器、部署、排障和回退 | [环境与部署](docs/enviroment.md)、[备份恢复](docs/BACKUP-RESTORE.md) |
| API 分组与调用规则 | [接口说明](docs/API.md)、[完整路由清单](docs/API-ROUTES.md) |
| ZIP 技能扩展与导读契约 | [Skills 开发](docs/SKILLS.md) |
| 已实现范围、验证和遗留项 | [项目状态](docs/STATUS.md)、[后续计划](docs/ROADMAP.md)、[变更记录](docs/CHANGELOG.md) |

文档不保存认证内容。`.env`、`data/`、`backups/`、私钥、运行日志和公网认证文件不提交 Git。旧方案与历史验收可从 [文档目录](docs/README.md) 查找，不应直接作为当前部署步骤。
