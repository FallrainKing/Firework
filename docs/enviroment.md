# 当前开发与运行环境

记录日期：2026-11-17；工作台/部署信息补充于 2026-11-18（Asia/Shanghai）。文件名沿用请求中的 `enviroment.md`。

本文件用于后续开发交接。只记录环境和配置位置，不保存密钥、密码、令牌或认证文件内容。基础环境版本保留原记录；本轮重建了前端镜像，完成前端测试、服务冒烟与浏览器阅读/图片输入验证。

## 1. 服务器与项目

| 项目 | 当前信息 |
|---|---|
| SSH 用户与地址 | `f@100.64.0.7` |
| SSH 连接 | `ssh -i ~/.ssh/id_ed25519_1026 f@100.64.0.7` |
| 项目目录 | `/home/f/research-assistant` |
| 操作系统内核 | Linux `7.0.0-38-generic` |
| 架构 | `x86_64` |
| Python | `3.12.3` |
| 虚拟环境 | `/home/f/research-assistant/.venv` |
| Docker | `29.10.0`，build `fdd4b8e` |
| Docker Compose | `v5.7.1` |
| Claude Code CLI | `2.1.322` |
| Claude CLI 路径 | `/home/f/.local/bin/claude` |

SSH 私钥只引用调用端路径，不属于项目文件，也不应复制或提交到仓库。

## 2. Git 状态与交付文档

2026-11-18 阅读工作台更新：

- 当前交付分支：`feat/vue-reading-workbench`，从另一智能体重构后的 `ac86b9c` 建立。
- 前端：Vue 3 + TypeScript + Vite + Pinia；生产沿用 Docker 内 Node 24 构建；本机 Node 26 测试需要 `NODE_OPTIONS=--no-experimental-webstorage`，避免原生 localStorage 与 jsdom 冲突。
- 本轮未变更后端迁移、Runner 服务及其模型配置，仅读取状态和执行一笔最小图片验证。
- 发布前保留镜像：`research-assistant-app:before-reading-workbench-20261118`；执行了已有数据备份脚本。
- 本轮为服务器本地 Git 提交，未远程推送；具体提交号见 Git 日志。
- 历史 `feat/reading-workbench-tabs` 和 `11d7efa` 属于前一轮原生页面交付，不能代表当前 Vue 架构。

项目根目录的交接文档：

- `架构.md`：整体架构、接口、数据模型和部署结构。
- `任务设计和实现的流程与未实现.md`：实现过程、已有验证证据、未验证和未实现事项。
- `enviroment.md`：当前环境与运维入口。

以下原有运维文件不纳入本轮提交：

- `ops/public-access-credentials.txt`
- `ops/tunnel.log`
- `ops/tunnel.sh`

不要使用无差别的 `git add .` 将认证资料或日志意外提交。

## 3. 服务部署

采用现有 Docker Compose 配置运行：

| 服务 | 职责 |
|---|---|
| `app` | FastAPI API、静态 Web、管理数据与任务 |
| `qdrant` | 原文文本块的向量索引 |
| `backup` | 数据库、文件、向量与原生会话备份 |

已有容器名称：`research-assistant-app-1`、`research-assistant-qdrant-1`、`research-assistant-backup-1`。

app 容器内服务端口为 `8000`，宿主机映射为 `127.0.0.1:8600` 和 `100.64.0.7:8600`。容器内通过 `http://qdrant:6333` 访问 Qdrant。

