# 当前环境、部署与排障

核对日期：2026-11-20（Asia/Shanghai）；适用于 Firework 当前部署，Runner 协议 5。文件名保留原约定。只记录配置位置与非敏感状态，不记录密钥、认证内容或完整配置转储。

## 1. 当前实例

| 项目 | 已核对信息 |
| --- | --- |
| 服务器 / 项目 | `f@100.64.0.7` / `/home/f/research-assistant` |
| 系统 | Ubuntu 24.04.5 LTS，x86_64 |
| Python / 虚拟环境 | 3.12.3 / `.venv` |
| Docker / Compose | 29.10.0 / v5.7.1 |
| Claude Code CLI | 2.1.322，`/home/f/.local/bin/claude` |
| 前端构建 | Docker Node 24，多阶段构建 Vue/Vite |
| 生产分支 | `release/frontier-workbench-20261119` |
| Runner | 用户级 `research-agent-runner`，协议 5，并发 2 |
| 实际模型快照 | 本次发布冒烟报告 `glm-5.3[1M]`，以运行时状态为准 |
| 应用入口 | `127.0.0.1:8600`、`100.64.0.7:8600`，公网 `https://paper.matchesai.vip` |
| 数据 / 最新迁移 | `/home/f/research-assistant/data` / `0015_zotero_manual_sync.sql` |

远程仓库为 `https://github.com/FallrainKing/Firework.git`，默认分支为 `main`；当前服务器分支跟踪 `origin/main`。部署目录与服务名保留原标识。确认目标版本应使用当前 Git HEAD，不使用历史重写前的提交编号。

SSH 使用调用端 `~/.ssh/id_ed25519_1026`，不复制到项目。公网网关位于 root@matchesai.vip，站点配置 /etc/nginx/conf.d/paper-matchesai.conf。旧 Basic Auth 已关闭，仅保留应用网页登录；HTTPS 与反向隧道链路不变。配置快照见 `ops/paper-matchesai.conf`，回退信息见本文第 7 节。

## 2. 服务和目录

Compose：app 提供 API/SPA，qdrant 保存向量，backup 负责计划备份。app 容器内端口 8000，Qdrant 连接 `http://qdrant:6333`；宿主 Runner 通过 `data/agent/runner.sock` 与应用通信。

```text
data/
  app.db                        管理员研究 SQLite（含导读、追踪与审批）
  auth/accounts.db              身份、会话、节流与审计
  accounts/{工作区ID}/            独立账号数据库、私有资源与原生会话
  papers/ imports/ attachments/  原始 PDF、暂存、会话图片
  skills/archives/              不可变 ZIP 原包
  skills/packages/              已安装版本资源
  avatars/                      用户头像
  hf/                           bge-m3 模型缓存
  qdrant/                       向量存储
  agent/
    runner.sock                 私有通信入口
    internal-token              内部工具认证文件
    claude-config/ sessions/    本项目原生会话及工作目录
    runs/                       执行事件与工具记录
```

容器与 Runner 共用文件，需对齐宿主 UID/GID。上传目录和技能资源按宿主用户准备，不能用全目录放宽权限来解决读取失败。

## 3. 配置来源

| 配置 | 来源及规则 |
| --- | --- |
| DATA_DIR / QDRANT_URL | `app/core/config.py`；宿主默认 data / localhost:6333，Compose 内覆盖 |
| HOST_UID / HOST_GID | Compose 默认 1000，新机器按运行用户对齐 |
| HF_HUB_OFFLINE | Compose 默认 1，要求缓存已存在；首次下载用 0 |
| HF_ENDPOINT | 镜像/测试使用 hf-mirror；模型缓存挂载到容器 HF 缓存目录 |
| 模型凭据 | 现有宿主 `~/.claude/settings.json` 的 ANTHROPIC 配置，由 Runner 读取 |
| 模型选择 | RESEARCH_AGENT_MODEL → Claude 配置的 ANTHROPIC_MODEL → 默认 Sonnet 配置 → 代码回退 |
| 视觉覆盖 | RESEARCH_AGENT_VISION_MODEL；否则沿用当前模型，仍须真实支持视觉 |
| Runner 并发 | RESEARCH_AGENT_CONCURRENCY 默认 2；队列和额度另受执行器约束 |

仓库 `ops/research-agent-runner.service` 模板仍含旧的固定模型 `deepseek-latest`，不能不加核对覆盖当前运行服务。新装时删除该固定覆盖，或按明确需要设置模型；不从文档猜测供应商配置。

## 4. 新机器部署

