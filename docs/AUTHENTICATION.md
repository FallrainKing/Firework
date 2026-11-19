# 认证、多账号与数据隔离

更新：2026-11-19。实现位于 `app/auth/`、`app/core/workspaces.py` 和宿主 Runner；业务数据库仍迁移至 0013，新增独立身份库 schema 1，Runner 协议升级到 **5**。

## 1. 本次开放范围

- 沿用当前站点管理员账号及密码，初始化为唯一 primary admin。
- 登录页 `/login`；注册页 `/register` 已建立，表单禁用，注册 API 始终返回 403。
- 当前 `RESEARCH_AUTH_ADMIN_ONLY=1`。只有 primary admin 可以登录，管理员创建或启用的普通账号也受此发布限制。
- 管理员可创建账号、启停、重设普通账号密码；创建默认停用。管理界面只提供身份和状态，不提供进入其他账号研究空间的入口。
- 现有网关 Basic 访问认证保留；应用内登录作为研究空间的认证。初始凭据相同，后续应用密码修改不改变网关认证。

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

这是同一可信服务器进程内的应用和存储隔离，不是为每账号部署容器/操作系统沙箱。宿主机运维权限、公共模型供应商配置和备份由可信维护者统一管理。

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

## 5. 初始化与恢复

以下命令在项目目录、受信任维护者终端执行。初始化只可执行一次，已有管理员时不覆盖：

```sh
# 当前部署的私有文件仅保存原入口密码；不输出文件内容
.venv/bin/python -m app.auth.bootstrap init-admin \
  --legacy-file ops/public-access-credentials.txt --legacy-username paper \
  --verify-origin https://paper.matchesai.vip
```

验证既有站点的认证挑战和凭据成功后才保存管理员散列。新环境也可不带文件参数，交互输入账号和密码。禁止把明文密码放入命令行参数、.env 或 Git。

忘记应用管理员密码时，可在服务器交互恢复，不会读取或输出原密码：

```sh
.venv/bin/python -m app.auth.bootstrap reset-admin-password --confirm
```

此操作要求两次输入新密码，撤销全部旧会话；网关入口认证独立管理。普通账号密码由管理员管理页重设。

## 6. 部署与验证

生产认证默认启用，环境变量不能切回匿名旧模式。`create_app(authentication=False)` 仅用于显式构造隔离的旧业务单元测试，不是部署开关。

应用 Compose 与宿主 Runner 必须同时升级至协议 5。保持 `RESEARCH_AUTH_ADMIN_ONLY=1` 和 `RESEARCH_AUTH_COOKIE_SECURE=1`，Origin 为现有 HTTPS 站点。未来允许普通账号时需要同步应用/Runner 配置、启用具体账号并规划网关访问策略；本次未开放。

零模型维护冒烟使用短期私有文件，不在终端打印令牌：

```sh
.venv/bin/python -m app.auth.bootstrap issue-session \
  --output /tmp/research-auth-smoke.json --minutes 5
AUTH_SESSION_FILE=/tmp/research-auth-smoke.json .venv/bin/python scripts/smoke_test.py
# 检查后撤销维护会话并删除私有文件
.venv/bin/python -m app.auth.bootstrap revoke-session --input /tmp/research-auth-smoke.json
```

完整备份增加 `identity-日期.db` 和 `accounts-日期.tar.gz`；管理员单账号时也生成空 accounts 归档。所有账号的业务库使用 SQLite 在线快照，不归档活跃 WAL 作为数据库副本；向量快照分别按集合保留。恢复前核验身份与资源成套，并使恢复的浏览器会话全部失效。

回归覆盖未登录全部私有路由、CSRF/来源/节流/过期、关闭注册、仅管理员登录、同 ID 的论文/文件/批注/草稿/会话隔离、私有 Skill/向量、Runner 原生目录/查询/取消隔离、内部工具绑定和真实 SQLite 备份恢复。研究模型调用数为 0。实际发布与验收见项目状态和变更记录。

## 7. 本次实际验收

功能提交 `79e6cb2`、HTTPS 入口修复 `b46f89e` 已发布；生产仅 1 个管理员，使用原站点凭据验证登录成功。匿名论文库/PDF/SSE/账号管理/接口文档均 401，注册 403，缺 CSRF/错误 Origin 写入 403，退出后的旧会话 401；PDF Range 206，原 9 篇论文和 1 个导读任务保留，协议 5 兼容。五步冒烟通过，维护会话已撤销。前端 189 项、后端相关 189 项通过；模型调用 0。

生产安全 Cookie 仅在 HTTPS 使用；HTTP 登录页已禁用密码提交并引导到配置的 HTTPS 登录地址。Chrome 已核对该提示及关闭注册的页面，不在 HTTP 页面发送真实凭据；公网管理员认证由实际 HTTPS/本地受信任请求验证。隔离测试使用临时多账号，生产未创建额外测试账号。备份与回退位置见 [变更记录](CHANGELOG.md)。
