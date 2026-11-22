# 环境、部署与排障

更新：2026-11-22。当前业务迁移 0022、身份 schema 3、Runner 协议 **8**。文件名保留既有 `enviroment.md` 约定。这里只记录非敏感配置和操作，不保存密钥、登录凭据或配置转储。

## 1. 当前实例与部署边界

| 项目 | 当前配置 |
| --- | --- |
| 项目目录 | `/home/f/research-assistant`，部署账户 f |
| 仓库 | `https://github.com/FallrainKing/Firework.git`，远程默认分支 main |
| 部署分支 | release/frontier-workbench-20261119，跟踪 origin/main |
| 应用 | Compose app，容器端口 8000，宿主端口 8600 |
| 公网 | `https://paper.matchesai.vip/#/`，HTTPS 反向代理及应用网页登录 |
| Runner | 用户级 research-agent-runner，私有 Unix Socket，当前协议 8、默认并发 2 |
| 数据 | 项目 data/，主业务库 app.db，身份库 auth/accounts.db |
| 向量与缓存 | Compose qdrant、data/qdrant、data/hf |
| Zotero | 插件 0.1.4，声明兼容 10.0.6–10.x |

2026-11-22 只读核对服务器仓库提交为 `4abeb36`，app/qdrant/backup 运行，qdrant healthy、Runner active；该检查不代替完整业务冒烟。当前代码要求 Runner 协议 8。模型以所选连接或每个 Run 实际记录为准；legacy 最近状态为 glm-5.3[1M]，不能据此假定所有账号使用同一模型或已经实测 1M。

2026-11-22 首批增量已部署到 `dc7ff6e`（迁移 0020）；发布前完成成套备份，保留旧镜像 `firework-before-collection-lifecycle:20261122`。新增分类/历史导读/策略接口及浏览器核验通过，无新研究模型任务。后续文档提交不需要重建镜像。

当前 Compose 包含 `100.64.0.7:8600` 网卡绑定，服务模板包含固定项目路径和 legacy 模型覆盖。这些是现有部署参数，新机器必须修改；不是可原样复制的通用默认。

## 2. 全新安装

准备 Python 3.12+、Docker/Compose、Claude Code CLI 和模型缓存空间。前端本地开发使用 Node 24；生产由 Docker 构建。

```sh
python3.12 -m venv .venv
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

1. 设置实际 `RESEARCH_PUBLIC_ORIGIN`，生产保留 Secure Cookie；保持注册关闭和 `RESEARCH_AUTH_ADMIN_ONLY=1`，除非另有经过验证的开放方案。
2. 调整 Compose 的网卡和端口绑定、HOST_UID/HOST_GID；确认 Qdrant 从 app 网络可达。
3. 新机器没有 bge-m3 缓存时，首次有意设置 `HF_HUB_OFFLINE=0` 下载并初始化；完成后恢复离线启动，缓存保留在 data/hf。
4. 修改 [Runner 服务模板](../ops/research-agent-runner.service) 的 WorkingDirectory、ExecStart/ExecStartPre 和 Socket。模板的 RESEARCH_AGENT_MODEL 只应作为 legacy 覆盖，自定义连接忽略它。
5. 安装用户服务并交互初始化管理员：

```sh
mkdir -p ~/.config/systemd/user
cp ops/research-agent-runner.service ~/.config/systemd/user/research-agent-runner.service
systemctl --user daemon-reload
systemctl --user enable --now research-agent-runner
.venv/bin/python -m app.auth.bootstrap init-admin
docker compose up -d --build
```

既有实例不要重复初始化。密码通过交互输入，不写入命令参数或 Git。仅启动 Compose 不会启动宿主 Runner；两者都就绪后再执行维护冒烟。

管理员可保留已有 Claude 配置，也可在 Web 配置个人模型连接；独立账号必须配置自己的 API。仅在 legacy 模式使用 `~/.claude/settings.json`。不要将模型 Key 放入普通 `.env` 或用户偏好 JSON。

当前研究工具的内部回调固定为宿主 `http://127.0.0.1:8600`；改端口需同步适配工具端。Qdrant 默认不向宿主发布 6333，宿主运行 API/恢复工具时要提供实际可达地址。

## 3. 模型连接与主密钥

用户菜单 → 模型连接，入口 `/#/settings/runner/connections`。参数、API、限制与运行隔离见 [Runner 配置](RUNNER-CONFIGURATION.md)。

默认主密钥为各工作区 `auth/runner-master.key`，32 字节、创建权限 0600。可通过 Web 服务的 `FIREWORK_RUNNER_MASTER_KEY_FILE` 指定现成外部密钥文件；Runner 不需要读取这个文件。默认密钥纳入项目备份，外部挂载密钥需另行备份。

自定义连接默认仅允许公网 HTTPS。需要内网或 HTTP API 时，由维护者在 **Runner 服务环境** 配置 `FIREWORK_RUNNER_ALLOW_PRIVATE_HOSTS`，逗号分隔主机名，并重启 Runner。Web 用户不能修改该允许列表。服务模板没有自动读取所有 app `.env` 参数，需显式设置 systemd 环境或受控 EnvironmentFile。

