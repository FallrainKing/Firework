# 备份与恢复

更新：2026-11-21，依据 `ops/backup.sh` 与 `ops/restore.sh`。备份必须覆盖身份、研究数据库和资源；单独 SQLite 快照不能代替完整备份。

## 1. 备份范围

| 内容 | 备份文件或范围 |
| --- | --- |
| 管理员研究数据库 | `app-YYYYMMDD.db` |
| 身份、登录会话与审计 | `identity-YYYYMMDD.db` |
| 独立账号数据库与私有资源 | `accounts-YYYYMMDD.tar.gz`，单管理员也生成空归档 |
| 技能原包与展开资源 | `skills-YYYYMMDD.tar.gz` |
| PDF、暂存、附件、头像 | 对应日期的资源归档 |
| 原生智能体会话 | agent-sessions 日期归档，含 legacy 与自定义连接目录 |
| 连接加密主密钥 | 默认管理员 runner-secrets 日期归档；账号 Key 随 accounts 归档；外部挂载 Key 单独管理 |
| 向量 | 各 collection 的 `qdrant-*-YYYYMMDD.snap` |

SQLite 使用在线快照；账号归档中的数据库也来自在线备份，不依赖活跃 WAL 副本。每类本地备份默认保留 14 份，向量按 collection 分别保留。

```sh
# 在已部署项目目录执行；backup 容器可访问 Compose 内部 Qdrant。
docker compose exec backup /ops/backup.sh
```

同日再次运行会复用同日期文件名。需要多个发布前快照时，另存带时间的私有目录。Qdrant 不可达时脚本可能跳过向量快照，因此退出成功不等于向量完整；核对日志、文件和每个账号对应 collection。

## 2. 恢复准备

1. 在独立环境演练，选择与目标代码、迁移和 Runner 协议兼容的备份。
2. 核对同日身份库、账号归档、管理员数据库、技能和实际使用的资源/向量全部成套，不混用日期。
3. 暂停会触发任务的调度，确认在途任务，停止所有业务写入：

   ```sh
   systemctl --user stop research-agent-runner
   docker compose stop app backup
   ```

4. 维护环境需有 `sqlite3`、`tar`、`curl`、目标目录写权限和正确的文件属主。

身份库必须与同日账号归档配套。当前已有身份库但备份缺失身份时，脚本拒绝混合恢复；资源归档是否可选不代表业务引用可以缺失。

## 3. 执行恢复

先设置维护环境可达的 Qdrant 地址，再明确执行：

```sh
DATA_DIR=./data \
QDRANT_URL="${RESTORE_QDRANT_URL:?请先设置恢复环境可达的Qdrant地址}" \
  sh ops/restore.sh ./backups YYYYMMDD --confirm
```

Compose 默认不向宿主发布 Qdrant 6333。可在能访问 Compose 网络的维护环境执行，并核对目录挂载；不要为恢复将 Qdrant 暴露到公网。

脚本先解包和检查 SQLite 完整性、账号工作区、私有技能、PDF、附件与头像引用；验证失败时不替换正式资源。成功后，原管理对象移入 `data/restore-rollback-时间戳/`，向量快照上传至 Qdrant，恢复的浏览器会话撤销。

HF 缓存、Qdrant 数据目录和不属于管理对象的无关文件不会作为普通业务资源删除。宿主 legacy 配置由维护者单独管理；个人连接的加密数据库和默认主密钥属于本项目备份，外部挂载主密钥必须单独成套恢复。

## 4. 恢复后验证

```sh
systemctl --user start research-agent-runner
docker compose up -d app backup
```

待健康后，按 [认证说明](AUTHENTICATION.md) 签发短期维护会话并执行零模型冒烟，不能直接用匿名请求测试私有接口。

然后登录核对论文/PDF、批注、Skills 版本、原生会话、附件、头像、追踪报告及检索。恢复撤销了旧会话，需要重新登录。确认完整前保留 rollback 目录，不在首次检查后立即清除。

## 5. 失败处理

- 备份失败：检查 `backups/backup.log`、容器日志和实际文件，不能只看退出状态。
- 恢复前校验失败：修正备份集后重试，不绕过校验。
- 替换后失败：保留 rollback 目录与现场，按其中旧数据库和文件回退；同时核对向量恢复状态。
- 发现孤立资源：先核对数据库引用、版本和审计，不直接删除。

当前具备隔离备份/恢复测试，但未完成生产全量恢复演练。具体部署的备份位置和回退镜像见 [环境与部署](enviroment.md)。

文件版本补充：papers 归档包含所有 `blob-{sha256}.pdf`，数据库包含文档、版本、默认指针和批注关联。恢复新增检查每个 file_objects.storage_key 对应原件是否存在，包含非默认版本和补充材料；缺失则在替换正式资源前失败。旧备份没有 file_objects 表时保持兼容。

## Runner 连接密钥与原生会话

启用个人连接后，管理员的默认主密钥随 runner-secrets-YYYYMMDD.tar.gz 归档，独立账号密钥随 accounts 归档。自定义连接的 agent/connections 目录随 agent-sessions 归档。归档权限为私有；连接数据库和密钥是成套恢复资源。

恢复前检查有连接记录的工作区具备对应 32 字节主密钥；外部 FIREWORK_RUNNER_MASTER_KEY_FILE 不由脚本归档，必须另行恢复原文件。缺失主密钥时不要新建随机文件替代。恢复脚本只校验文件结构，重启后还需验证实际解密。不要将包含主密钥的备份公开或放入 Git。
