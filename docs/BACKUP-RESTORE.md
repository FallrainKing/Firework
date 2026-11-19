# 备份与恢复操作说明

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

1. 先停止应用与备份容器，避免恢复过程中产生新写入：

   ```sh
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
   DATA_DIR=./data QDRANT_URL=http://localhost:6333 \
     sh ops/restore.sh ./backups YYYYMMDD --confirm
   ```

   脚本会先解包到临时目录并检查：

   - SQLite `integrity_check`。
   - 每个 `skill_versions.storage_key` 对应的展开目录。
   - 每个 `skill_imports.archive_hash` 对应的不可变原包。
   - 用户资料引用的头像文件。

   任何引用缺失都会在修改正式目录前失败。恢复成功后会上传 Qdrant 快照，并将旧状态移动到 `data/restore-rollback-时间戳/`。

4. 重启服务后验证：

   ```sh
   docker compose up -d app backup
   curl http://localhost:8600/health
   ```

5. 在界面中确认技能版本、历史会话、运行记录、审计记录、头像和设置均可读取，再删除 rollback 目录。

## 失败处理

- 备份阶段失败：不会标记恢复完成；先查看 `backups/backup.log` 与容器日志。
- 恢复前校验失败：正式 `data/` 未被修改，直接修正备份集后重试。
- 恢复后数据库校验失败：保留 rollback 目录，按其中的旧数据库和文件手工回退。
- 发现孤立资源：先不要删除。使用同日 SQLite 与资源归档核对 `skill_versions`、`skill_imports` 和 `user_profile.avatar_storage_key`；只有无法被任何版本、导入或资料引用且不参与审计追溯时，才可另行归档处理。
