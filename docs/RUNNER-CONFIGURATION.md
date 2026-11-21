# Firework Runner 配置、Skills / MCP 与会话调试设计

日期：2026-11-21。基线：ad1053c、Runner 协议 5、已安装 Claude Code 2.1.322。
修订：已补全第 4 章前端页面、路由、表单、交互和分批验收。
状态：额度管理与个人模型连接已实现，交付边界见第 13、14 节；独立执行方案、通用 MCP 管理、额度续跑与容器 Runner 尚未实现。
目标：沿用 Claude Code 及现有研究工具，实现按用户配置、可复现执行、可解释触限、可检查会话，并与宿主机其他 Claude Code 使用场景隔离。

## 1. 引用与采用方式

| 来源 | 本设计采用的内容 | 与 Firework 的区别 |
| --- | --- | --- |
| [CC Switch README](https://github.com/farion1231/cc-switch/blob/main/README.md) | 连接、MCP、Skills、提示预设分区管理，预设与连接状态可见 | Firework 面向多用户服务器，不切换宿主机全局配置 |
| [CC Switch 配置组织](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/5-faq/5.1-config-files.md) | 数据库作为配置来源；连接参数与通用设置分离；Profile 组合资源；变更前备份 | 每个 Run 编译不可变执行快照，允许不同用户并发使用不同连接 |
| [Claude Code CLI](https://code.claude.com/docs/en/cli-reference) | 模型、显式 MCP、受限执行、原生会话与用量限额入口 | 参数是否可用仍以固定 CLI 版本和驱动测试为准 |
| [模型与上下文配置](https://code.claude.com/docs/en/model-config) | 模型名、上下文窗口、思考能力存在版本与网关差异 | 声明能力、实测能力和实际使用能力分别记录 |
| [网关兼容](https://code.claude.com/docs/en/llm-gateway-protocol) | 自定义 Base URL 必须匹配 CLI 使用的协议 | 首批直连 Anthropic Messages；纯 OpenAI 格式需显式适配网关 |
| [Claude Code MCP](https://code.claude.com/docs/en/mcp) | 显式服务器配置、工具发现、连接状态 | 保留研究材料授权与写入验证，不把外部 MCP 当成内置受信工具 |
| [MCP 2025-06-18 Transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports) | stdio 与 Streamable HTTP 的传输边界 | SSE 作为兼容项，不作为新的默认接入方式 |
| [Claude Code 监控](https://code.claude.com/docs/en/monitoring-usage) | 用量、请求、工具与错误可以建立关联 | 先使用现有事件流和工具代理；不能采集的请求级明细显示“不可观测” |
| [容器部署](https://code.claude.com/docs/en/devcontainer) | 独立运行环境、版本固定与状态持久化 | Runner 独立服务，不挂载宿主机 Claude 配置和个人目录 |

以上为组织方式和接口依据。CC Switch 的桌面全局切换、自动切换服务商、任意 stdio 命令、自动导入全部个人配置，不直接移植到多用户服务。外部项目若复用代码，应另外核验许可证并保留声明。

## 2. 当前代码与实际问题

### 2.1 已有能力，迁移时必须复用

| 模块 | 实际代码 | 保留方式 |
| --- | --- | --- |
| 独立账号与工作区 | app/auth、app/core/workspaces.py | 所有配置和会话均由服务端认证工作区定位 |
| Runner 与异步任务 | agent_runner/server.py、jobs.py | 保留队列、并发、SSE、取消、重启中断及幂等 |
| Claude 调用 | agent_runner/cli.py | 改为版本化 Driver；不重写成另一套研究智能体 |
| 会话及论文关联 | app/sessions、app/agent/repository.py | 保留 conversation ID、native_session_id、论文与草稿 |
| Skills 库 | app/skills、skills/ | 保留 ZIP 预检、分类、启停、版本哈希、资源、默认版本和审计 |
| 研究 MCP | agent_runner/tools.py | 注册为受保护的 builtin:research 服务 |
| 导入、前沿、导读 | app/imports、app/frontier、app/reader/guides | 保留材料校验、来源证据、审批与结构化写入 |
| 用量和执行记录 | agent_runs、data/agent/runs | 增加归一化事件与快照；保留历史原记录 |
| Web 设置 | frontend/src/views/SettingsView.vue | 从偏好 JSON 扩展成有字段校验的配置中心 |

只读盘点：内置启用 Skill 10 个，ZIP Skill 1 个处于归档状态，技能分类 6 个。不得在迁移时重新启用归档技能。当前只主动构造一个 research stdio MCP，工具 13 个；没有外部 MCP 注册中心。

### 2.2 写死的限制

- app/agent/catalog.py：普通任务 6 轮、1024 输出 token、120 秒、CLI 估算金额上限 0.10 美元；阅读类 30 轮、8192 输出 token、无墙钟超时、1.00 美元。
- 导读：12 轮、6000 输出 token、6 次工具、240 秒、0.20 美元；前沿：12 轮、4096 输出 token、10 次工具、240 秒、0.20 美元。
- app/skills/service.py 又维护 short/read 两份默认策略；自定义 Skill 的工具次数固定为 4，形成多处配置来源。
- agent_runner/cli.py 固定 MAX_THINKING_TOKENS=0；从宿主机 ~/.claude/settings.json 读取 ANTHROPIC_*；进程级 RESEARCH_AGENT_MODEL 优先于账号意图。
- API/Runner 提示最长 3000 字符，首次播种历史最多 40 条、每条截为 2000 字符；这些是应用限制，不代表模型上下文容量。
- 工具返回的块数、页数、资源字符数有独立限制；扩大模型窗口不会自动扩大阅读范围。
- image_blocks 会发送图片，但当前没有“该连接下的该模型确实支持视觉”的完整前置校验。
- jobs.py 丢弃 stderr，仅保存部分进度摘要；CLI 触限通常被 build_payload 归并成通用失败，难以排障。
- 当前 strict MCP 与 tools 白名单是真实边界，必须保留；不能用提高预算来绕过材料或写入授权。

### 2.3 最新失败证据与结论边界

检查时管理员工作区共 32 条 Run：19 成功、13 失败。最新三个真实任务均为 error_max_budget_usd：

| 类型 | 配置金额上限 | CLI 返回的金额估算 |
| --- | --- | --- |
| paper_guide | 0.20 美元 | 约 0.264481 美元 |
| frontier_monitor | 0.20 美元 | 约 0.260552 美元 |
| frontier_monitor | 0.20 美元 | 约 0.222410 美元 |

这是 CLI 的客户端估算，不是服务商账单。最新三次可确定被金额限制停止；不能把全部历史失败都归为同一原因。

当前 build_payload 将 cost_scope 固定标为 native_session_cumulative，CLI 每次 result 的费用/usage 范围仍需按固定版本核验，不能直接累加会话返回的累计值。

CLI 的金额检查存在调用边界与估价误差；达到阈值时停止，并不保证最后金额恰好小于阈值。最近前沿任务的累计输出超过单次 4096，也说明“单次生成输出”与“整个任务累计输出”不能混用。

本次核查未发起模型请求、未自动重试这些付费任务，也未改变运行限额。

## 3. 产品对象与配置层次

### 3.1 七类对象

| 对象 | 管什么 | 不应混入的内容 |
| --- | --- | --- |
| ProviderConnection 连接 | 地址、协议、认证引用、代理、连接状态 | Skill 提示词、全局权限 |
| ModelDefinition 模型 | 实际模型 ID、上下文、视觉、工具、推理与价格资料 | 用户真实 Key |
| RolePreset 研究角色 | 精读导师、审稿人、领域观察员的提示与输出风格 | admin/user 权限或新增工具权限 |
| SkillVersion 技能版本 | 研究步骤、材料要求、产物契约、请求的工具能力 | 自行提升预算、执行任意脚本 |
| MCPServerRevision 工具服务 | 服务器定义、工具目录、凭据引用、权限与健康状态 | 自动继承全部模型凭据 |
| BudgetPolicy 运行额度 | 单次请求、整个 Run、会话、账号、调度周期限额 | 把 1M 上下文当成单次输出额度 |
| ExecutionProfile 执行方案 | 将连接、模型路由、角色、Skills、MCP、预算组合为可选预设 | 对宿主机配置做全局切换 |

另外由管理员管理 RuntimePolicy：CLI 镜像与版本、可执行路径、并发、队列、容器资源、允许的网络与安装来源。

| RuntimePolicy 参数 | 建议初始配置 / 生效范围 |
| --- | --- |
| cli_driver / cli_version / image_digest | 固定受测版本，升级走兼容检查与发布 |
| cli_path / runtime_root / callback_base_url | 容器内路径与回调；普通用户不可填写 |
| global_concurrency / per_user_concurrency | 初始保持全局 2，每账号不超过平台允许；后续按压测调整 |
| max_active / max_queue_wait_s | 初始保持最多 8 个活动任务；等待超时不调用模型、不计作推理失败 |
| cpu_limit / memory_limit / pids_limit | Runner 与 worker 资源限制；溢出需标记 OOM/worker failure |
| heartbeat / lease_ttl / graceful_shutdown_s | 任务租约与停止策略；旧 worker 不能再次写入终态 |
| prompt_chars / attachment_bytes / material_limits | API 请求体与材料安全限制，区别于模型 token 额度；首批建议提示上限 64000 字符，预检再按实际窗口核验 |
| egress_policy / approved_mcp_templates | 私有地址例外、安装来源与工具模板由管理员控制 |
| diagnostics_retention / max_log_bytes | 有界日志与清理，研究记录和诊断记录分别管理 |

以上数值是迁移建议，只有明确发布后生效；不因页面保存而热修改正在运行的进程。

### 3.2 配置合并与生效

1. 系统提供连接模板、能力描述和建议预算。
2. 用户创建自己的连接、模型声明和执行方案。
3. 会话绑定执行方案版本；新消息可以显式选择已获授权的覆盖项。
4. 提交前执行服务端预检，生成 resolved execution snapshot，界面显示最终值及来源。
5. 排队 Run 固定快照，不随“默认模型”变化；执行前重新检查账号、凭据撤销和资源授权。
6. 已运行任务不热切换 Key、服务商、角色或 Skill；变更只作用于后续 Run 或新分支。

普通设置选择顺序：任务显式选择 → 会话绑定 → 用户默认 → 系统推荐。
硬限制不使用“后者覆盖”：实际允许值由模型能力、管理员上限及账号授权共同约束。超过上限返回清楚的预检错误，不静默缩小；未提供值才应用预设。
Skill 只声明最低需求和请求权限。实际工具集合是已批准能力的交集；必需工具缺失时阻止执行，不悄悄删掉后启动。

管理员的安全与权限限制始终有效。研究角色不能改变 RBAC；提示词中的“管理员”“无限额度”“启用 Bash”不产生权限。

## 4. 前端配置页、路由与交互设计

本节是可直接拆分开发任务的页面设计。以下页面和路由均为目标设计，当前尚未实现；不能仅增加菜单和 JSON 输入框就视为配置中心完成。

### 4.1 入口与信息架构

沿用当前顶部五个研究导航，不再增加一排技术设置按钮。右上角用户菜单的“设置”进入独立设置工作区；增加“模型连接”快捷入口。“技能库”入口和设置内 Skills 指向同一实现，不维护两份数据或两套编辑器。

~~~text
右上角 用户菜单
  模型连接 ──→ 设置 / Runner / 模型连接
  技能库   ──→ 设置 / Runner / Skills
  设置     ──→ 设置首页
                    │
                    ├─ 账号与资料（复用）
                    ├─ 模型连接
                    ├─ 模型与能力
                    ├─ 执行方案
                    ├─ 研究角色
                    ├─ Skills
                    ├─ MCP 工具
                    ├─ 额度与用量
                    └─ 运行环境（仅管理员）

阅读区输入框：当前方案 / 模型 / 本次额度 / 运行详情
会话列表：状态筛选 → 会话详情 → 分支 → Run 检查器
~~~

设置页左侧导航固定，右侧为内容区；顶部显示当前账号与“仅影响此账号”的作用范围。管理员共享资源明确显示共享标记，普通用户只能选择已授权资源，不出现其他用户的名称或密钥信息。
运行环境页由管理员操作，但 API 同样校验权限，不能只隐藏菜单。

### 4.2 页面路由与当前框架衔接

| Hash 路由 | 页面与默认内容 |
| --- | --- |
| /#/settings | 账号与资料；显示当前默认执行方案的概览卡 |
| /#/settings/runner/connections | 模型连接列表，新建/导入按钮 |
| /#/settings/runner/connections/:id | 连接详情，使用 tab 查询参数恢复当前页签 |
| /#/settings/runner/models | 模型列表与能力状态，按连接筛选 |
| /#/settings/runner/profiles | 执行方案列表、创建与复制 |
| /#/settings/runner/profiles/:id | 执行方案编辑、生效配置预览 |
| /#/settings/runner/roles | 研究角色与提示版本 |
| /#/settings/runner/skills | 复用现有 SkillsView 的列表与版本能力 |
| /#/settings/runner/mcp | MCP 服务列表、发现、工具授权 |
| /#/settings/runner/budgets | 预算策略与账号/周期额度 |
| /#/settings/runner/usage | 用量账本、估价来源、未知与待核对用量 |
| /#/settings/runner/runtime | 管理员的 CLI、容器、并发、资源和健康配置 |
| /#/sessions/:conversationId | 会话详情与分支、运行列表 |
| /#/sessions/:conversationId/runs/:runId | Run 检查器；tab 查询参数可定位诊断/用量等 |

详情编辑可用右侧面板，但仍有可刷新、可直接打开的地址。URL 不放 Key、Token、提示正文或完整模型连接 JSON。

当前 SettingsView 由工作台 store.view 切换，需迁为可定位的设置路由；TopNav 中 wb.setView('settings') 和技能库快捷入口同步调整。复用公共导航外壳，不创建第二套认证状态。
同时更新 router.ts、safeReturnTarget 的站内返回白名单和旧入口兼容；现有阅读深链保持有效。离开阅读时保存页码、草稿和布局，返回时恢复原标签，不能把“打开设置”变成“新建阅读会话”。

### 4.3 页面公共布局与状态

桌面页面采用“左侧设置导航 + 内容区”，内容区按需分“列表 / 编辑详情”。连接和 MCP 列表可用卡片，预算和用量采用便于对比的表格。小屏幕将导航收进抽屉、列表和编辑切为独立页，避免强行保留三栏。

所有编辑页共用：
- 页首：名称、作用范围、启停状态、revision、验证状态和最后更新时间。
- 主体：基础表单为默认，高级参数折叠；有依赖或限制的字段就地说明。
- 底部操作：取消、保存；“测试”“设为默认”“应用到下一次运行”是独立动作。
- 状态覆盖：首次加载、空列表、读取失败、未保存、保存中、保存成功、版本冲突、资源被撤销、只读和权限不足。
- 保存使用 expected_revision；409 时展示“本地草稿 / 服务端新版本”差异，允许重新载入或合并后另存，不静默覆盖。
- 离开有改动的表单，提供“保存后离开 / 放弃改动 / 留在此页”。成功保存后刷新资源状态和相关引用，不重建原生会话。
- 密钥只放当前表单内存，不进入 URL、localStorage、sessionStorage、前端持久化 store 或错误追踪。刷新后要求重新填写尚未保存的 Key，其他非敏感草稿可按账号恢复。

### 4.4 模型连接页

列表显示：连接名称、协议、模型数、是否个人默认、已配置凭据、健康状态、上次验证；支持搜索、标签过滤、新建、复制和导入。
复制连接默认不复制密钥，避免用户误以为副本已经可用。停用/归档前显示受影响的执行方案和定时任务。

详情页四个页签：
1. 基础：名称、服务商预设/自定义、协议、Base URL、认证方式、Key/Token、描述与标签。
2. 模型：此连接的模型目录，手工新增、发现模型、设置展示名；发现结果先确认，不自动切换默认模型。
3. 高级：连接/请求超时、已批准代理、额外请求头、重试策略和兼容适配。
4. 验证记录：配置校验、文本、视觉、工具与长上下文测试的时间、模型、范围、用量和错误。

Key 输入框始终为空，已有密钥显示“已配置”，并提供“替换”“清除”。空输入保存保留旧密钥；清除必须明确点操作。前端从接口拿不到原 Key，不能提供“显示服务器原密钥”。

操作区：
- 保存：只保存配置，不调用模型。
- 校验配置：本地/服务端结构与权限检查，不调用模型。
- 测试连接：弹出测试模式、材料范围、输出额度和费用说明，确认后创建可追溯验证 Run。
- 设为个人默认：显示只影响新会话；已经绑定方案的会话不被修改。
- 导入：打开脱敏预览与选择向导，command/hook 等危险字段不能直接激活。

仅填写地址和 Key 后也可先保存“待验证”连接，避免强迫用户为保存配置付费。正式任务是否允许使用待验证能力由预检规则决定。

### 4.5 模型与能力页

按连接分组，列表列出实际模型 ID、展示名、上下文、单次输出、视觉、工具调用、流式及能力可信状态。
点击模型进入详情面板：

| 表单组 | 控件与行为 |
| --- | --- |
| 基础 | 连接选择、模型 ID、展示名；连接内 ID 唯一性校验 |
| 上下文 | 128K / 200K / 1M / 自定义整数，显示实际 token 数 |
| 输出 | 单次输出上限，提示输出与思考预留关系 |
| 视觉 | 能力声明选项、图片 MIME/数量/大小；单独视觉验证按钮 |
| 工具/结构化 | 用户声明及验证结果分别显示 |
| 思考 | off/adaptive/fixed 和 effort，仅提供 Driver 与模型支持的选项 |
| 价格 | 输入、缓存、输出价格和计价单位、来源、更新时间；允许“未知” |
| 证据 | 已验证范围、Driver 版本、连接 revision、过期原因 |

“声明支持 1M”保存后显示声明标记；只有对应范围的验证证据才显示已验证。不得用一个绿色勾号同时表示“用户勾选”和“实际测试通过”。
选择不支持的组合时就地说明，如“当前 Driver 无法下发此参数”；不能保留一个看似可用、实际被忽略的滑杆。

### 4.6 执行方案页

这是普通用户最常使用的配置页：创建“快速问答”“论文精读”“导读批注”“前沿追踪”等组合，而不要求每次分别选择七类资源。

编辑页为“配置表单 + 生效摘要”，示意：

~~~text
执行方案：论文精读                         个人 · revision 3

连接          [我的网关          v]      生效摘要
主模型        [研究模型          v]      发送目标：我的网关
视觉模型      [使用主模型 / 另选 v]      上下文：声明 200K
研究角色      [精读导师          v]      单次输出：8192
主 Skill      [paper_read @版本  v]      全任务：24轮 / 24次工具
MCP 工具      [research 3项已授权]      金额策略：token/时长控制
预算策略      [标准研究          v]      缺口：视觉未验证
高级覆盖      [展开]                    [展开各参数来源]

[校验方案] [另存副本] [保存]
~~~

主 Skill 的选择会展示必需工具和能力，但不自动扩权。缺少能力时摘要列出修复入口，如“选择支持视觉的模型”“申请此 MCP 工具”。
点击“校验方案”调用 preflight，显示实际最终值、来源、限制精度、能力缺口和材料范围，不调用模型。
保存不等于应用到所有历史会话；另外提供“设为新会话默认”和“应用到当前会话的后续 Run”，后者展示差异，必要时引导创建分支。

方案中的模型路由角色 main/vision/fast/reasoning 放在本页，研究角色提示词在单独角色页编辑，避免把两种“角色”混在一个下拉框中。

### 4.7 额度与用量页

预算策略页不是 JSON 编辑器。按“单次生成 / 整个任务 / 会话与周期”分组：

| 分组 | 前端字段 |
| --- | --- |
| 单次生成 | 最大输出、思考预留、首响应/请求超时 |
| 整个任务 | 累计输入/输出、轮次、工具次数、墙钟时长 |
| 金额 | 不使用美元自动停止 / CLI 估价守卫 / 可信网关控制；对应金额与可信度 |
| 会话与调度 | 会话总额、单次调度上限、每日/周期额度、达到上限后的行为 |
| 提醒与停止 | 预警比例、保留结果、追加额度继续的提示方式 |

每个限制旁显示“CLI 执行 / 工具代理执行 / 观察后中止 / 当前不可精确执行”。当前无法观测的模型请求数默认“不设置”，不展示无法兑现的硬限额。
受管理员限制的字段标出最大可选值及限制来源；用户输入超过时明确校验，不静默改小。空值、不设置和关闭策略使用明确控件，不混用 0。

用量页以账号、会话、执行方案、连接/模型、时间段筛选，分别展示 token、CLI 估价、可信金额、未知用量与预留中额度。
显示“最近触限任务”，可直接进入 Run 诊断。不得把 CLI 估价汇总标题写成“实际账单”。

### 4.8 Skills、MCP、角色和运行环境页

| 页面 | 主界面 | 详情和关键操作 |
| --- | --- | --- |
| Skills | 复用现有技能库的分类、标签、来源、启停、版本、ZIP 上传与归档 | 增加能力需求、必需/可选工具、建议预算、适配覆盖、被哪些方案引用；预算实际值通过方案修改 |
| MCP | 服务卡显示内置/外部、传输类型、状态、已授权工具数和引用方案 | 基础连接、凭据、工具目录、权限、诊断四区；“发现工具”后逐项授权；schema 更新展示差异 |
| 研究角色 | 角色卡显示用途、语言、版本和引用数 | 表单编辑提示、证据要求和输出风格；预览组合效果；保存不提升权限 |
| 运行环境 | 仅管理员可见，展示当前 CLI/镜像、协议、并发、队列、资源、心跳和重启状态 | 参数标注“下次任务生效”或“需重新发布”；CLI 版本升级不能伪装成普通即时保存 |

MCP 详情按 transport 改变控件：远程 HTTP 填 endpoint/认证；stdio 选择管理员已批准模板。普通用户不出现可执行任意命令的输入框，可提交待审接入申请。
内置 research 卡展示真实 13 个工具；不可改名伪装、不可覆盖内部凭据、不可关闭某个任务必需授权后仍假装运行成功。
MCP 显示“连接成功/发现工具”与“实际工具验证成功”两种状态，避免把握手当成业务可用证明。

### 4.9 新用户配置向导

首次进入模型配置，提供四步向导：
1. 添加连接：选择预设或自定义，填写地址与凭据；可保存后稍后验证。
2. 添加模型：填写实际 ID，声明上下文、视觉和工具能力。
3. 选择方案：复制标准研究预设，选择角色、Skill 和已授权 MCP，确认额度。
4. 查看生效预览：列出能力缺口与费用策略；可设为新会话默认。

向导不会自动测试付费模型、启用任意工具或重新开放普通账号登录。完成前允许保存草稿，下次进入能恢复非敏感配置进度。

### 4.10 阅读输入框与会话调试前端

阅读区输入框上方增加紧凑配置条：
“论文精读方案 · 我的模型 · 标准额度 [调整] [详情]”。

“调整”打开本次 Run 配置弹窗，展示从方案继承的值、可覆盖项和最终限制；保存为“仅本次”，或另外选择“另存为方案”。普通临时修改不改变所有会话。
检测到图片时显示本次视觉模型和发送目标；若需改用另一服务商，发送前明确展示并确认。
预算达到预警值时在会话内显示进度；停止后保留已完成回答和产物卡，提供“查看原因”“追加额度继续”“新建分支”。

会话详情页面：
- 左侧：会话与分支、关联论文和 Run 列表。
- 中间：正常讨论及已验证产物，不混入环境变量和长诊断日志。
- 右侧：按需打开 Run 检查器，七个页签与第 8.4 节对应。
- 从失败消息、活动面板、任务会话列表、额度页都能直接定位到同一个 Run 的诊断页签。
- 原生会话缺失、资源撤销、重试可能重复副作用时，按钮禁用或先显示明确处理步骤，不仅显示“重试失败”。

触限展示示例：
“本轮因 CLI 估价上限 0.20 美元停止，返回估价约 0.264 美元；该值不是服务商账单。已完成的材料与产物见下方。”
如果批注已经校验提交，另显示“批注已生成”；没有验证通过的产物则显示未完成，不用空白页替代。

### 4.11 前端组件与接口映射

| 组件/页面（建议命名） | 数据与接口 |
| --- | --- |
| SettingsLayout / RunnerSettingsNav | 认证身份、设置导航、返回阅读位置 |
| ConnectionList / ConnectionEditor | /api/me/runner/connections 及 credential、validate |
| ModelCatalog / ModelCapabilityEditor | models、capability_checks、验证结果 |
| ExecutionProfileEditor / ResolvedConfigPanel | profiles、preflight、字段来源与 enforcement |
| BudgetEditor / UsageDashboard | budgets、usage ledger、预留和诊断入口 |
| McpServerEditor / ToolPermissionTree | mcp-servers、discover、工具授权与健康 |
| RoleEditor | roles、版本及引用关系 |
| SkillRunnerRequirements | 复用 SkillsView，读取技能执行契约与方案引用 |
| RunConfigPopover | 本次覆盖项、preflight 和提交 Run |
| SessionDetail / BranchList / RunInspector | sessions、branches、Run snapshot/events/usage/artifacts/diagnostics |
| RuntimeSettings | 管理员 RuntimePolicy、Driver 能力与健康 |

配置资源使用按账号的查询状态，统一处理 revision/失效刷新；不把密钥放进 Pinia 持久化。
保存操作返回服务端规范化视图，页面展示该结果。运行提交只传已授权资源引用和允许的覆盖项，最终配置由后端编译，前端预览不构成授权。

### 4.12 前端实施范围与验收

- P0-A 必须同时交付预算编辑页、发送前额度预览、失败诊断入口和触限结果卡；不能只开放后端配置 API。
- P0-B 必须交付连接列表/编辑、模型能力表单、执行方案编辑与研究角色页，以及最短配置向导。
- P0-C 必须复用技能库并补充执行需求，交付内置 MCP 目录及远程 MCP 草稿/发现/授权页。
- P1 完善完整会话分支页、七页签检查器、用量账本和管理员运行环境操作。

验收路径：全新账号从设置入口保存一个连接和模型 → 复制并调整方案 → 预检 → 回阅读区选方案发送 → 从结果进入对应 Run → 查看当时配置与用量 → 明确追加额度或创建分支。全过程不需要修改服务器配置文件。
另覆盖：刷新/深链、浏览器返回、未保存离开、密钥不回显、版本冲突、账号切换清理、表单键盘操作、小屏布局和受限能力说明。



## 5. Runner 可配置参数

### 5.1 连接

| 字段 | 含义及规则 |
| --- | --- |
| name / description / tags | 用户可理解的连接标识，支持分组 |
| protocol | anthropic_messages 首批直连；openai_chat / responses 为未来适配模式，必须绑定已验证适配器 |
| base_url | HTTPS 默认，保留供应商要求的路径；校验重定向、DNS 和地址访问策略；私有 API 须由管理员显式授权范围 |
| auth_type | x_api_key 或 bearer，选择其一；禁止旧凭据残留同时覆盖 |
| credential_ref | 仅服务端引用；新增、替换、清除是不同操作；空输入默认保留 |
| extra_headers | 名称和值按结构校验；敏感值入凭据库；不允许用户伪造 Firework 内部身份头 |
| proxy_ref | 管理员提供的出网配置，不接受任意代理命令 |
| connect_timeout_s / request_timeout_s | 建连与单次请求超时，均受平台上限约束 |
| retry_policy | Runner 不自动重跑付费 Run；CLI 内部重试若无法完整控制，显示能力限制和观察值 |
| enabled / default / revision | 多连接并存，乐观锁更新，版本化、可归档 |
| validation | 校验级别、时间、连接/模型/Driver 版本、结果和失效原因 |

连接能力验证不等于读取全部宿主机配置。迁移向导可由管理员选择导入当前连接，服务端直接转存凭据；默认只授权原管理员，其他账号不继承。

### 5.2 模型、视觉和长上下文

ModelDefinition 绑定 connection_id 与 revision，同名模型在不同网关视为不同模型。

| 字段 | 设计 |
| --- | --- |
| model_id / display_name | 实际请求 ID 与展示名分离，兼容大小写和网关别名 |
| context_window_tokens | 模型声明的单次总窗口，如 128000、200000、1000000；不是全任务累计额度 |
| max_output_tokens_supported | 服务商允许的单次输出上限；Run 请求值不能超过它 |
| vision / tool_calling / streaming / structured_output | 每项记录 unknown / declared / verified / failed，附证据和验证范围 |
| thinking_support / effort_levels | 模型及驱动确实支持的模式；未支持时不发送相应参数 |
| image_constraints | MIME、单图体积、图片数、分辨率策略；同时满足上传端和供应商限制 |
| context_mode | automatic / declared_window / verified_long_context；可选 1M，不能由名称后缀直接宣称通过 |
| pricing_revision | 输入、缓存读、缓存写、输出及计价单位；来源、更新时间与可信度 |
| metadata | 供应商说明及适配参数；禁止执行脚本或注入任意 CLI 参数 |

能力分别记录“用户声明”“小样本实测”“真实任务实际使用”，而不是一个 supports_vision=true。
小图测试通过不代表任意图片都可理解；64K 测试通过不代表 1M 已实测。界面应显示“声明 1M，已验证 64K”等真实范围。

1M 的实际可用窗口取模型、网关、CLI Driver、用户方案和管理员允许值的共同约束。输入预算必须包含系统提示、角色、Skills、MCP 工具定义、历史、材料、图像估算、输出及思考预留。每次上下文占用与整个 Run 重复输入的累计量分别统计。

模型 ID 含 [1M] 仅是当前连接的请求/配置表示，不凭此判断后端容量。CLI 2.1.322 与新文档中的上下文变量行为可能不同；Driver 必须有版本能力清单和测试，不将最新文档参数无条件下发。没有精确 token 计数时显示估算及余量；不通过禁用所有压缩来假装支持长上下文。

视觉任务预检失败时明确缺失项；可建议文本阅读或选择视觉模型，用户确认后才改变覆盖范围。视觉路由切换不得把整段历史悄悄发送到另一服务商。

### 5.3 两种“角色”分别管理

- 研究角色 RolePreset：精读导师、方法解释、证据审查、前沿分析。记录 prompt_version、语气、语言、证据与不确定性要求；在系统安全前缀之下与 Skill 内容组合。
- 模型路由角色 ModelRoute：main、vision、fast、reasoning，对应具体连接和模型版本。需要时才能使用其他模型，不能无提示切换。
- 平台账号权限 admin/user 仍由认证系统控制，与以上两者无关。
- 首批单一主智能体，不因选择“审稿人”就自动启动子智能体。未来子智能体有独立 trace 和预算，且计入父 Run 总额。

### 5.4 推理参数

| 参数 | 规则 |
| --- | --- |
| max_output_tokens_per_request | 每次生成的最大输出，所有轮次复用，但不等于全任务最大输出 |
| thinking_mode | off / adaptive / fixed，仅对当前模型/Driver 支持的组合显示 |
| thinking_budget_tokens | fixed 模式的上限，纳入供应商定义的输出约束与 Run 用量 |
| effort | 取当前 Driver/模型支持的枚举；不能把 UI 选项当成已生效 |
| auto_compact / context_target_tokens | 版本适配后生效；记录压缩发生、上下文摘要及材料引用变化 |
| temperature / top_p 等 | 非所有 Claude CLI 版本可配置；首批不展示通用滑杆，有已验证适配器后再开放 |
| fallback_routes | 默认关闭；启用需明确服务商、上下文传输与用量归属，不静默回退 |

## 6. 用量、预算与触限处理

### 6.1 分清四层

1. 单次模型请求：输入窗口、最大输出、思考、请求/首 token/空闲超时。
2. 单个 Run：累计输入、累计输出、推理轮数、模型请求数、工具调用、墙钟时长、金额策略。
3. 会话/定时任务：多次 Run 的累计额度、每日或每个调度窗口额度。
4. 账号/平台：跨模型和并发任务的总额度、并发数、排队数及资源上限。

缓存 token 单独计数；不能把 usage.input_tokens 简单当成当前上下文大小。流事件和最终 result 的同一份 usage 只结算一次；累计值和增量值通过 Driver 标记 scope、request_id、message_id 和来源。

### 6.2 BudgetPolicy 字段

~~~json
{
  "schema_version": "runner-budget/v1",
  "max_output_tokens_per_request": 8192,
  "max_run_input_tokens": 256000,
  "max_run_output_tokens": 32000,
  "max_model_requests": null,
  "max_turns": 24,
  "max_tool_calls": 24,
  "max_wall_time_s": 1800,
  "first_token_timeout_s": 120,
  "idle_timeout_s": 180,
  "tool_timeout_s": 120,
  "cost_mode": "disabled",
  "cost_limit_usd": null,
  "warn_at_ratio": 0.8,
  "on_limit": "stop_and_preserve",
  "automatic_run_retry": false
}
~~~

以上是待配置的示例，不自动应用生产。cost_mode 可选：
- provider_verified：只有已验证计价或可信网关预算约束时提供；账户账本仍需结算。
- cli_estimate_guard：明确接受 Claude CLI 估算误差，再生成 --max-budget-usd。
- disabled：不使用美元估算自动停机，仍执行 token、轮次、工具和时长限制。

必须选择明确的金额策略。没有可信价格但选择强制账号金额额度时，预检提示补齐价格/可信网关；不能把未知金额记为 0，也不能偷偷关闭账号限额。
已知只是估价的当前网关，建议迁移向导提供“token/时长控制，CLI 金额只作参考”的方案，解决固定 0.20 美元过早截断；由用户/管理员确认后用于新任务。

金额上限和累计 token 上限在请求边界停止后续派发；不能承诺即时中断已经发出的请求而不计费。单次输出限制、额度预留和取消信号用于缩小超额范围；严格账单硬限额需服务商或可信网关配合。

### 6.3 首批限制的真实执行能力

每个生效参数附 enforcement：cli / mcp_proxy / runner_observed / gateway / unavailable。界面显示来源与精度，不能只有可编辑数字。

| 限制 | 当前 CLI 路线的可实现方式 | 不能承诺的能力 |
| --- | --- | --- |
| 单次最大输出 | Driver 注入已验证的输出参数，要求模型/网关遵守 | 后端忽略该参数时仍绝对不超额 |
| max_turns / CLI 估价上限 | 使用 CLI 已验证参数；保留原始 subtype | 等同于实际账单硬限制 |
| MCP 调用数与结果大小 | 自有代理在调用前检查，分别统计尝试/成功/失败 | 统计未经过代理的未知外部操作 |
| Run 累计 token | 解析公开 usage，在可观察边界发送取消并收尾，标 runner_observed | 取消前已经发出的下一请求可以撤销计费 |
| 模型请求次数 | 当前 Driver 默认为 null；有可验证请求 trace/网关后再启用 | 用 agent turn 数代替实际请求数 |
| 墙钟/空闲超时 | Runner 监视并终止进程组、保留记录 | 正在进行的远程请求立即停止计费 |
| 请求级硬金额/账号硬额度 | 可信网关或服务商限制，结合预留账本 | 单靠本地估价和容器就能保证账单上限 |

初版标准方案不填写不可执行的 max_model_requests，以免预检把所有任务挡住。total token 约束标明“观察后中止，可能有在途用量”；管理员要求精确硬约束时必须选择可执行的 Driver/网关，否则预检阻止。
first_token_timeout 只有 Driver 能观察首个公开 token 事件时才启用；否则使用 first_response_timeout，不把整条 assistant 结果的到达时间称为首 token 延迟。stderr 的活动不能无限延长模型空闲期限。

### 6.4 建议预设，不直接覆盖生产

| 预设 | 单次最大输出 | 累计输入/输出 | 轮次 / 工具 | 墙钟上限 | 用途 |
| --- | --- | --- | --- | --- | --- |
| 连通验证 | 256 | 8K / 1K | 2 / 0 | 60s | 用户主动的一次小请求 |
| 快速问答 | 2048 | 32K / 8K | 8 / 4 | 180s | 摘要与简短解释 |
| 标准研究 | 8192 | 256K / 32K | 24 / 24 | 1800s | 导读、比较、一次前沿任务 |
| 深度研究 | 16384 | 1M / 64K | 40 / 48 | 3600s | 多步骤精读，模型须支持输出 |
| 长上下文 | 8192 | 2M / 32K | 12 / 24 | 3600s | 窗口可选 1M，累计输入另计 |

K/M 是预算展示单位，持久化保存明确整数，1M 在本设计中为 1000000 token。上下文预留后，1M 窗口能容纳的纯材料必然少于 1M。

美元额度不写死在 Skill；可在方案中另外启用。超过预设的任务可以由已授权用户修改，不以改代码完成。管理员配置最大可选值，不能开放无界后台任务。

### 6.5 账本与触限

- 提交时原子预留账号/调度周期额度，使用 SQLite 事务防止并发分别绕过；排队、取消、失败都要结算。
- usage 缺失标记 unknown，保留待核对预留与说明，不将失败当成免费。
- 达 80% 发预算预警，展示已用/剩余和剩余步骤；可配置收尾预留，首次验证其真实效果。
- 达阈值停止 Runner 后续任务/工具派发并向 CLI 取消；对于 CLI 内部请求存在可观测性和在途边界，不能假称逐请求派发均由 Runner 控制。保存已读材料、已完成步骤、最后有效回答、usage 与检查点。
- 预算停止应显示“额度用尽，可继续”，不是“智能体不知道怎么做”；网络、鉴权和协议错误另外分类。
- “追加额度继续”创建新 Run，引用原 Run/checkpoint；展示追加额度和会话累计，需明确提交，不自动重跑。
- 新预算不会修改过去记录，也不会自动复活失败/排队任务。
- 角色/Skill 没有收尾能力时，不伪造总结；可显示已完成的证据与未完成步骤。

## 7. Skills 与 MCP 统一纳管

### 7.1 现有 10 个 Skill 映射

| Skill | 主职责 | 必需 MCP 工具 | 首批建议方案 |
| --- | --- | --- | --- |
| chat | 科研讨论 | 无 | 快速问答 |
| search_library | 已存资料检索 | library_search | 快速问答 |
| search_arxiv | arXiv 检索 | arxiv_search | 快速问答 |
| paper_discover | 多源论文发现 | paper_search | 快速问答或标准研究 |
| paper_import | 已授权入库 | paper_import | 独立导入预设，保留导入幂等 |
| paper_read | 阅读 | paper_read、paper_page、library_search | 标准或深度研究 |
| paper_review | 审查 | 同上 | 深度研究 |
| paper_compare | 比较 | 同上 | 标准或深度研究 |
| paper_guide | 结构化导读批注 | reader_guide_context、reader_guide_material、reader_guide_submit、skill_resource | 标准研究 |
| frontier_monitor | 发现、证据与报告 | frontier_context、frontier_search、frontier_report、skill_resource | 标准研究及周期额度 |

工具按完整服务器命名空间引用，例如 mcp__research__paper_page。表中为迁移的执行方案建议，不修改既有工具授权条件。

### 7.2 Skill 元数据扩展

在已有 skill_versions manifest 增加版本化 runner_contract：
- required_capabilities：视觉、工具调用、结构化输出、最低上下文/输出要求。
- required_tools / optional_tools：带服务器与能力名；不接受任意命令。
- suggested_budget_profile：仅建议；运行时取执行方案和管理员约束。
- input_contract / output_contract / artifact_types：保留导读 paper-guide/v1 与证据锚点核验。
- execution_mode：prompt_resources 首批；脚本/原生插件为后续独立适配模式。
- upstream、license、attribution、resources_hash：保留 Nature/kelip 来源和实际适配覆盖。

沿用现有 ZIP 与不可变版本。纳管不等于把上游所有脚本、依赖、网络和本地文件权限开放。现有 Nature 前沿适配、导读资源先原样登记；完整 kelip 六站/视觉材料链继续标注未完成。
同一 Run 先只指定一个主 Skill；附属资源和角色显式组合。复杂跨 Skill 工作流另有步骤 DAG 与共享预算，不能靠把所有 SKILL.md 拼成系统提示实现。

### 7.3 内置 research MCP 的 13 个工具

| 分组 | 工具 |
| --- | --- |
| 库内检索 | library_search |
| 外部发现 | arxiv_search、paper_search |
| 论文材料 | paper_read、paper_page |
| 授权导入 | paper_import |
| Skill 资源 | skill_resource |
| 前沿 | frontier_context、frontier_search、frontier_report |
| 导读 | reader_guide_context、reader_guide_material、reader_guide_submit |

将现有实现包装为 builtin:research，记录工具 schema 哈希、版本和状态；先不拆成 13 个服务。
不得由外部 MCP 覆盖 research 名称或内部身份字段。导入、导读、前沿仍需匹配已授权 Run、论文版本与工作区；保留审批入库。

### 7.4 外部 MCP 配置

字段：name、transport、endpoint 或 executable_template_id、args_template、credential_refs、env_allowlist、headers、tool_allowlist、tool_schema_hash、timeout、max_result_tokens/bytes、health、revision、visibility、risk_class。

- remote Streamable HTTP：首批新增方式，支持凭据引用和 list_tools；连接发现不等于自动授予所有工具。
- stdio：内置 research 首批保留。外部 stdio 只运行管理员批准并固定版本的安装模板，普通用户只填模板参数；任意 command、安装钩子、shell 拼接不开放。
- 必须以 argv 数组启动，不使用 shell=True；路径与参数结构校验。
- stdio 子进程只得到自己的 MCP 凭据和最低材料授权，不继承模型 Key、其他 MCP Token 或平台主密钥。
- 普通用户提交未经批准的工具仅进入待审定义，不能在共享 Runner 中直接执行。
- 新外部 stdio/不可信脚本未来放入独立 worker，只挂当前账号的必要材料；仅分目录不等于操作系统级租户隔离。
- 工具目录按服务端策略裁剪再暴露给 Claude；执行时再次授权，不能仅依赖 --allowedTools 提示。
- 外部写入、发送、删除、发布等工具定义副作用级别与确认策略；重试前检查幂等能力。
- 设置任务总调用上限、分服务/分工具上限、结果体积上限；结果超限返回分页或明确截断标记与来源，不无声裁剪证据。
- OAuth 接入、任意新 stdio 安装、旧 SSE 兼容分后续阶段，不在 MVP 假装完成。

### 7.5 导入 CC Switch / Claude 配置

提供“导入预览”而不是直接覆盖运行配置：
1. 上传经用户选择的配置，先脱敏解析，显示连接、MCP、角色/提示和 Skill 引用。
2. 同一连接按规范化地址、协议及用户定义标识提示疑似重复，不按名称直接覆盖。
3. 密钥单独转入凭据库，前端预览不回显；导出默认无密钥。
4. command、apiKeyHelper、hooks 和宿主机路径作为不可信配置，不自动执行或挂载。
5. Skill 路径只转为待上传/待匹配资源，不从服务器任意路径读取。
6. 用户确认选择后写入草稿版本；外部 MCP 待授权，验证后才可用于任务。
7. 首批支持明确标识格式的 JSON；CC Switch 原生数据库完整导入列为后续，不用猜测兼容所有版本。

## 8. 会话、运行与调试设计

### 8.1 五层标识

~~~text
研究任务会话 conversation_id
 ├─ 论文、分类、任务类型、草稿、执行方案版本
 ├─ 原生会话分支 native_session_id / branch_id
 │   └─ Run run_id（一次点击发送、继续或重试）
 │       ├─ 模型请求 request_id / message_id（能观测时）
 │       ├─ MCP call_id / server_revision / tool_name
 │       └─ artifact_id / material_version / checkpoint_id
 └─ source_run_id / parent_branch_id 保留分支来源
~~~

conversation 是研究任务的长期容器；native session 是引擎续接状态；Run 是一次执行，不再用同一 ID 混淆三者。
现有 conversation_id、native_session_id、agent_runs 全部保留，增加分支和关联字段。分类/归档与删除分离。

### 8.2 会话功能

- 按论文、领域、任务类型、标签、状态、时间、连接、模型、Skill 查找与筛选。
- 置顶、重命名、归档、恢复、导出 Markdown；结构化调试包与研究内容导出分开。
- 详情显示关联 PDF 版本、阅读位置、当前方案、角色、模型和累计 usage；无模型调用也可查看。
- 会话顶部显示实际连接与最近成功使用模型，下一次运行的预期配置与历史配置可对比。
- 每个原生分支同一时间只允许一个写入中的 Run；数据库锁跨进程生效。不同分支可并发，但共享账号总预算。
- 继续会话：新 Run、原 native session、明确的新额度；先检查会话文件和当前材料可用性。
- 重试：新 attempt 与 request_key，引用失败 Run；提示是否可能重复计费，禁止隐式自动重试。
- 分支：从检查点或指定消息创建新的 native session，保留来源；原分支不被覆盖。
- 切换角色、Skill 主要版本、服务商或敏感 MCP 能力时，默认建议新分支，并显示历史将发送至哪里。
- 原生会话文件丢失：显示缺失和恢复/新分支入口，不悄悄降级成失去上下文的新会话。
- PDF 换版：保留旧材料引用；明确选择继续使用旧版本或新分支切到新版本。
- 归档/更改默认配置不终止历史审计；禁用或撤销资源可阻止后续执行。

### 8.3 状态和结束原因

目标 Run 状态：
queued → preflighting → running → succeeded / stopped / failed / cancelled。
waiting_user 仅用于明确的可恢复批准/输入需求，不能把已结束 CLI 进程装成仍在暂停。

finish_reason 单独记录：
completed、budget_usd、budget_tokens、max_turns、max_tool_calls、wall_timeout、idle_timeout、user_cancel、runner_restart、auth_error、rate_limit、provider_unavailable、context_overflow、unsupported_capability、mcp_unavailable、tool_error、invalid_artifact、native_session_missing、internal_error、unknown。

stopped 表示有意触限或策略停止，保留 partial/checkpoint；failed 表示执行错误。succeeded 仍须满足研究工具、材料和产物契约，不能只因 CLI exit 0 就通过。

Run 执行状态与业务产物状态分开：artifact 可为 staged / validated / committed / rejected。若导读已通过材料与字段校验并完成幂等写入，而最后的模型总结触限，界面显示“批注已生成，本轮总结因额度停止”，不能把已提交产物隐藏成全部失败。若仅有 staged 内容，则由业务服务重新核对 Run 绑定、材料版本、引用与副作用后决定能否提交；不因保留 partial 就发布未校验结果。检查器展示每个产物的状态和对应检查点。
waiting_user/触限继续都需要新的明确动作；进程已经退出的任务通过新 Run 续接，原 Run 不回到 running。

P0 可先保留旧 status 枚举，新增 finish_reason、partial_available、continuation_available 和用户可读诊断；触限界面先显示“已触限中止”。协议/前后端协同升级后再启用新状态，禁止旧客户端误判为仍运行。

### 8.4 调试检查器

会话右侧提供“运行详情”，分七页：
1. 概览：Run 状态、结束阶段、耗时、配置摘要、费用可信度及可继续条件。
2. 生效配置：脱敏快照、来源、版本哈希、与上一次的差异；解释某参数被限制/忽略的原因。
3. 时间线：预检、排队、启动、首响应、工具调用、产物校验、触限、取消、完成；支持按 trace_id 关联。
4. 模型与用量：每次可观察请求的模型、延迟、token/缓存、CLI 估价和预算变化；无法观察则显示 Run/turn 粒度。
5. 工具：服务、名称、参数摘要、授权、耗时、状态、结果大小、截断/分页、来源与副作用确认。
6. 材料与产物：论文/版本/页码、读入范围、证据、导读校验错误及可下载产物。
7. 诊断与操作：清晰原因、原始错误码、脱敏诊断、重试/追加预算继续/新分支/导出调试包。

研究界面默认只展示简明进度与问题；底层配置和日志放到检查器，不占据正常论文阅读流程。

### 8.5 Trace 与日志契约

每条事件至少包含：event_id、seq、timestamp_utc、workspace_key、conversation_id、branch_id、run_id、attempt_id、trace_id、span_id、parent_span_id、stage、event_type、status、duration_ms、usage_scope、config_snapshot_hash；事件按 seq 可去重和断线补读。

保留 bounded stderr 的脱敏环形缓冲，截断标记和错误分类。禁止保存完整环境变量、Authorization、Key、Cookie、含凭据 URL、带密钥 argv；服务商错误文本需先脱敏再展示。

调试不收集或要求模型提供隐藏思维链；不存 thinking/signature 原始段。记录公开回答、工具轨迹和可观察 usage 即可。
用户自己的内容可在本人会话中查看；管理员默认只能看健康与脱敏指标，读取研究正文要有明确支持授权和审计。服务器管理员本身的系统权限不能被宣传成加密后绝对不可访问。

调试包默认包含快照哈希、版本、结束原因、脱敏事件、用量和资源标识；默认排除正文、PDF、图片和完整 MCP 输出。用户勾选才附带自己的内容。保留期限：诊断默认 30 天可配置，研究会话按用户归档规则保留；凭据永不进入包。

### 8.6 调试与重放

| 操作 | 是否调用模型 | 作用 |
| --- | --- | --- |
| 解析/编译快照 | 否 | 校验能力、权限、参数及最终配置 |
| 离线事件重放 | 否 | 用已保存事件检查 UI、状态机和预算计算 |
| MCP 健康/工具发现 | 否 | 可能访问外部服务，但不调用研究工具；可有第三方服务自身计费 |
| 小请求连通/视觉验证 | 是 | 用户显式触发，独立低额度 |
| 继续/重试/重新生成 | 是 | 新 Run，显示配置差异、额度和可能重复费用 |
| 复用导入/写入工具 | 视工具而定 | 必须保留业务幂等和副作用确认，不靠回放历史消息执行 |

不能将 SSE assistant/user 事件数量假装成全部底层 API 请求数。请求级追踪通过已验证的本地 OTel 接收器或显式网关补充；未支持时模型请求级额度标为无法精确执行，若管理员要求精确硬约束则预检拒绝，不能只在界面显示一个数字。

## 9. 数据模型与 API

### 9.1 数据保存范围

- 中央身份库继续管理账号、工作区映射与共享资源授权。
- 用户自己的连接、模型、角色、方案、MCP 定义与使用账本保存于其工作区数据库；所有跨表引用必须在同一授权作用域内验证。
- 管理员共享配置使用显式授权，不因知道 ID 就可使用；共享凭据对使用者仍只暴露引用。
- secrets 保存在独立凭据服务/表，用 AES-GCM 等带认证加密，主密钥由容器 secret 挂载提供，不进入 Git、普通偏好 JSON 或模型可读挂载；记录 key_version 以便轮换。
- 完成/排队历史记录固定非敏感配置内容及 credential revision 引用，不复制密钥密文到 Run。
- 资源删除采用停用/归档；被历史记录引用的不可变版本保留。删除秘密可撤销后续访问，但不破坏旧快照展示。

### 9.2 表与关系

| 表/扩展 | 关键字段 |
| --- | --- |
| provider_connections / connection_revisions | id、name、protocol、base_url、auth_type、credential_ref、revision、state |
| model_definitions / model_revisions | connection_revision、model_id、capabilities、context_window、pricing_revision |
| capability_checks | feature、scope、sample_size、declared/verified/failed、driver_version、expires_at |
| role_presets / role_revisions | prompt、language、evidence_rules、hash |
| mcp_servers / mcp_revisions | transport、approved_template、endpoint、secret_refs、tools_schema_hash、risk |
| budget_policies / budget_revisions | request/run/session/account 限额和 enforcement_mode |
| execution_profiles / profile_revisions | 连接、模型路由、角色、Skill、MCP、预算及 hash |
| conversation_branches | conversation_id、native_session_id、parent_branch、checkpoint、profile_revision |
| run_snapshots | run_id、resolved_json、hash、driver_version、runtime_image_digest |
| run_events / tool_spans / model_spans | 关联标识、阶段、用量、耗时、脱敏诊断、可观测性 |
| usage_reservations / usage_ledger | 预留、结算、usage_source、idempotency_key、pricing_revision、可信度 |
| run_artifacts / checkpoints | Run、材料版本、产物契约、验证、partial、恢复范围 |
| agent_runs 扩展 | branch_id、profile_revision、snapshot_id、parent_run_id、attempt、finish_reason、partial |
| conversations 扩展 | default_profile_revision、active_branch_id、tags/归档等复用现有字段 |

表按增量迁移添加，编号在实施时取最新迁移号，不预占当前数据库序号。

### 9.3 对外接口（目标）

| 接口 | 用途 |
| --- | --- |
| GET/POST /api/me/runner/connections | 列出/创建连接 |
| PATCH /api/me/runner/connections/{id} | expected_revision 更新配置，不回显凭据 |
| PUT/DELETE /api/me/runner/connections/{id}/credential | 单独替换/撤销 Key |
| POST /api/me/runner/connections/{id}/validate | mode=metadata/text/vision/tool/long_context，费用测试需 confirmed |
| GET/POST /api/me/runner/models、roles、budgets、profiles | 各对象注册与版本管理 |
| GET/POST /api/me/runner/mcp-servers | MCP 定义与导入草稿 |
| POST /api/me/runner/mcp-servers/{id}/discover | 工具发现与差异报告，不自动授权 |
| POST /api/me/runner/profiles/{id}/preflight | 生成最终配置、需求缺口及预算估算 |
| GET /api/me/runner/imports/{id} | 连接/MCP 导入的脱敏预览与审批状态 |
| POST /api/agent/runs | 增加 profile_revision、branch_id、approved_overrides，复用 request_key |
| GET /api/agent/runs/{id}/diagnostics | 归一化失败原因、阶段、可恢复性 |
| GET /api/agent/runs/{id}/snapshot、events、usage、artifacts | 检查器读取；事件支持 after_seq |
| POST /api/agent/runs/{id}/continue、retry | 显式新 Run，必须新 request_key |
| POST /api/sessions/{id}/branches | 新建分支或切换执行方案 |
| POST /api/agent/runs/{id}/debug-export | 默认脱敏包，内容附件需明确选择 |

上述为目标路由，不加入当前“已实现 API 清单”。错误：401 未登录，403 无权使用资源，409 revision/会话并发/资源撤销冲突，422 参数或能力缺口，429 队列/周期配额，503 Runner 离线。错误体带 code、stage、limit_name、configured、observed、retryable、continuation_available，不携带密钥。

### 9.4 执行快照示例

~~~json
{
  "schema_version": "runner-execution/v1",
  "profile": {"id": "standard-reading", "revision": 3},
  "connection": {"id": "my-gateway", "revision": 2, "credential_revision": 4},
  "model_routes": {"main": {"model_id": "my-model", "revision": 2}},
  "role": {"id": "reading-mentor", "revision": 1},
  "skill": {"id": "paper_guide", "version_id": 7, "content_hash": "<hash>"},
  "mcp": [{"id": "builtin:research", "revision": 1, "allowed_tools": ["reader_guide_context", "reader_guide_material", "reader_guide_submit", "skill_resource"]}],
  "budget": {"id": "standard-research", "revision": 1},
  "capability_evidence": {"vision": "not_required", "context": "declared"},
  "driver": {"name": "claude-cli", "version": "2.1.322"},
  "runtime_image_digest": "<digest>",
  "snapshot_hash": "<hash>"
}
~~~

示例只含引用；服务端保存可复现的非敏感展开内容和每个值的来源。预算里的金额和价格可信度另行展开。
网页不提交可信 workspace_key、内部 token、CLI path、原生路径或 shell 命令。Runner 从认证的内部请求绑定工作区，并重新检查快照签名/哈希、资源授权、撤销和版本。

## 10. 容器与 Driver 实现边界

推荐 app / runner / qdrant / backup 四服务，外部只访问 app。Runner 不公开端口，通过有权限控制的 socket 卷与 app 通信；模型和外部发现源另有受控出网。
CLI 使用独立固定版本的原生二进制，镜像摘要进入快照，禁止运行时自行更新影响正在执行的任务。

新增模块建议：
- app/runner_config：配置、预检、策略合并、版本和脱敏视图。
- app/credentials：凭据引用、加密与撤销。
- app/usage：预留、用量归一化、结算和成本可信度。
- agent_runner/drivers/claude_cli：当前 cli.py 的版本化适配；支持的 flags/env/settings 有显式清单。
- agent_runner/compiler：把已授权快照编译成子进程参数和私有临时配置。
- agent_runner/mcp_proxy：授权、调用计数、脱敏 trace、工具目录与副作用策略。
- frontend runner-settings / run-inspector：配置中心和会话检查器，复用现有会话/活动 UI。

运行目录：
~~~text
data/
  auth/                         身份与共享授权
  accounts/<workspace>/
    app.db
    skills/                     复用技能版本资源
    agent/
      conversations/<branch>/   独立 Claude 配置和原生会话，持久化
      sessions/<native_id>/     稳定工作目录
      runs/<run_id>/            快照、事件、诊断、产物索引
  credentials/                  仅可信服务可读的加密记录
~~~

原管理员 legacy 数据先保留原路径，通过适配映射访问，不在第一批强行搬动全部研究文件。容器迁移必须测试原生会话路径兼容；需要时先保持旧绝对工作路径，再做显式迁移。

每个原生分支绑定稳定的 CLAUDE_CONFIG_DIR；启动时原子生成私有配置。并发分支不共写 settings.json。会话中的连续 Run 有锁，排队任务有租约/fencing，避免双 Runner 同时使用同一原生会话。

子进程只从白名单构建环境，不修改 os.environ、宿主机 ~/.claude/settings.json 或共享 .env。自定义连接凭据取代平台默认凭据时先清除互斥认证变量。
凭据只注入对应模型进程；MCP 通过独立 launcher 重建最小环境。私有 MCP 配置写 tmpfs 0600 文件，argv 只传路径，避免密钥出现在进程参数和诊断包。

继续使用 --bare、--restricted、--strict-mcp-config；不因支持角色/MCP 就开放任意 shell 或读取宿主机配置。当前 --bare 模式需要的 Skills、角色、MCP 均由 Driver 显式注入，不能假设放入 ~/.claude 后会自动加载。
密钥仍由系统管理员维护主密钥和备份；普通用户互相隔离不等于抵抗已控制宿主机的管理员。按任务 OS 隔离列为不可信扩展的必需前置，不拿共享卷目录规则冒充容器安全边界。

## 11. 实施顺序与迁移

本方案不自动开放公开注册或普通账号登录。当前 admin_only 发布策略保持，先在隔离环境完成双账号验证，用户开放范围另由管理员配置。设计和文档更新也不构成对既有付费失败任务的重试授权。

### P0-A：先修可解释限额和恢复入口

- 增加统一 BudgetPolicy resolver，收敛 catalog.py 与 skills/service.py 重复定义。
- 将最新预算触限映射到明确 finish_reason，保留 subtype、partial、usage 和可继续条件；补齐脱敏 stderr。
- 增加会话 Run 检查器的概览、预算与诊断页，以及发送前的生效限额预览。
- 把固定 0.20 美元策略迁为 legacy 预设，提供新预设选择与预算差异；未确认不自动重试已失败任务。
- 首先用历史三条触限事件离线重放，验证诊断与 UI；再由用户明确触发一次小预算真实验证。

验收：无需改代码可修改新 Run 的预算，最近三条历史失败能被正确解释；不扩大工具权限，不用成功样式发布未完成导读。

### P0-B：用户连接、模型与执行方案

- 新增连接/凭据/模型/角色/Profile 注册与版本；实现预检和能力状态。
- 管理员确认后将当前宿主连接复制到 Firework 私有凭据库，仅供该管理员；不修改原始文件。
- 两个隔离测试账号使用不同 mock 网关，同时运行并核对 URL、模型、Key、CLI 配置目录互不串用。
- UI 移除普通偏好 JSON 作为高级模型配置的误导，修正身份文案。

### P0-C：研究 MCP 与 Skills 纳管

- 迁移 10 个内置 Skill、现有版本与 6 个分类；保留归档 ZIP Skill 和历史 Run 关联。
- research MCP 以受保护内置服务登记，13 个工具和当前任务/材料授权不变。
- 支持远程 HTTP MCP 草稿、发现、工具选择与只读样例验证；外部写入默认禁用。
- 把导读/前沿最低工具与输出要求纳入 preflight，显示缺少什么；模型大窗口不冒称材料覆盖已扩大。

### P1：容器 Runner 与完整会话调试

- 配置 CLI path、runtime root 和工具回调 URL，后者改为容器内部 app:8000。
- 建立固定镜像、非 root 用户、稳定挂载、健康检查、队列/会话租约与停机中断恢复。
- 发布协议 6：协商 execution snapshot schema、支持的参数/状态与 Driver 版本；版本不兼容拒绝任务，不能静默回到宿主机凭据。
- 完善分支、检查点、after_seq 事件恢复、配置差异、调试包、跨 Run 额度和调度额度。
- 切换前完整备份身份、研究库、凭据密文及主密钥恢复方案、Skills、PDF 与原生会话；停旧 Runner 后再启新，避免同一任务双执行。
- 回退保留旧镜像与旧数据快照；新配置版本不可由旧 Runner 执行，回退时暂停相应任务而不混用旧凭据。

### P2：高级扩展

管理员批准的 stdio 安装模板、独立 worker 容器、MCP OAuth、可验证协议转换、多模型路由、请求级 OTel/网关预算、完整 CC Switch 配置导入和多 Skill DAG。
这些不是首批必须依赖的基础设施；可先完成可配置、可恢复、可检查的单智能体工作流。

## 12. 验收矩阵

| 场景 | 验收标准 |
| --- | --- |
| 账号隔离 | A/B 并发使用不同 mock 地址、模型、Key；日志与工具均不泄露另一账号配置 |
| 宿主机共存 | Firework 保存/切换连接后，宿主 ~/.claude 及其他项目配置哈希不变 |
| 密钥保护 | 读接口、事件、错误、argv、导出包无明文；撤销后排队与新任务停止使用 |
| 额度修复 | 离线重放三条 error_max_budget_usd，准确显示配置值、估价值和继续入口；任务预算可在 Web 修改 |
| 单次与整次 | 两次各 4096 输出的任务与总输出限额分别计算；流事件与 result 不重复结算 |
| 成本未知 | 未配置价格不显示 0 元；强制金额上限但缺乏可信计价时预检明确阻止 |
| 并发账本 | 两个 Run 同时申请剩余额度只能预留允许部分；失败/取消/重启不重复结算 |
| 视觉 | 文本模型拒绝含图需求；视觉测试明确模型、样本与费用，不以上传成功当理解成功 |
| 1M 上下文 | 声明、Driver 支持与实测范围分开；无付费授权不自动生成 1M 请求；离线边界测试不调用模型 |
| 角色权限 | prompt 角色不能提升账号权限、开启未授权工具或修改预算 |
| Skills | 十个内置、版本/哈希、分类、归档状态迁移完整；ZIP 脚本不因纳管而执行 |
| MCP | 内置十三工具仍遵守论文、任务、工作区约束；外部不能伪装 research；发现不会自动授权 |
| 会话与材料 | 继续保留原生 ID 和 PDF 版本；分支新 ID；缺失会话不静默重建 |
| 产物与运行状态 | 工具已幂等提交且验证通过的导读，不因最后总结触限被隐藏；staged/partial 不冒充已发布 |
| 运行锁 | 同一分支并发提交只允许一个运行者；租约失效的旧进程不能覆盖新结果 |
| SSE 恢复 | 刷新、断线 after_seq 补读不重跑模型、不重复计费/结算 |
| 调试覆盖 | 鉴权、限流、上下文、工具、预算、产物校验、Runner 重启有独立阶段/原因 |
| 调试隐私 | 默认导出无密钥、正文、PDF、图片或隐藏思维链；支持授权与审计可查 |
| 容器迁移 | 旧会话真实续接、取消、重启中断可解释，Web/API 和宿主其他 Claude 场景不受影响 |
| 发布验证 | 编译/参数/权限/账本/日志/状态优先 mock 与离线测试；每种真实能力验证单独确认额度 |

## 13. 实施前必须确定的产品默认值

建议默认：个人连接优先；平台连接需显式授权；自动服务商回退关闭；普通会话单主 Skill；未知价格使用明确选择的 token/时长控制；新外部 stdio 待管理员审批；长期运行受账号与周期额度约束。

需要界面显式选择而不能猜测的事项：真实能力验证费用、追加预算、向新服务商发送会话内容、外部写入工具授权、是否包含正文的调试包。其余常规实现可按本文方案推进，不要求用户逐项审批技术细节。

本文包含完整目标设计；首批 P0-A 额度管理和第二批个人模型连接已实现，见下方交付记录。角色/Profile 独立资源、通用 MCP 配置及容器 Runner 仍未实现。协议 7 传递额度与连接快照及临时凭据，完整 execution snapshot 协商属于后续协议演进，不能视为已具备。



## 13. 首批交付记录（2026-11-21）

本批交付 P0-A 的额度配置与可解释失败闭环。

- 前端入口：设置 → Runner 任务额度，Hash 路径 `/#/settings/runner/budgets`；预设复制、自定义额度编辑、账号默认设置、无模型调用预检；阅读讨论输入区可按次选择。
- 限制：推理轮次、单次输出 token、工具调用次数、时长及可选 CLI 估价守卫。快速/标准/深度研究预设不启用金额守卫，但保留其余限制。原有账号默认沿用 Skill 额度，需显式保存默认预设才会改变后续自动任务。
- 数据迁移 0017：账号工作区内额度、不可变修订和默认设置；乐观版本控制。提交 Run 时保存额度版本及数值快照，修改配置不改变已排队/历史任务。
- API：`GET/POST /api/me/runner/budgets`、`PATCH /api/me/runner/budgets/{id}`、`PUT /api/me/runner/budgets/default`、`POST /api/me/runner/budgets/preflight`；RunCreate 可附 `budget: {id, revision}`。权限/CSRF 沿用已有账号隔离；不允许客户端覆盖工具权限。
- Runner 协议 6：内部提交接收预算快照。使用新预算的任务提交前核对 Runner 版本，旧版不接收任务。历史 Run 无快照时沿用旧策略。
- 诊断：Run 响应增加 `diagnostics`，包括结束原因、原始子类型、有效额度、预算快照及部分输出状态；CLI 额度/轮次中断和超时可解释，正常流中的预算中断保留最近文本，超时也保留已收到文本。前端提供重新编辑后手动发送；没有自动付费重试，也没有独立“追加额度继续”端点。
- 不提供：服务商账单硬限额、累计 token/每次请求额度、可靠请求级账本、原始 stderr 调试包、连接密钥配置、模型能力检测、MCP 新增服务、容器执行。
- 验证：前端 229 项、后端相关 104 项及生产构建通过。使用模拟 CLI 和隔离数据库，不调用真实模型。用户需自行选择新额度后发起正式任务；历史失败不会自动重放。


## 14. 第二批：个人模型连接（2026-11-21）

### 实际交付

- 前端 `/#/settings/runner/connections`，用户菜单“模型连接”快捷入口，与额度页共用设置导航。创建/编辑/复制连接、启停、版本冲突、设为账号默认；复制不复制密钥，编辑留空保留密钥。更改目标地址或鉴权方式时要求重填 Key。
- 每个连接暂包含一个模型：API Base URL、API Key、x-api-key/Bearer 鉴权、精确模型名称、图片理解声明、4096–1000000 上下文声明，以及研究角色补充要求。只接收 Anthropic Messages 兼容接口，不做 OpenAI 格式转换。能力状态为 not_tested；配置预检不访问模型，不验证服务可达性或计费。声明 1M 不会擅自修改模型名称、启用 beta 或保证有效上下文容量。
- 账号内默认连接只影响新会话；阅读输入区可在尚无运行记录的会话中选择连接。首轮提交后固定连接快照和原生配置目录；更换连接、修订连接后使用新会话，不暗中转发旧会话历史。独立账号未配置连接时拒绝执行，不能继承宿主机凭据；原管理员 legacy 模式保留兼容，不自动导入原有密钥。
- 数据迁移 0018：runner_connections、runner_connection_settings 和 conversations.runner_connection_json。Run 的 execution_policy_json 保存无密钥快照及用户选择；当前版本只存一份连接凭据，修订/停用会阻止旧版本排队任务继续执行。
- API：GET/POST `/api/me/runner/connections`、PATCH `/api/me/runner/connections/{id}`、PUT `/api/me/runner/connections/default`、POST `/api/me/runner/connections/preflight`。RunCreate 增加可选 `connection: {id, revision}`；诊断中可看到绑定连接与版本。
- AES-GCM 加密凭据，随机 nonce、工作区与连接 ID 作为附加认证数据；默认主密钥在工作区 `auth/runner-master.key`，创建权限 0600。可由部署方通过 FIREWORK_RUNNER_MASTER_KEY_FILE 指定现成的 32 字节外部密钥文件；缺失/错误密钥明确失败，不生成替代密钥冒充恢复。
- 协议 7：Web 只在执行时解密，通过私有 Unix Socket 传递临时凭据，Runner 不读取加密主密钥。自定义任务从白名单环境构建，直接使用快照模型，不调用宿主 Claude 配置加载器；ANTHROPIC_API_KEY 与 ANTHROPIC_AUTH_TOKEN 仅取其一。原生会话路径为 `agent/connections/{id}-{revision}/claude-config`，不修改 ~/.claude。
- 排队任务启动前校对当前连接仍启用、版本与快照一致。默认仅公网 HTTPS，执行时拒绝解析到私有/保留地址；内网服务需管理员在 Runner 环境显式设置 FIREWORK_RUNNER_ALLOW_PRIVATE_HOSTS。该检查不是容器级出口隔离，完整网络策略仍属后续容器工作。
- 模型凭据从 MCP 工具子进程环境移除；已知当前 Key 在进度和最终结果持久化前替换为 REDACTED。凭据不放 argv、Run 快照、URL、本地浏览器存储、事件日志或结果文件；不收集原始 stderr。运行结束移除内存任务中的临时凭据。
- 备份：新增受限权限的 runner-secrets 日期归档；独立账号密钥随账号归档，自定义原生会话目录纳入 agent-sessions 归档。恢复连接数据前要求对应 32 字节密钥存在；修复旧原生会话归档恢复时丢失一层目录的问题。外部挂载密钥由部署方另行备份，不自动归档。

### 尚未交付

模型目录自动发现、真实最小能力探测、独立角色/执行方案资源、连接分类与归档、凭据轮换服务、完整运行检查器、通用 MCP 服务管理和容器 Runner 仍待实现。当前静态上下文容量不是累计输入 token 的精确硬限制；角色提示不能扩大 Skill 工具权限。

实现依据：[Claude Code 环境变量](https://code.claude.com/docs/en/env-vars)、[网关组织方式](https://code.claude.com/docs/en/llm-gateway)；加密库参考 [Cryptography](https://cryptography.io/en/latest/hazmat/primitives/aead/)。实际参数优先以当前固定 CLI 和测试结果为准。

第二批验证：前端 232 项、后端相关 122 项通过；服务器因缺少 sqlite3 CLI 跳过的恢复场景，在本机独立环境补跑 6 项全部通过。生产构建通过。模拟 CLI 验证了所选模型/Key/角色注入、Key 不进入事件/结果与 MCP 子进程、连接修订拒绝、账号隔离及会话绑定；没有进行真实模型能力或计费验证。
