# 认证、多账号与数据隔离

更新：2026-11-21。实现位于 `app/auth/`、`app/core/workspaces.py` 和宿主 Runner；当前业务迁移 0019、独立身份库 schema 2、Runner 协议 **7**。

## 1. 当前开放范围

- 沿用当前站点管理员账号及密码，初始化为唯一 primary admin。
- 登录页 `/#/login`；注册页 `/#/register` 已建立，表单禁用，注册 API 始终返回 403。
- 当前 `RESEARCH_AUTH_ADMIN_ONLY=1`。只有 primary admin 可以登录，管理员创建或启用的普通账号也受此发布限制。
- 管理员可创建账号、启停、重设普通账号密码；创建默认停用。管理界面只提供身份和状态，不提供进入其他账号研究空间的入口。
- 公网只使用应用网页登录；旧网关 Basic Auth 已关闭，避免浏览器弹窗后再次登录。管理员账号沿用原站点凭据。HTTPS 与应用会话认证保持启用。

当前不支持公开自助注册、邮件找回、邀请注册、MFA、共享资料库或跨账号协作。

## 2. 隔离方式

采用独立工作区，避免所有业务表仅依赖分散的 owner_id 过滤：

| 对象 | 管理员原有空间 | 新账号空间 |
| --- | --- | --- |
| 业务数据库 | data/app.db | data/accounts/{随机工作区ID}/app.db |
| PDF/附件/头像/自定义技能 | data 中的原位置 | 对应账号工作区内的目录 |
| 向量集合 | chunks | chunks_{工作区ID} |
| Agent 原生会话/工作目录/事件 | data/agent | 对应工作区/agent |
| 模板、批注、导读、前沿、审批、草稿、调度 | 原数据库 | 各自数据库 |
| 身份与会话 | data/auth/accounts.db 中集中管理，不经业务接口公开散列/令牌 | 同一身份服务，关联不同随机工作区 |

原有论文、会话、文件和向量均保留为管理员资料，不复制到新账号。每个业务请求从有效服务端会话选择工作区；客户端提交的账号/工作区头不能切换数据空间。数字 ID 相同也只解析到当前账号内的实体。

WorkspaceManager 复用只读模型权重和 Qdrant 客户端，但创建不同 collection、SQLite 连接及后台上下文；当前仍使用单 Web worker。私有 Runner 使用分开的 JobEngine 数据与 CLI 原生配置目录，所有账号共用并发上限和队列总上限。通用内置 Skill 可共用代码资源，私有安装、配置和版本引用独立。

内部工具使用当前工作区的令牌、Run、材料/会话绑定；伪造其他账号工作区头但使用自己的令牌会被拒绝。普通账号不能访问管理员 API；管理员的研究接口同样只选择管理员自己的工作区。

这是同一可信服务器进程内的应用和存储隔离，不是为每账号部署容器/操作系统沙箱。宿主机运维权限和备份由可信维护者管理。个人模型连接与凭据保存在各账号工作区，普通账号不能使用原管理员的 legacy Key；连接加密与运行边界见 [Runner 配置](RUNNER-CONFIGURATION.md)。

## 3. 登录与会话

- 密码采用每次随机盐的 PBKDF2-HMAC-SHA256，600,000 次，不存明文。
- 会话令牌为随机不透明值，身份库仅存其 SHA-256；生产 Cookie 为 `__Host-research_session`，Secure、HttpOnly、SameSite=Strict、Path=/、无 Domain。
- 会话最长 12 小时；登录轮换当前浏览器旧会话，退出撤销当前会话；修改密码/重设/启停通过版本号使旧会话立即失效。
- 写请求要求会话 CSRF Token，并检查 Origin/跨站来源；登录只接受允许来源的 JSON 请求。
- 登录节流持久化：每账号标识 15 分钟最多 10 次、每来源地址最多 40 次；密码验证并发有上限。现有反向代理可能汇聚来源地址，公开开放前需审查可信代理地址策略。
- 认证错误统一处理，参数校验不会回显密码输入；安全审计记录动作和账号 ID，不保存密码或会话令牌。
- 私有 API、PDF、附件、头像、事件和接口文档都受认证约束，响应不进入共享缓存。健康接口只有状态，匿名会话接口不返回账号列表。

参考：[OWASP 密码存储](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)、[会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)。这里只描述实际实现，不作合规认证声明。

浏览器只在内存保存 CSRF，不将登录令牌存入 localStorage。切换账号/退出清理旧草稿缓存、主题和视图；各账号保留独立的工作区标识以恢复服务端标签。跨标签页身份改变或浏览器返回缓存会重新加载认证状态。首次管理员迁移保留旧工作区标识。

## 4. API