以下是部署步骤，文档整理时没有对现有服务器重新安装或切换配置。

1. 准备 Python 3.12+、Docker/Compose、可工作的 Claude CLI 和现有宿主配置；模型凭据不写入 app 的 `.env`。
2. 在项目创建虚拟环境、先安装 CPU torch，再安装 requirements：

   ```sh
   python3.12 -m venv .venv
   .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
   .venv/bin/pip install -r requirements.txt
   cp .env.example .env
   ```

3. 核对 `.env` 中 UID/GID、项目路径；修改 Compose 内 `100.64.0.7` 绑定为本机实际网卡地址，或仅保留 loopback。当前地址不是通用安装默认。
4. 新机器没有缓存时以 `HF_HUB_OFFLINE=0` 首次启动，等待 bge-m3 下载与初始化；下载时间取决于网络，不保证固定分钟数。缓存位于 data/hf；之后恢复离线启动。已有缓存部署不重复下载。
5. 安装用户 Runner。服务模板默认项目在 `~/research-assistant`；其他路径须同步改 WorkingDirectory、ExecStart/ExecStartPre 和 Socket。先核对并调整模板中的模型覆盖，再安装：

   ```sh
   mkdir -p ~/.config/systemd/user
   cp ops/research-agent-runner.service ~/.config/systemd/user/research-agent-runner.service
   systemctl --user daemon-reload
   systemctl --user enable --now research-agent-runner
   ```

6. 新实例交互初始化管理员，再启动容器：

   ```sh
   .venv/bin/python -m app.auth.bootstrap init-admin
   docker compose up -d --build
   ```

启动后按 [认证说明](AUTHENTICATION.md) 执行带维护会话的零模型冒烟。首次部署 Runner/App 的启动时序可能短暂不就绪，待应用健康后再次检查协议。宿主 Runner 工具目前回调固定 `http://127.0.0.1:8600`；修改宿主端口还须修改/适配工具端，不能只改 Compose。

需要退出登录后继续运行用户服务时，按主机运维策略配置用户 linger；本次未修改系统级设置。

## 5. 现有实例升级

在 `/home/f/research-assistant` 操作：

1. 检查 Git 干净与目标提交；查询 `/api/agent/runs`，确认没有 queued/running 任务，并暂停会触发运行的相关调度。
2. 保存旧提交、镜像标签，并按 [备份文档](BACKUP-RESTORE.md) 做迁移前成套备份。在线 SQLite 备份不能替代 PDF/技能包/原生会话/Qdrant 备份。
3. 在独立工作区验证并构建候选镜像；评估增量迁移。不要通过 checkout 覆盖未提交工作。
4. 同步应用与宿主 Runner 代码，必要时重启 Runner，再替换 app。协议必须兼容，本版为 5。
5. 零模型冒烟通过后，再按需要做一次用户明确触发的小范围真实验证。页面刷新或重复测试不能额外创建收费任务。

`ops/deploy.sh` 已有备份、构建、重启和冒烟流程；默认 `DOCKER='sudo docker'`，已有 Docker 权限可设 `DOCKER=docker`。脚本不会自动检查在途任务；实际迁移由 app/core/db.py 应用所有未执行 SQL。认证版会自动创建短期维护会话用于冒烟，结束后撤销并清理文件。使用前仍须执行上述检查。

## 6. 状态与排障

```sh
# 不需要模型调用
curl -fsS http://127.0.0.1:8600/health
docker compose ps
systemctl --user status research-agent-runner --no-pager
journalctl --user -u research-agent-runner -n 60 --no-pager
docker compose logs --tail=80 app
```

私有 `/api/agent/status` 需要有效登录，不能用匿名 curl 检查；协议与工作区检查使用 [认证说明](AUTHENTICATION.md) 的完整维护冒烟流程。查看日志时不要把认证内容、完整提示或未脱敏配置贴入公开问题。`/health` 只说明应用可响应；Runner 兼容性以 `/api/agent/status` 和五步冒烟为准。

| 症状 | 检查 |
| --- | --- |
| app 启动后持续不可访问 | 模型缓存/离线配置、Qdrant 就绪、启动日志；RAG 初始化有有界重试 |
| 页面可用但智能体离线 | 宿主用户服务、Socket 挂载与权限、CLI 配置 |
| protocol 不匹配 | 应用和 Runner 是否同一代码版本、是否漏重启服务 |
| 图片或技能资源无法读取 | DATA_DIR 属主与文件权限、资源是否与 DB 记录成套存在 |
| 新页面看不到改动 | 检查实际构建镜像和 app 容器，再刷新浏览器；仅改源码不会改镜像内静态资源 |
| 任务重启后失败 | 当前会终止受影响任务，不自动重复付费；核实后手动重试 |

