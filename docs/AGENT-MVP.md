> 后续版本已升级为任务会话与原生恢复，当前操作请参阅 [TASK-SESSIONS.md](TASK-SESSIONS.md)。本文保留最小版本历史说明。

# Agent MVP：交互、数据库与搜索最小闭环

日期：2026-11-17。新首页使用现有 Claude Code；复杂论文处理后续逐步迁移。旧功能保留 `/legacy.html`，暂未改写旧处理链路。

## 架构

网页 → `/api/agent/runs` → SQLite `agent_runs` → Unix socket → 宿主 Claude CLI → 已注册 Skill → 只读 MCP 搜索工具 → 结果/工具来源/用量落库 → 网页轮询。

没有新增模型账号或把密钥复制到网页。Runner 每次从宿主 Claude 现有配置中仅读取 Anthropic 连接环境；使用 `--bare --restricted --tools '' --strict-mcp-config`、独立任务目录和关闭原生会话持久化。普通交互没有工具，论文检索只开放对应只读工具。历史上下文由数据库提供最近两轮已成功交互。

## 使用

- 首页 `/`：选择科研对话、搜索论文库或搜索 arXiv，然后提交。
- 论文库：直接查询已有论文，不触发模型调用。
- 任务与搜索：按问题/回答查找历史，打开已有结果不重复调用。
- 原有功能：导入、精读、比较、笔记保留旧入口。

目前是个人单用户版本，访问控制沿用现有入口。不要将没有鉴权的宿主应用端口额外开放公网。

## 限额与费用

- 默认使用现有配置可用的 `deepseek-latest`，没有新建 API key。
- 一次一个 Agent；队列最多 8；同一会话同时只允许一个任务。
- 每次 CLI 输出上限 1024 tokens，最多 4 turns，每任务最多 2 次搜索工具调用，运行超时 120 秒。
- CLI `--max-budget-usd 0.10` 仅作为附加限制。自定义提供商的计价未知，**不能认为这是实际账单硬限额**。
- `usage_json` 保存实际返回的 input/output/cache token；`cli_estimated_cost_usd` 单独标注为未经核实的 CLI 估算。
- 不自动重试模型调用；相同 request_key 返回已有任务，避免网络重发重复消耗。
- arXiv 每次最多 2 条结果，不下载 PDF。主 API 出现瞬时错误时只做一次官方站点回退，不额外调用模型；外部来源仍可能超时。

## 运维

Runner 使用用户级 systemd 服务，启动文件位于 `ops/research-agent-runner.service`：

```bash
mkdir -p ~/.config/systemd/user ~/research-assistant/data/agent
chmod 700 ~/research-assistant/data/agent
cp ops/research-agent-runner.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now research-agent-runner
systemctl --user status research-agent-runner
journalctl --user -u research-agent-runner -n 30
```

已验证服务器 f 用户 `Linger=yes`，服务不依赖当前 SSH 会话。Socket 在 `data/agent/runner.sock`；私有目录权限 700，既有 app 容器通过已有 data 挂载访问，不新增宿主监听端口。

应用保持 Compose 单 worker 部署。新增 `0003_agent_runs.sql` 为增量迁移，不改旧 papers/notes。API 重启将未完成任务明确标 failed，用户手动重试；本 MVP **不实现持久化排队恢复或自动重放**。不能增加 Web workers 而不先实现跨进程租约。

仅重建应用：

```bash
docker compose build app
docker compose up -d --no-deps app
curl -fsS http://127.0.0.1:8600/api/agent/status
```

不要把 `/health` 的常量返回当作智能体连通检查。`/api/agent/status` 检查 Runner 与 DB，但不会发起模型请求，不能证明提供商当下认证/额度一定可用。

## 测试

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agent_mvp.py
HF_HOME="$PWD/data/hf" HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

新增测试覆盖任务落库、用量、搜索记录、幂等/冲突、输入验证、离线失败、历史上下文、只读 SQL、重启状态、MCP 协议/权限、拒绝无真实工具响应的伪搜索、arXiv 传输回退。全部测试使用 fake 模型，不消耗真实额度。

真实验证已执行：CLI 极小探针、库内 MCP 搜索、应用交互落库、网页 arXiv 搜索和刷新历史恢复。网页 arXiv 首轮超时被如实保存为失败；修复冗余请求参数和回退后成功。验收任务记录保留，不删除失败证据。

MCP stdio 与 arXiv 参数参考官方文档：
- https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- https://info.arxiv.org/help/api/user-manual.html

## 回滚

基线源码和 SQLite 在线备份：`~/research-assistant-change-backups/20261117-152447/`。未修改论文 PDF。

旧镜像保留为 `research-assistant-app:pre-agent-20261117`。优先回退 app 镜像或源码，并保留新增表和验收记录；旧代码可忽略这些增量表。停止 Runner 可用 `systemctl --user stop research-agent-runner`。不要未经核对用旧数据库覆盖新任务记录。

## 后续再做

完整 Skill Registry、取消 API、真实持久化 worker/恢复、用户权限、流式输出、证据精确页码、完整阅读/审查/知识记忆等均未包含在此最小版本。旧版引用页码问题仍存在，新库内搜索明确标注 legacy 未核验页码。