| 方法/路径 | 权限与作用 |
| --- | --- |
| GET /api/auth/session | 匿名可查询登录状态/开放状态；登录后返回自身身份和 CSRF |
| POST /api/auth/login | 当前允许登录的账号；签发会话 Cookie |
| POST /api/auth/logout | 已登录且 CSRF 有效，撤销当前会话 |
| POST /api/auth/password | 验证当前密码，修改应用密码并撤销所有旧会话 |
| POST /api/auth/register | 当前固定关闭，返回 403 |
| GET/POST /api/admin/accounts | 管理员查看账号元数据/创建默认停用的普通账号 |
| PATCH /api/admin/accounts/{id} | 管理员启停普通账号；不能停用 primary admin |
| POST /api/admin/accounts/{id}/password | 管理员重设普通账号密码并撤销旧会话 |

停用账号保留数据，停止已有任务并禁止后续调度；已经创建但未开放登录的账号不产生研究任务。账号管理不提供物理删除或研究数据共享。

## 5. 初始化与密码恢复

在受信任宿主的项目目录中执行。新部署先准备虚拟环境、依赖和正确的 DATA_DIR，再交互初始化管理员；已有管理员时不会覆盖：

```sh
.venv/bin/python -m app.auth.bootstrap init-admin
```

不要在现有实例重复初始化，不使用已关闭的旧入口认证挑战作为初始化前提。密码通过交互输入，不放入命令行参数、`.env` 或 Git。

忘记管理员应用密码时：

```sh
.venv/bin/python -m app.auth.bootstrap reset-admin-password --confirm
```

此操作要求两次输入新密码，并撤销全部旧会话。普通账号密码由管理员管理页重设。公网只有应用网页登录，不另设网关密码。

## 6. 部署与维护验证

应用与宿主 Runner 必须兼容协议 7。生产认证默认启用，环境变量不能切回匿名模式。`create_app(authentication=False)` 只用于显式构造隔离业务测试。

保留 `RESEARCH_AUTH_ADMIN_ONLY=1`、`RESEARCH_AUTH_COOKIE_SECURE=1`，并将 `RESEARCH_PUBLIC_ORIGIN` 设为实际 HTTPS 站点。HTTP 登录页禁用密码提交，提供配置的 HTTPS 登录入口。仅在隔离的本地 HTTP 开发环境可设置 `RESEARCH_AUTH_COOKIE_SECURE=0`，同时配置匹配的开发 Origin，使用单独的 `research_session_dev` Cookie。

以下零模型冒烟在受信任宿主执行。创建短期私有文件，完成或中断后撤销会话；输出不包含令牌：

```sh
set -eu
maintenance_dir=$(mktemp -d)
cleanup_auth() {
  if [ -f "$maintenance_dir/session.json" ]; then
    .venv/bin/python -m app.auth.bootstrap revoke-session \
      --input "$maintenance_dir/session.json"
  fi
  rmdir "$maintenance_dir"
}
trap cleanup_auth EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
.venv/bin/python -m app.auth.bootstrap issue-session \
  --output "$maintenance_dir/session.json" --minutes 5
AUTH_SESSION_FILE="$maintenance_dir/session.json" \
  .venv/bin/python scripts/smoke_test.py
```

私有维护文件最长支持 15 分钟，不是前端登录凭据，不应上传或输出内容。`ops/deploy.sh` 会自行签发、使用并清理维护会话。

## 7. 访问与恢复边界

公网由 HTTPS 反向代理提供服务，研究资料由应用会话保护。匿名登录页与登录状态查询可访问；论文、附件、头像、会话、SSE、账号管理和接口文档均受认证约束。未登录返回 401，不包含浏览器密码认证挑战。注册 API 固定返回 403。

账号数据库与研究资源需成套备份和恢复；恢复后撤销浏览器会话。详见 [备份恢复](BACKUP-RESTORE.md)。发布验证范围见 [项目状态](STATUS.md)，当前网关和回退位置见 [环境与部署](enviroment.md)。

## Zotero 设备授权

身份 schema 2 增加 10 分钟配对码和 30 天限域设备凭据。网页必须登录并通过 CSRF 核对和确认设备；插件凭一次性秘密领取令牌，服务端仅存哈希，本地使用 Zotero 的凭据服务保存。设备令牌仅适用于 `/api/zotero/device/*`，其他接口继续要求网页登录。重配同账号实例更换令牌并保留来源编号；改密、停用、撤销和到期使旧令牌失效。公开配对发起入口有持久节流，跨站来源拒绝；不暴露研究资料。

备份身份库会保留设备哈希与撤销状态。恢复历史备份后应复核并撤销不再信任的设备，避免恢复旧授权状态。插件本地 `firework-sync.json` 位于 Zotero 数据目录，含书目信息与任务恢复记录，不含设备令牌；它也应随研究资料妥善备份。