连接修订或停用会阻止旧版本任务继续调用；缺失凭据不回退宿主 Key。角色是连接上的补充要求，不是独立角色库。上下文和视觉只是声明，不能以预检通过代替实际能力验证。

## 4. 现有实例升级

1. 核对目标提交与 Git 状态，保留无关未提交文件；确认队列无在途任务，并暂停相关调度。
2. 保存旧镜像/提交，做身份、研究资源、主密钥、原生会话和向量的成套备份。
3. 在隔离目录按范围验证并构建候选镜像；数据库只应用新的顺序迁移，不删除迁移记录。
4. 同步 app 与宿主 Runner；协议变化时重启 Runner，再更新 app。运维脚本变化时同步构建 backup。
5. 执行带短期维护会话的无模型冒烟、页面和文件检查；真实模型验证单独明确触发。

```sh
docker compose build app backup
systemctl --user restart research-agent-runner
docker compose up -d --no-deps app backup
```

以上命令应在完成检查与备份后执行。`ops/deploy.sh` 提供发布辅助流程，但不会替代人工在途任务检查；模板和脚本也需核对本机路径。仅更新文档不需要构建镜像或重启服务。

## 5. 状态与排障

```sh
curl -fsS http://127.0.0.1:8600/health
docker compose ps
systemctl --user status research-agent-runner --no-pager
journalctl --user -u research-agent-runner -n 60 --no-pager
docker compose logs --tail=80 app
```

`/health` 只说明 app 可响应。私有 `/api/agent/status` 需有效会话，Runner 兼容性通过已登录页面或 [认证说明](AUTHENTICATION.md#6-部署与维护验证) 的短期维护冒烟检查。禁止把维护会话、Key、完整环境或研究提示贴入公开日志。

| 现象 | 优先核对 |
| --- | --- |
| app 长时间不可访问 | Qdrant、嵌入缓存、离线设置与初始化日志 |
| 页面正常但 Agent 离线 | 用户服务、Socket 挂载/权限、CLI 路径及协议 |
| 更新源码后页面未更新 | 镜像是否重建、容器是否更新；文档提交与前端部署不同 |
| 自定义连接执行失败 | API 协议、目的地址、鉴权方式、模型名与当前修订 |
| 凭据无法解密 | 原主密钥、工作区和备份是否成套；不要生成随机替代文件 |
| 任务达到金额上限 | Run 实际额度快照；原 Skill 金额守卫仍可生效 |
| 重启后任务失败 | 当前中断不会自动付费重跑；先核对结果再手动决定 |
| 浏览器出现额外密码弹窗 | 网关是否残留 Basic Auth；当前仅应用网页登录 |

## 6. 插件与回退

```sh
python3 scripts/build_zotero_plugin.py
node --test plugins/zotero/tests/plugin.test.cjs
```

当前 XPI 为 `/downloads/firework-zotero-0.1.4.xpi`，更新清单由同一构建生成。安装包不含本地配置、配对令牌、恢复队列或研究资料。客户端安装、配对与实际传输由使用者确认，操作见 [usage](usage.md#9-zotero-手动双向交换)。

最近模型连接发布前的数据库快照为 `data/maintenance/before-runner-connections-20261121`，旧 app 镜像为 `firework-before-runner-connections:20261121`。这类数据库快照不等同于覆盖所有资源的完整备份，不能单独用于全量恢复。

回退需匹配 app/Runner 协议并检查数据库兼容性；完整数据恢复按 [备份恢复](BACKUP-RESTORE.md) 停写、成套恢复和验证。过期发布路径与旧插件哈希不再作为当前操作说明；历史记录通过 Git 查询。生产全量恢复演练仍未完成。

## 执行方案与外部 API 发布记录

2026-11-22：代码 `7952e47` 已部署；app 镜像重新构建、宿主 Runner 同步重启至协议 8。业务迁移 0021、身份 schema 3；旧镜像保留为 `firework-before-external-api:20261122`，发布前成套备份日志为服务器 `/tmp/firework-external-api-backup.log`。核验配置 API、13 个内置 MCP 工具、Skill ZIP、外部匿名拒绝、外键完整性与浏览器页面；不创建真实外部令牌或模型任务。

新增入口：`/#/settings/runner/profiles`、`/#/settings/integrations`；Skill 下载 `/downloads/firework-paper-ops.zip`。授权密钥与客户端环境在使用者本地配置，不写入本文档。

2026-11-22：Skill 审查修复及本机前沿报告上传代码 `a8023b9` 已发布，业务迁移 0022，身份 schema 3 与 Runner 协议 8 不变。发布前备份日志 `/tmp/firework-local-reviews-backup.log`，旧镜像 `firework-before-local-reviews:20261122`。本次仅重建/切换 app，Runner 协议未变；无活动任务时发布。线上只读验证与新授权入口核验通过，未创建真实外部授权、报告或模型任务。
