# 备份与恢复操作说明

核对：2026-11-19 / `13956f9`，依据 ops/backup.sh 与 ops/restore.sh。本文描述操作，本轮未执行生产恢复。仅 SQLite 快照不能代替下述成套备份。

## 备份范围

`ops/backup.sh` 会成套保留以下状态：

- SQLite 数据库：技能注册表、版本引用、模板绑定、会话、运行、审计、用户资料与偏好。
- Qdrant 快照。
- 原始 PDF、导入暂存、附件。
- 原生智能体会话。
- `data/skills/archives` 中的不可变 ZIP 原包。
- `data/skills/packages` 中的展开技能版本资源。
- `data/avatars` 中的头像文件。

每类本地备份默认保留 14 份。动态技能的数据库记录、原包和展开资源来自同一天的备份，不能混用不同日期。

## 恢复流程

1. 先确认没有在途任务，暂停相关调度，停止宿主 Runner、应用与备份容器，避免恢复过程中产生新写入：

   ```sh
   systemctl --user stop research-agent-runner
   docker compose stop app backup
   ```

2. 确认要恢复的备份日期，并检查以下文件成套存在：

   ```sh
   ls backups/app-YYYYMMDD.db
   ls backups/skills-YYYYMMDD.tar.gz
   ls backups/qdrant-*-YYYYMMDD.snap
   ```

3. 显式执行恢复脚本（必须包含 `--confirm`）：

   ```sh
   DATA_DIR=./data QDRANT_URL="${RESTORE_QDRANT_URL:?请先设置恢复环境可达的Qdrant地址}" \
     sh ops/restore.sh ./backups YYYYMMDD --confirm
   ```

   当前 Compose 没有将 Qdrant 6333 发布到宿主。示例要求先设置实际可达的 RESTORE_QDRANT_URL；未设置会在执行恢复脚本前停止。可在能访问 Compose 网络的维护环境执行，并核对数据库和归档路径。不要仅为恢复把 Qdrant 暴露到公网。

   宿主运行脚本需有 sqlite3、tar、curl 等命令、目标目录写权限及正确文件属主。除脚本强制要求的数据库和技能包，还需人工核对 PDF、原生会话、附件、头像和向量快照是否成套；脚本将缺少的部分归档视为可选，不代表这些业务资源不需要恢复。

   脚本会先解包到临时目录并检查：

   - SQLite `integrity_check`。
   - 每个 `skill_versions.storage_key` 对应的展开目录。
   - 每个 `skill_imports.archive_hash` 对应的不可变原包。
   - 用户资料引用的头像文件。

   上述脚本核验的技能和头像引用缺失会在修改正式目录前失败；其他业务资源仍需人工核对。恢复成功后会上传 Qdrant 快照，并将旧状态移动到 `data/restore-rollback-时间戳/`。

4. 重启服务后验证：

   ```sh
   systemctl --user start research-agent-runner
   docker compose up -d app backup
   .venv/bin/python scripts/smoke_test.py
   ```

5. 在界面中确认技能版本、历史会话、运行记录、审计记录、头像和设置均可读取，确认数据和引用完整后，另按运维保留策略处理 rollback 目录，不在首次检查时立即删除。

## 失败处理

- 备份阶段失败：不会标记恢复完成；先查看 `backups/backup.log` 与容器日志。
- 恢复前校验失败：正式 `data/` 未被修改，直接修正备份集后重试。
- 恢复后数据库校验失败：保留 rollback 目录，按其中的旧数据库和文件手工回退。
- 发现孤立资源：先不要删除。使用同日 SQLite 与资源归档核对 `skill_versions`、`skill_imports` 和 `user_profile.avatar_storage_key`；只有无法被任何版本、导入或资料引用且不参与审计追溯时，才可另行归档处理。

## 手动备份与限制

```sh
# 在当前部署目录；由现有 backup 容器运行，内部可达 Qdrant
docker compose exec backup /ops/backup.sh
```

默认本地各类保留 14 份，同日再次运行使用同日期文件名；若需保留多次发布前快照，另存带时间的私有目录。备份脚本在 Qdrant 不可达时会跳过快照，因此退出成功不代表向量一定已备份，需核对日志和文件。

计划备份位于 backups/；最近导读发布还保留了一份私有 SQLite 快照与旧镜像，位置见 [环境文档](enviroment.md)。生产恢复前应在独立环境演练，并同步恢复对应代码、Runner 协议和资源；模型缓存可独立准备，但模型认证不属于业务数据备份。

## 认证与多账号备份

身份库单独在线快照为 identity-日期.db；独立账号目录为 accounts-日期.tar.gz，其中每个业务库先取 SQLite 在线备份，再复制资源，不依赖原 WAL 副本。管理员单账号时也保存空 accounts 归档。原管理员的 app.db、papers、skills、agent 等仍按原范围备份。向量快照按每个 collection 分别保留，避免账号数量增加后互相挤掉当日备份。

恢复身份库必须同时提供同日 accounts 归档，校验账号工作区、业务库完整性及私有技能/PDF/附件/头像引用；恢复后撤销所有浏览器会话。当前已有身份库而备份缺少身份时，脚本拒绝混合恢复。未纳入管理的无关文件、HF 缓存和 Qdrant 数据目录保留；管理对象的旧状态进入 rollback。详细入口见 [认证说明](AUTHENTICATION.md)。
