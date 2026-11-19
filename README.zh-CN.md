# Firework

**通过现有智能体与 Skills 发现、阅读和管理研究资料的工作台。**

[English](README.md) · [文档目录](docs/README.md) · [后续计划](docs/ROADMAP.md) · [反馈问题](https://github.com/FallrainKing/Firework/issues)

Firework 将论文库、PDF 阅读与智能体会话放在同一工作区。平台管理资料、账号、会话、任务与证据；阅读、总结、审查、比较和前沿报告交给现有 Claude Code 智能体，通过可扩展 Skills 执行。

## 功能

- 阅读起始工作台：最近阅读、领域分类、任务模板、搜索与导入。
- 多论文标签、可调三栏与阅读恢复：左侧辅助阅读，中间原文，右侧关联会话，保存位置、布局和草稿。
- 多渠道论文库：PDF 上传、arXiv、DOI、公开 URL；分类、状态、图文卡片和全文补充。
- 可延续的任务会话：原生会话映射、执行进度、取消、用量与估算费用。
- 明确触发的 Skill 导读与批注：用户确认后生成总结、重点和解释，核验原文证据后渲染。
- 前沿追踪：领域、关键词、作者或团队，发现论文与开源项目，去重、时间线报告和批准入库。
- 动态 Skills：上传 ZIP、预检、安装、分类、版本、启停与最小验证。
- 讨论输入：模板、原文选区和图片；图片理解需要真实视觉能力。
- 独立账号空间：数据库、文件、私有技能、向量与原生会话隔离；公开注册关闭，当前仅 primary admin 可登录。

打开论文、切换标签、选择模板或预览图片不会自动运行研究模型。发送请求、确认生成或启用调度才会创建相应任务。

统一知识条目、跨任务长期记忆、OCR/图像导读及完整六站精读材料链仍未完成，详见 [当前状态](docs/STATUS.md) 与 [后续计划](docs/ROADMAP.md)。

## 架构

Vue 3 / TypeScript 前端连接 FastAPI。SQLite 保存业务与身份数据，Qdrant 配合 bge-m3 提供语义检索；宿主私有 Runner 对接现有 Claude Code 和已注册 Skills。当前 Runner 协议为 **5**。

## 自托管

需要 Docker/Compose、Python 3.12+、可用的 Claude Code CLI、嵌入模型缓存，以及用于生产登录的 HTTPS 入口。开发前端使用 Node 24，生产前端在 Docker 内构建。

```sh
git clone https://github.com/FallrainKing/Firework.git
cd Firework
cp .env.example .env
```

启动前须完成：

1. 配置实际 HTTPS Origin，保留生产 Secure Cookie。
2. 修改 Compose 中原部署使用的 `100.64.0.7` 网卡绑定。
3. 准备约 2.3 GB bge-m3 缓存；新机器首次下载需关闭离线模式。
4. 配置宿主 Runner 的路径、模型和权限；仅启动容器不能使用智能体。
5. 在准备好的虚拟环境交互初始化管理员，再启动服务。

```sh
.venv/bin/python -m app.auth.bootstrap init-admin
docker compose up -d --build
```

完整步骤见 [环境与部署](docs/enviroment.md)、[认证](docs/AUTHENTICATION.md) 和 [开发指南](docs/DEVELOPMENT.md)。使用方法见 [用户指南](docs/USER-GUIDE.md)。公网统一使用应用网页登录，不再有旧 Basic Auth 密码弹窗。

## 文档与贡献

[文档目录](docs/README.md) 汇总当前架构、接口、Skills、备份恢复与开发说明。欢迎提交问题和范围明确的改进；代码变更附上对应验证和文档更新。

不要提交 `.env`、凭据、私钥、论文、运行数据或备份。部署目录和服务中仍保留 `research-assistant` 标识，用于兼容现有实例。

项目尚未添加项目级许可证；仓库公开不表示已授予开源许可。第三方组件保留各自许可证。
