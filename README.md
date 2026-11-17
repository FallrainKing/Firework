## Agent 最小交互版本（2026-11-17）

新首页已接入服务器已有 Claude Code：科研对话、论文库检索、arXiv 检索，结果和 token 用量保存 SQLite。原有导入/精读/比较页面位于 `/legacy.html`。

运行、限额、测试与回滚见 [docs/AGENT-MVP.md](docs/AGENT-MVP.md)。本阶段先验证链路，复杂科研 Skills 后续完善。

# 个人 AI 科研助手（research-assistant）

个人论文库 + RAG 问答：上传 PDF / 导入 arXiv / 批量导入文件夹 → bge-m3 向量检索 → LLM 带页码引用的中文问答。Web UI 为免构建原生 JS 单页应用。

## 部署（Docker Compose，3 步）

1. 安装 Docker Engine 与 Compose 插件（本仓库 `ops/install-docker.sh` 可在 Debian 系主机一键安装）。
2. `cp .env.example .env`，填入 `LLM_PROVIDERS` 各条的 `api_key`/`model`（`LLM_FAST`/`LLM_STRONG` 指向其中条目名）。**`.env` 含密钥，永不提交。**
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

依次验证 `/health`、上传 fixture PDF、问答（answer 与 citations 非空）、批量导入 job done；任一步失败退出码 1。全程幂等，可重复运行。

## 本地开发与测试

```bash
python -m venv .venv
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest        # 51 tests
```
