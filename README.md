# 个人 AI 科研助手（research-assistant）

论文发现/导入/分类 + 三栏 PDF 阅读工作台 + 任务会话。所有模型调用统一经服务器已有的 Claude Code（私有 Runner）；bge-m3 + Qdrant 提供原文检索。Web UI 为免构建原生 JS（Vue 工作台迁移见 `docs/superpowers/specs/2026-11-17-modular-refactor-design.md`）。

架构与接口见 [架构.md](架构.md)；环境与运维见 [enviroment.md](enviroment.md)；会话/论文库细节见 [docs/TASK-SESSIONS.md](docs/TASK-SESSIONS.md)、[docs/AGENT-MVP.md](docs/AGENT-MVP.md)。

## 部署（Docker Compose，3 步）

1. 安装 Docker Engine 与 Compose 插件（本仓库 `ops/install-docker.sh` 可在 Debian 系主机一键安装）。
2. `cp .env.example .env`（只需基础路径项；**模型凭据由宿主机 Claude 配置提供，app 无需 LLM 密钥**）。Runner 由用户级 systemd 服务 `research-agent-runner` 管理，见 enviroment.md。
3. `docker compose up -d --build`，然后浏览器打开 `http://127.0.0.1:8600`（局域网/手机为 `http://100.64.0.7:8600`，按本机网卡 IP 调整）。

注意事项：

- **首次启动需下载 bge-m3 嵌入模型（约 4GB，走 hf-mirror，5–15 分钟）**；期间容器尚未开始监听，属正常现象。模型缓存持久化在 `./data/hf`，之后升级/重建不再重复下载。
- `./data` 若由 docker 首次自动创建会是 root 属主；容器入口脚本会在启动时自动 chown 为宿主用户（`HOST_UID`，默认 1000，非 1000 用户在 `.env` 中覆盖）。
- torch 必须装 CPU 版（`--index-url https://download.pytorch.org/whl/cpu`），Dockerfile 已内置；本地 venv 安装请照 requirements.txt 顶部注释操作。

## 端到端冒烟（服务运行中）

```bash
docker compose up -d
.venv/bin/python scripts/smoke_test.py
```

依次验证 `/health`、论文库、任务模板、工作区读写、Runner 在线；**零模型调用**，任一步失败退出码 1，全程幂等。智能体执行链路用最小材料单独验证，避免重复计费。

## 本地开发与测试

```bash
python -m venv .venv
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt
HF_HOME="$PWD/data/hf" HF_HUB_OFFLINE=1 .venv/bin/python -m pytest
```

### Vue 工作台（/v2）

```bash
cd frontend
npm install
npm run dev        # 开发服务器，/api 与旧页面代理到 127.0.0.1:8600
npm test           # Vitest 组件/store 测试
npm run build      # 产物 dist/，拷贝到 app/web/v2/ 后由 FastAPI 挂载 /v2
```