公共入口为 [https://paper.matchesai.vip](https://paper.matchesai.vip)，沿用原有 HTTPS 与访问认证。凭据不记录在本文中。

当前架构按单 Web worker、单 Runner 部署设计，不应直接扩展为多个 worker 或副本而不处理队列、数据库启动清理及定时调度的一致性。

## 4. 数据与模型缓存

宿主机 `data/` 挂载到 app 容器的 `/app/data`。

```text
data/
  app.db                  SQLite 数据库
  papers/                 原始论文 PDF
  imports/                待处理上传文件
  attachments/            图片附件
  hf/                     Hugging Face 本地模型缓存
  qdrant/                 Qdrant 持久数据
  agent/
    runner.sock           私有 Runner Unix Socket
    internal-token        内部导入认证令牌，不提交 Git
    sessions/             原生任务工作目录
    claude-config/        本项目 Claude 原生会话存储
    runs/                 工具执行记录
```

- SQLite 使用 WAL，迁移由 `app/migrations/` 自动应用。
- 当前本地嵌入模型为 `BAAI/bge-m3`，使用 CPU。
- Compose 默认设置 `HF_HUB_OFFLINE=1`，利用已有缓存，避免启动时联网探测和限流等待。
- 首次下载或有意更新模型时才调整离线设置；缓存环境不能直接照搬为一台新服务器已经具备的条件。
- Qdrant 镜像在 Compose 中按 digest 固定，避免浮动标签改变存储版本。
- 图片目录为宿主机运行用户所有，目录权限 `700`、文件权限 `600`，使宿主机 Runner 能读取上传附件。

## 5. 现有智能体环境

Runner 由用户级 systemd 服务管理：

```text
服务名：research-agent-runner
服务文件：/home/f/.config/systemd/user/research-agent-runner.service
工作目录：/home/f/research-assistant
启动模块：agent_runner.server:app
运行方式：.venv/bin/python -m uvicorn
通信方式：data/agent/runner.sock
```

宿主机 Socket 路径为 `/home/f/research-assistant/data/agent/runner.sock`，app 容器内路径为 `/app/data/agent/runner.sock`。

模型与认证配置从宿主机 `/home/f/.claude/settings.json` 读取。项目不另存一份 API 密钥。

模型选择顺序：

1. 显式 `RESEARCH_AGENT_MODEL`。
2. 当前 Claude 配置的 `ANTHROPIC_MODEL`。
3. 当前 Claude 配置的默认 Sonnet 模型。
4. 代码中的兼容回退值；不应把它视为已确认可用的模型。

图片可通过 `RESEARCH_AGENT_VISION_MODEL` 单独覆盖。最近实际读取到的配置模型为 `qwen4-max[1M]`；模型配置会变化，不应将此名称重新硬编码进服务文件。原服务固定旧模型名的设置已经移除。

执行模型为后台任务 + SSE 进度 + 可取消（2026-11-18）：Runner 并发 `RESEARCH_AGENT_CONCURRENCY` 默认 2，队列上限 8；护栏按 Skill 配置（chat/搜索 6 回合/1024 token/120s/$0.10，导入 6/2048/180s/$0.20，阅读/审查/比较 30/8192/无硬超时/$1.00）。各 Skill 另有工具和调用次数限制。CLI 费用估算不等同于网关账单。

## 6. 前端与业务入口

- 主工作台：`app/web/index.html`、`app/web/workbench/`。
- Vue 工作台：`frontend/`（Vue 3 + Vite + TS），根路径 `/`；开发 `cd frontend && npm run dev`（proxy 指向 8600），测试 `npm test`，构建 `npm run build` 后拷贝 `dist/` 到 `app/web/`（Docker 多阶段构建自动完成）。`app/web/vendor/`（PDF.js）保留在仓库。
- 阅读页面：`app/web/reader.html`、`app/web/reader/`。
- 论文管理兼容页面：`app/web/manage.html`。
- 搜索与导入：`app/web/discover.html`。
- 内置 PDF.js：`app/web/vendor/pdfjs/`，版本 `6.5.438`。
- Skill 注册表：`app/agent/catalog.py`。
- Skill 说明：`skills/<skill>/SKILL.md`。

前端为 Vue 工作台，开发需要 Node（服务器已装 v24）与 `frontend/` 的 npm 依赖；生产由 Docker 多阶段构建，无需宿主手动构建。

## 7. 备份与回退位置

备份脚本为 `ops/backup.sh`，输出到项目 `backups/`，默认保留 14 份。备份容器配置为 Asia/Shanghai，每日 02:00 执行。

备份范围包含 SQLite、Qdrant 快照、原始论文、待处理上传、图片附件和本项目原生会话。附件目录加入脚本后的最终备份演练尚未继续执行，不能把配置完成等同于已验证恢复。

本轮改造前的快照目录：

```text
/home/f/research-assistant-change-backups/workbench-20261117-213912/
```

其中保存了代码和数据库快照，以及修改前的 `research-agent-runner.service`。旧 app 镜像保留为：

```text
research-assistant-app:pre-workbench-20261117
```

回退需要同时考虑代码、数据库迁移、原始文件、向量和原生会话；不要直接用旧数据库覆盖新增草稿、附件和执行记录。

## 8. 后续使用的命令

以下仅供交接参考，本次没有执行这些检查或重新发布。

```bash
cd /home/f/research-assistant

# 查看服务
systemctl --user status research-agent-runner
docker compose ps

# 测试：后续明确安排验收时使用
HF_HOME="$PWD/data/hf" HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m pytest -q -p no:cacheprovider

# 发布代码：确认需要发布时使用
docker compose build app backup
docker compose up -d app backup
systemctl --user restart research-agent-runner
```

当前提交的最终回归、运行镜像对应版本和备份恢复验证仍以《任务设计和实现的流程与未实现.md》的待办为准。本文件不是新增的验收通过报告。


## 2026-11-19 前沿追踪发布补充

- 服务器代码目录仍为 `/home/f/research-assistant`；发布分支 `release/frontier-workbench-20261119`，功能提交 `50e9eb1`。
- 宿主 Runner 与应用同步升级到协议 3，继续复用原模型配置，没有新增 API 密钥。
- 新增迁移 `0012_frontier.sql`，身份回填与候选、报告、项目、审批记录保存在现有 SQLite。
- 真实验证主题 ID 为 1，周期保持暂停；仅执行过一次真实追踪，未批准生产候选。
- 发布前 SQLite 备份：`/home/f/.local/state/research-assistant/backups/before-frontier-20261119-162623/app.db`。原 `backups` 目录对宿主用户不可写，本次使用宿主私有状态目录备份。
- 回退镜像 `research-assistant-app:before-frontier-20261119`；回退需同步应用与 Runner 协议。
- 详情见《前沿追踪实现与验收记录》。

- Markdown 生产依赖新增固定版本 `marked@18.2.1` 与 `dompurify@3.4.18`，依赖锁定在前端 package-lock.json，随 Docker Node 24 构建打包，无新增外部 Markdown 服务。

## 2026-11-19 导读与批注更新

- 发布代码基于 `cf8f62f`，功能提交 `5dac0d7`；功能分支 `feat/skill-reader-guides`，生产发布分支仍为 `release/frontier-workbench-20261119`。服务器本地提交，未推送远端。
- Runner 协议 **4**；用户级 `research-agent-runner` 与 app 已同步更新。
- 新迁移 `0013_reader_guides.sql`，资料位置不变；导读保存在现有 SQLite，不另建模型服务。
- 新默认技能 `paper_guide`：最多 6 次工具、240 秒、6000 输出 token、预算参数 $0.20；仅用户确认执行，未新增收费调度。
- 部署前备份：`/home/f/.local/state/research-assistant/backups/before-reader-guides-20261119-185306/app.db`；回退镜像 `research-assistant-app:before-reader-guides-20261119`。
- 回退需同步旧应用与 Runner 协议；迁移采用增加字段/表方式，不直接删除新导读或旧阅读记录。
- 验证：前端 180 项、后端相关 158 项通过，构建及现有发布检查 5/5 通过。真实验证与功能边界见《Skill导读与批注实现验收》。
