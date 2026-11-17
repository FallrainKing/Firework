# 环境与运维手册

> 服务器环境、凭据位置、公网链路、模型行为、运维 runbook
> 更新：2026-11-17

## 一、本机（科研助手宿主机）

- Ubuntu 24.04，AMD Ryzen 9 8945HX 32 线程，30GB 内存，无 GPU（全部外部 API，不需要）
- 服务：Docker Compose 三服务（app:8000 / qdrant / backup），端口发布 `127.0.0.1:8600` + `100.64.0.7:8600`
- **sudo 需密码且 AI 会话无 tty**——系统级操作需用户在自己终端执行
- 本机 ufw 开启：tailnet 入站 8600 被拦，故公网链路走 SSH 反向隧道（见下）
- docker 命令在本会话需 `sg docker -c "..."` 包裹（会话未刷新组身份）

## 二、公网入口

**https://paper.matchesai.vip** — nginx basic auth

- 账密：`paper` / 见 `ops/public-access-credentials.txt`（0600，不入 git）
- 链路：浏览器 → 阿里云服务器 nginx（泛域名证书 *.matchesai.vip，2027-02 到期）→ `127.0.0.1:18600` ←SSH 反向隧道← 本机 `127.0.0.1:8600`
- 隧道：`ops/tunnel.sh`（断线 10s 自重连；crontab `@reboot` 开机拉起；日志 `ops/tunnel.log`）
- 阿里云服务器：`ssh -i ~/.ssh/id_ed25519_1026 root@matchesai.vip`（Alibaba Cloud Linux 3，与本机同 Tailscale tailnet：服务器=corral-gateway 100.64.0.1，本机=f-thinkbook 100.64.0.7）
- nginx：`/etc/nginx/conf.d/paper-matchesai.conf`（**htpasswd 权限必须 root:nginx**，否则 500）；`client_max_body_size 64m`、`proxy_read_timeout 600s`
- 换密码：`openssl passwd -apr1 新密码` → 更新服务器 `/etc/nginx/.htpasswd-paper` → `systemctl reload nginx`

## 三、凭据与密钥

| 凭据 | 位置 | 备注 |
|---|---|---|
| LLM API keys | 本机 `.env`（0600，永不入 git） | 源：`~/.cc-switch/cc-switch.db` providers 表 |
| 钉钉机器人 token | 尚未配置（P3 需用户提供 access_token + 加签 secret） | 计划存 `.env` |
| 公网 basic auth | 本机 `ops/public-access-credentials.txt` + 服务器 `/etc/nginx/.htpasswd-paper` | |
| SSH key | `~/.ssh/id_ed25519_1026`（root@matchesai.vip） | |

## 四、LLM 提供商（实测 2026-11-17）

| 提供商 | 端点 | 模型 | 状态 |
|---|---|---|---|
| 内部网关 huoshan | `https://llm.inner.bza.edu.cn/plan`（Anthropic 兼容） | glm-5.3 / glm-5.3-flash / deepseek-latest / doubao | ✅ 当前主力 |
| DeepSeek 官方 | `https://api.deepseek.com`（Anthropic + OpenAI 双兼容） | deepseek-chat/flash/v4-pro | ✅ 备用 + fast 档主力 |
| GLM 官方 bigmodel | `open.bigmodel.cn` | — | ⚠️ 429 套餐到期，保留配置不启用 |
| OpenAI / Claude / Google 官方 | — | — | 无 key |

**当前路由**：`fast` → DeepSeek 官方；`strong` → 内部网关 glm-5.3。

### ⚠️ 关键模型行为（P3 配置必读）

1. **glm-5.3 的 thinking 量随 max_tokens 膨胀**（16384 预算实测 thinking 3 万字符；2048/4096 小预算常被 thinking 吃光 → HTTP 200 但 text 为空）。
2. **deepseek-latest（同网关）全预算正常**（thinking ~1-2k 字符）。
3. 已落地根治：网关层"空文本 = 可重试故障"→ 自动故障转移到 tier 内下一 provider（`app/llm/gateway.py`，默认开启）；reader/compare 另有模块级守卫与预算重试。
4. **P3 建议**：fast 档勿配 thinking 模型（会重演饥饿）；可用 `llm_usage` 的 `completion_tokens == max_tokens` 作饥饿监控信号。

## 五、运维 runbook

```bash
# 重建/重启（先停后起，避免迁移与旧进程并发）
sg docker -c "docker compose down app" && sg docker -c "docker compose up -d --build app"

# 全量测试 / 端到端冒烟
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke_test.py          # 7 步，含真实 LLM，幂等可重跑

# 重入库（解析器改动后）
sg docker -c "docker compose up -d --build app"
sg docker -c "docker compose exec app python scripts/reingest_all.py"

# 查看服务状态 / 隧道日志
sg docker -c "docker compose ps"
tail -5 ops/tunnel.log
journalctl --user -u ... 或 crontab -l   # 隧道由 @reboot 拉起

# 手动重启隧道
pkill -f "ssh.*18600" ; nohup ops/tunnel.sh >/dev/null 2>&1 &

# 备份位置与恢复
ls backups/                     # app-YYYYMMDD.db + qdrant 快照，保留 14 份
# 恢复演练在 P4 验收项中
```

## 六、依赖与镜像（国内网络适配）

- PyPI 直连不稳（截断/损坏）→ 一律清华源；torch 用 `--index-url https://download.pytorch.org/whl/cpu`
- HuggingFace → `HF_ENDPOINT=https://hf-mirror.com`（用户已确认）；bge-m3 已在 `data/hf` 持久化
- Docker Hub → `/etc/docker/daemon.json` 已配 1ms/daocloud/dockerproxy 镜像加速
- qdrant 镜像按 digest 固定（tag 拒拉环境的等效不可变方案）
- pip: python-multipart / pymupdf / httpx / APScheduler(P3 补装)