## 7. 当前回退资料

下列是当前实例保留的私有恢复资料，其他机器应记录自己的位置：

| 范围 | 位置或标签 |
| --- | --- |
| 完整认证改造前备份 | `backups/before-auth-complete-20261119-2248/` |
| 认证发布后成套备份 | `backups/after-auth-20261119-2250/` |
| 文件管理发布前成套备份 | `backups/before-documents-20261120/` |
| 文件管理发布后成套备份 | `backups/after-documents-20261120/` |
| Zotero 发布前成套备份 | `backups/before-zotero-20261120/` |
| Zotero 发布后成套备份 | `backups/after-zotero-20261120/` |
| Zotero 发布前应用镜像 | `research-assistant-app:before-zotero-20261120` |
| 文件管理前应用镜像 | `research-assistant-app:before-documents-20261120` |
| 改名前应用镜像 | `research-assistant-app:before-firework-20261119` |
| 认证改造前 app/backup 镜像 | `research-assistant-app:before-auth-20261119`、`research-assistant-backup:before-auth-20261119` |
| 网关单次登录修改前配置 | 网关 `/root/research-auth-gateway-backups/20261119-before-app-login-only.conf` |

切回旧应用必须同步对应 Runner，并核对迁移和身份库兼容性。不要混合不同日期的身份库与研究资源，也不要删除迁移记录或直接逆向修改数据库。恢复旧网关配置会重新启用双重登录，不能当作应用认证的替代。

完整恢复先停止 app、Runner 与备份写入，恢复后撤销旧会话并重新验证，见 [备份恢复](BACKUP-RESTORE.md)。生产全量恢复演练尚未完成。

## 8. 认证与隔离配置

认证默认强制启用。RESEARCH_AUTH_ADMIN_ONLY=1、RESEARCH_AUTH_COOKIE_SECURE=1、RESEARCH_PUBLIC_ORIGIN=https://paper.matchesai.vip；未开放注册，普通账号仍不能登录。当前实例已初始化管理员；新机器使用交互初始化，详见 [认证说明](AUTHENTICATION.md)。

新增 data/auth/accounts.db（身份、散列、会话、节流和审计）及 data/accounts/{随机ID}/（独立研究空间）；原管理员继续使用原 data/app.db、papers、agent 和 chunks 集合。新账号集合为 chunks_{工作区ID}。原资料不迁移、不复制到新账号。

旧的匿名五步冒烟在认证版会收到 401；先按认证说明签发 5 分钟私有维护会话，再设置 AUTH_SESSION_FILE 执行。生产 Cookie 只通过 HTTPS，临时维护文件只在受信任宿主使用。HTTP 本地开发可显式配置 RESEARCH_AUTH_COOKIE_SECURE=0，同时配置匹配的 RESEARCH_PUBLIC_ORIGIN；使用单独的 research_session_dev Cookie，不用于公网。

当前实例的完整备份和回退镜像见第 7 节。回退不能混合新身份库与其他日期研究库；恢复后旧浏览器会话必须撤销。


## Zotero 插件构建

本机核对版本为 Zotero 10.0.6（macOS），插件声明目标 10.0.6–10.x，实际客户端安装与配对未在发布脚本中执行。`python3 scripts/build_zotero_plugin.py` 生成 `app/web/downloads/firework-zotero-0.1.0.xpi`，Docker 构建时执行相同脚本，网站路径为 `/downloads/firework-zotero-0.1.0.xpi`。包仅包含本项目的 manifest、bootstrap 和插件实现；本地配置、凭据、队列、研究资料不进入包。

设备授权存于 `data/auth/accounts.db`（schema 2），业务映射、分类树和队列存于各账号业务库（迁移 0015）。本地 Zotero 的凭据服务保存令牌，数据目录中的 `firework-sync.json` 保存任务恢复记录；插件只主动访问配置的 HTTPS Firework，不开放本地监听端口。

本次 Zotero 功能发布为 `b97000e`，业务迁移 0015 与身份 schema 2 已在生产应用。公网插件 SHA-256 为 `80d70b3b5c29f3d547941577c4462f92ebf2c8be64dc740583519a4fef45e5e4`；线上五步冒烟、匿名隔离、设备令牌拒绝和 PDF Range 验证通过，未新增真实设备或研究运行。
