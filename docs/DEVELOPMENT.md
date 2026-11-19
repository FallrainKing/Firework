# 开发与发布指南

更新：2026-11-19，适用于当前 Firework 版本。目录结构见 [架构](架构.md)，服务器安装见 [环境与部署](enviroment.md)。

## 1. 开发环境

后端需要 Python 3.12+，依赖按仓库 requirements 安装；CPU torch 先安装，避免误拉 CUDA 构建。前端推荐与镜像一致使用 Node 24，执行 `npm ci` 保持 lockfile。

```sh
python3.12 -m venv .venv
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pytest
npm --prefix frontend ci
npm --prefix frontend run dev
```

前端开发代理指向 `127.0.0.1:8600`；远程后端需先准备本地转发或调整开发代理。当前 Compose 不向宿主发布 Qdrant 6333；若在宿主启动 Python API，需单独提供可达的 QDRANT_URL，不能假设默认 localhost 可用。

独立启动后端前设置隔离 DATA_DIR，避免测试写入生产库；需可用的嵌入模型缓存和 Qdrant。仅改前端可直接使用既有后端，不必启动第二个 app worker。

## 2. 代码变更路径

- 页面与交互放 `frontend/src/`，沿用组件、store、API 封装，不重新引入旧静态页面或 iframe。
- 业务接口按 `router → service → repository` 组织，Pydantic 校验请求，统一 ServiceError。
- 智能内容通过 Skill 与 Runner 完成；业务层负责材料、校验、管理、事务与渲染。
- 新增数据库字段用新的顺序迁移，不改已经应用的 0001–0013。升级前验证旧库数据仍可读。
- 修改工具或执行协议同时核对 app 与宿主 Runner；新工具须登记白名单，不能靠 Skill 文本绕过权限。
- Markdown 统一使用 `frontend/src/shared/markdown.ts`；原始文本存储、渲染后清理，不将任意 HTML 当作可信内容。

## 3. 验证

前端：

```sh
npm --prefix frontend test
npm --prefix frontend run build
```

若本机 Node 26 的原生 localStorage 与 jsdom 冲突，可用 `NODE_OPTIONS=--no-experimental-webstorage` 执行测试；该兼容选项不作为生产启动配置。

后端相关回归示例（使用隔离 fixtures；本组不调用真实 Agent 模型）：

```sh
HF_HOME="$PWD/data/hf" HF_HUB_OFFLINE=1 .venv/bin/python -m pytest   tests/test_auth_accounts.py tests/test_reader_guides.py tests/test_reader_imports.py   tests/test_workbench.py tests/test_runner_jobs.py tests/test_frontier.py   tests/test_agent_mvp.py tests/test_skills_registry.py tests/test_db_migrations.py   tests/test_task_sessions.py tests/test_release_smoke.py   tests/test_route_surface.py tests/test_app_health.py -q
```

模型缓存类测试仍可能加载本地嵌入模型；缺缓存时先处理依赖，不能把未运行说成通过。变更范围涉及解析器/备份等时再选择对应测试，完整测试可用 `.venv/bin/python -m pytest -q`。

运行中服务的五步冒烟：

```sh
AUTH_SESSION_FILE=/tmp/research-auth-smoke.json .venv/bin/python scripts/smoke_test.py
```

检查健康、论文库、模板、工作区读写/恢复、Runner 协议，不发起模型调用。真实执行应单独小范围验证，记录 Run ID、材料范围、工具、结果、费用估算与缺口；不要在每次刷新或重复冒烟时调用模型。

## 4. 当前回归重点

- 打开论文、切标签、选择模板或配置不会误触发收费任务。
- Enter 发送、中文输入法确认、图片预览移除与上下文绑定正确。
- 文件版本、真实引文、坐标与任务身份可核验；歧义只做页级提示。
- 重复请求不重复收费或重复入库；失败、取消、迟到提交不覆盖有效结果。
- 导读/翻译失败记录可移除；删除标记不因刷新恢复；采纳副本可编辑且不被新导读覆盖。
- 来源失败/截断明确，审批保留证据，不把发现当作精读。

## 5. 提交与发布

1. 先读取适用协作说明和 Git 状态，使用独立分支/工作区；保留用户已有修改。
2. 按范围测试，运行 `git diff --check`，逐项添加目标文件；不使用无差别提交运行目录。
3. 代码和对应状态/接口/架构文档同步提交，说明测试范围与未验证项。
4. 部署前确认无在途任务，暂停相关调度，保存成套备份和旧镜像。
5. 构建候选镜像，同步 app/Runner，零模型冒烟与必要界面核对通过后完成发布。

文档修改通常无需重建镜像或重启服务。仅提交 Git 不等于推送远端；只有明确执行 push 才说明已推送。当前 pyproject/package 版本仍为 0.1.0，不能用它替代实际 Git 提交和 Runner 协议判断版本。

文档改动检查本地链接、命令示例、源码引用和改动范围；涉及业务代码时执行对应测试，不以文档检查代替功能验收。

认证默认开启。旧业务单元测试可显式构造 create_app(authentication=False)，认证/隔离测试必须使用默认工厂并真实执行中间件；不得将测试参数作为生产开关。维护冒烟文件的签发与清理见 [认证说明](AUTHENTICATION.md)。

本项目 Git 提交身份为 `fallrain <fallrainking@gmail.com>`。远程默认分支为 `main`；提交前核对目标分支与远程状态，不使用旧提交编号作为现行部署基线。
