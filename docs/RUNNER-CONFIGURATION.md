# Runner 连接、额度与会话配置

更新：2026-11-21。当前实现参考，协议 **7**、业务迁移 **0019**。使用操作见 [usage](usage.md#2-配置模型与任务额度)，系统上下文见 [架构](架构.md)。本文件取代早期完整目标方案；未实现目标集中到 [后续计划](ROADMAP.md)。

## 1. 已实现资源

| 资源 | 存储与界面 | 生效范围 |
| --- | --- | --- |
| 模型连接 | runner_connections；模型连接页 | 账号私有，一个连接暂对应一个模型 |
| 默认连接 | runner_connection_settings | 仅新会话；既有会话保持绑定 |
| 额度预设及修订 | runner_budgets、runner_budget_revisions | 本次选择或账号默认，提交 Run 时冻结数值 |
| 默认额度 | runner_budget_settings | 后续创建的任务，含导读/追踪 |
| 会话连接绑定 | conversations.runner_connection_json | 固定连接、修订、模型与角色补充要求 |
| 执行与诊断 | agent_runs.execution_policy_json、diagnostics | 无密钥快照、原因、用量、工具及部分输出 |

当前没有独立 Model、Role、ExecutionProfile 或通用 MCPServer 配置资源；角色只是连接上的补充提示字段。Skills 继续使用已有注册表，MCP 继续使用内置 research 工具代理。

## 2. 连接字段与约束

| 字段 | 当前约束 |
| --- | --- |
| name | 1–80 字符，保存时去掉首尾空格 |
| base_url | HTTP(S) 根地址，禁止用户名、密码、query、fragment 和空白；执行默认只允许公网 HTTPS |
| model | 准确模型标识，1–150 字符，运行时显式传入 CLI |
| auth_type | api_key 或 bearer 二选一 |
| api_key | 新建必填；1–4096 字符单行文本；编辑省略时保留；响应不回显 |
| vision | unknown / declared_yes / declared_no；未声明支持时拒绝附图任务 |
| context_window | 4096–1000000，仅声明，不是精确输入 token 硬限制 |
| role_prompt | 最多 6000 字符，不增加工具或材料权限 |
| enabled、revision | 启停与乐观修订控制 |

复制不复制 Key；更改地址或鉴权方式要重填 Key。字段声明和本地预检不代表服务可达、视觉、1M 或计费已验证。纯 OpenAI 协议需要兼容网关，当前没有自动转换。配置依据见 [连接请求模型](../app/runner_config/connection_schemas.py)。

## 3. 额度与执行精度

优先级：显式 Run 额度 → 账号默认 → Skill 原额度。新预设由 [budgets.py](../app/runner_config/budgets.py) 定义，原策略由 [catalog.py](../app/agent/catalog.py) 和动态 Skill 版本策略提供。

| 参数 | 取值 | 执行方式 |
| --- | --- | --- |
| max_turns | 1–100 | CLI 推理轮次参数 |
| max_output_tokens | 256–32768 | CLI 单次输出环境参数 |
| max_calls | 0–100 | research MCP 代理计数 |
| timeout_s | 30–7200 秒 | Runner 执行超时 |
| cost_mode | disabled / cli_estimate_guard | 关闭时不传金额参数 |
| max_budget_usd | 开启时大于 0、最多 100；关闭时 null | CLI 估价守卫，不是服务商账单硬限额 |

标准预设为 24 轮、8192 单次输出 token、24 次工具、1800 秒，无金额守卫。快速/深度预设见 [使用指南](usage.md#任务额度)。原账号默认不被自动改成新预设，原 Skill 的金额限制仍可能生效。

结构化导读至少需要三个专用工具和 4096 单次输出 token，额度预检会校验兼容性；增加额度不增加工具权限。累计输入/输出 token、每次模型请求预算和全账号实际账单账本尚未实现。

## 4. 凭据与环境

[connections.py](../app/runner_config/connections.py) 用 AES-GCM 加密凭据，随机 nonce，附加认证数据绑定工作区和连接 ID。默认 32 字节主密钥为工作区 `auth/runner-master.key`，创建权限 0600；可用 `FIREWORK_RUNNER_MASTER_KEY_FILE` 指定部署方提供的现成密钥。

Web 在提交内部执行时解密，凭据通过私有 Unix Socket 临时交给 Runner，Runner 不访问加密主密钥。自定义运行使用白名单基础环境、所选鉴权及模型；不加载宿主 Claude 设置，也不受宿主 RESEARCH_AGENT_MODEL 覆盖。配置目录按账号、连接和修订隔离。

MCP 工具子进程移除模型鉴权变量。当前 Key 在进度与结果落盘前替换，不进入 argv、配置快照或正常 API 响应；没有原始 stderr 调试包。宿主进程仍由可信维护者管理，不能将应用隔离表述为操作系统或容器隔离。

目的地址检查在执行前进行；私有/保留地址和 HTTP 需维护者在 Runner 的 `FIREWORK_RUNNER_ALLOW_PRIVATE_HOSTS` 中明确列出主机。该检查不等同于完整网络出口策略。

默认主密钥纳入备份；外部挂载密钥另行备份。丢失原密钥后不能用随机新文件恢复既有凭据。见 [备份恢复](BACKUP-RESTORE.md)。

## 5. 会话与修订语义

- 原管理员可继续使用 legacy 宿主连接；独立账号必须配置自己的连接，没有宿主 Key 回退。
- 新会话首轮可显式选连接，否则使用账号默认；已有会话不随默认变更切换。
- 当前连接只保存最新配置/凭据，修改或停用会使旧修订不可继续调用。需要新会话；完整历史连接版本与受控会话迁移尚未实现。
- Web 和 Runner 启动任务前均检查当前连接状态、修订和快照。队列中旧修订失效时明确失败，不偷偷使用新 Key。
- 配置不兼容或版本不匹配不提交模型调用。任务中断不自动重跑；“重新编辑”是用户主动创建后续执行的入口，不是已实现的追加额度续跑 API。

## 6. 当前 API

均为当前账号接口，写请求需 CSRF。参数以各 schemas 与 OpenAPI 为准。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET / POST | `/api/me/runner/connections` | 列表 / 新建 |
| PATCH | `/api/me/runner/connections/{ident}` | 编辑，提交 expected_revision |
| PUT | `/api/me/runner/connections/default` | 设置新会话默认连接 |
| POST | `/api/me/runner/connections/preflight` | 检查本地配置，不调用模型 |
| GET / POST | `/api/me/runner/budgets` | 列表 / 创建额度 |
| PATCH | `/api/me/runner/budgets/{ident}` | 编辑自定义额度，保存修订 |
| PUT | `/api/me/runner/budgets/default` | 设置账号默认额度 |
| POST | `/api/me/runner/budgets/preflight` | 结合 Skill 检查有效限制 |
| POST | `/api/agent/runs` | 可附 connection、budget 引用，各含 id/revision |
| GET | `/api/agent/runs/{run_id}` | 既有运行详情及 diagnostics |

同名请求键但不同配置引用会返回 409。连接校验错误不回显原始敏感输入。内部 Runner 的连接凭据字段不属于浏览器 RunCreate 接口。

## 7. 诊断与待实现能力

diagnostics 包含结束原因、CLI 子类型、有效额度、连接/额度快照、模型、Skill 来源、费用估算及部分输出状态。已区分金额、轮次、超时、连接不可用、协议不匹配及中断；CLI 金额不视为已核实费用。

模型目录发现、最小真实能力探测、独立角色/Profile、通用 MCP 管理、请求级用量账本、会话分支、事件回放和调试包、凭据轮换服务、Runner 容器化仍待实现。设计参考 CC Switch 的配置分区，但当前没有导入其完整配置或切换宿主机设置的功能。
