# 阅读、模型配置与本机 MCP 交付

日期：2026-11-23。业务迁移0026、身份schema3、Runner协议12。对应 [R1–R5设计](READING-CONTEXT-CONFIGURATION-PLAN.md) 和 [实施计划](IMPLEMENTATION-PLAN.md)。本页记载实际首批实现，不把目标方案的扩展全部视为已交付。

## 功能与实际边界

| 阶段 | 本轮交付 | 边界 |
| --- | --- | --- |
| R1 | 翻译保留quote/rects；服务端对照原PDF核验；唯一引句精确定位、重复引句结合选区；支持旋转页面；菜单外点/失焦/Escape关闭 | 无文字或歧义仅跳页；旧PDF证据打开原版本，不将旧坐标套到新文件；无自动OCR |
| R2 | 高亮、备注、手绘与AI批注统一在批注页；高亮可编辑备注；AI采纳为个人副本；概要/阅读路线及本机阅读产物进导读 | 导读Skill原有材料契约保持；上传Skill仍需已支持的placement/工具契约，不自动执行任意包脚本 |
| R3 | 7项供应商/自定义预设、独立模型连接、网络与明确触发的最小流式模型测试、测试修订/取消；底部连接条与分支预览 | 仅Messages兼容协议；最小测试是Runner发出的受控Messages请求，不是完整Claude CLI任务。测试不能认证视觉、1M、工具链或供应商全部模型 |
| R4 | 首页/阅读版本与页码/前沿主题报告/比较会话/论文库分类/产物资源Hash地址，显式地址优先 | 内部论文标签按paper_id去重；历史版本可用深链独立读取和保存位置，未建立同一论文多版本的内部标签管理；批注单条深链聚焦后续扩展 |
| R5 | 默认关闭的窗口上下文分享、选区显式分享、45秒TTL、语义修订、登出失效；本机stdio MCP读取与成果写回、附件上传下载、批注/翻译投影、前沿回传、幂等回执 | 不监测操作系统其他窗口；不含远程Streamable HTTP、资源订阅、通用进程Bridge或页面控制；Token scope和论文白名单仍单独生效 |

## 双路径工作方式

Firework内：技能库上传ZIP → 预检与分类/显示名/版本/可用入口 → 选择已发布兼容Skill → 明确触发服务器智能体 → 保存真实Run和产物。既有Skill工具授权及隔离执行继续生效。

本机：本机智能体运行本机Skill → MCP读获准论文/窗口 → 本机处理 → 上传附件 → 提交稳定client_job_id成果 → Web展示与审核。Firework不取得本机模型Key，不重复调用服务器模型，不将调用方声明的Skill或结果伪装为服务器Run。

技能包下载入口在“外部智能体接入”，包内含标准库REST客户端、stdio MCP服务与配置说明。完整配置和提交例子见 [MCP说明](../plugins/agent-skill/firework-paper-ops/references/mcp.md)。本轮不自动编辑用户电脑的智能体配置。

## 实际接口

完整注册清单见 [API路由](API-ROUTES.md)。以下路径不是设计占位：

| 范围 | 接口 |
| --- | --- |
| 阅读 | `POST /api/reader/anchors/locate`；`GET /api/reader/papers/{paper_id}?version_id=...`；state读取可带file_version；`POST /api/reader/annotations/{ident}/adopt` |
| 供应商与模型 | `GET /api/me/runner/connections/presets`；`POST /api/me/runner/connections/{ident}/models` |
| 测试 | `POST /api/me/runner/connections/{ident}/tests`；`GET /api/me/runner/connections/tests/{tid}`；`POST /api/me/runner/connections/tests/{tid}/cancel` |
| 浏览器上下文 | `POST /api/workbench/contexts`；`PUT /api/workbench/contexts/{ident}`；`POST /api/workbench/contexts/{ident}/selections` |
| 对外读取 | `GET /api/external/v1/contexts`；`GET /contexts/{ident}`；`GET /contexts/{ident}/resource?expected_revision=...`；`GET /selections/{ident}`（后3项同外部前缀） |
| 本机成果 | `POST /api/external/v1/research-submissions`；`GET /api/external/v1/research-submissions/{client_job_id}`；文件/论文/产物/知识/前沿复用既有接口 |

ResearchSubmission包含schema_version、client_job_id、artifact、annotations、可选translation、target_language与declared_skill，具体校验模型见 `app/research/submissions.py`。annotations/translation必须属于成果论文；高亮与译文需要可定位原文。页级note可以不伪造精确坐标。附件先上传，成果和投影在同一账号库事务中提交。

重复请求键和相同client_job_id/body返回既有回执；同job不同body返回409。回执返回稳定产物、修订、批注/翻译ID与链接。修改已有产物继续使用expected_revision；知识只创建候选，论文发现仍经批准入库。

## 安全与状态

浏览器更新使用会话Cookie和CSRF，服务端校验论文、PDF版本、会话、分类和报告归属。每次应用加载注册独立上下文ID；共享默认关闭，关共享或登出即拒绝读取，后台页面不作为有效当前窗口，断网/关闭最长45秒过期。页面focus是上报状态，不等于操作系统焦点检测。

心跳序号用于拒绝乱序包；外部revision只在资源、页码、辅助页等语义改变时递增，正常心跳不造成虚假的context_changed。多窗口必须明确选择context_id。共享选区最长5分钟，仍要求页面共享有效及单独context:selection授权；不共享输入草稿、图片、设置或Key。

外部上下文读取需context:read；论文/文件/产物/批注/前沿/知识仍需各自scope，且受论文白名单限制。关闭页面共享不撤销独立成果写入权限，撤销令牌会停止该令牌所有访问。下载文件到指定研究目录；上传目录限定、文件类型/大小检查，令牌文件禁止上传。

供应商测试从Runner运行，不发送任意提示词/文件/工具。网络检查不带Key；模型检查固定“Reply with OK.”、max_tokens=32、限时30秒、不跟随跳转、不自动重试。服务端只保存脱敏结果，不保存请求Key。取消时若Runner断开，页面记录取消，远端仍受超时约束，不能保证供应商不计费。

## 数据与迁移

0026增量加入：翻译锚点JSON；connection_models/test；workspace_contexts/context_selections；reader_external_translations；external_submissions；批注产物与采纳来源关联。保留全部既有书目/文件/会话/原生记录，原PDF不可变。上下文过期记录按保留期限清理；客户端明确的论文版本保留阅读位置。

供应商子模型复制为独立加密连接，不将修改父连接凭据自动传播；连接修订改变使旧测试过期。修改自定义模型时同样固定Claude模型档位与子智能体模型，避免默认档位意外落回其他模型。宿主全局Claude设置不变。

## 验证与发布

隔离测试包含真实PDF锚点/旋转/旧版本、账号权限/过期/乱序/登出、同任务去重、失败回滚、AI采纳、译文移除、stdio协议和实际本地HTTP桥接领域API。供应商响应使用模拟流，未把测试通过表述为所有真实供应商已认证。本次不自动运行生产研究或长上下文测试。

发布前联合执行完整前后端回归、生产构建、技能包格式、文档链接和实际OpenAPI清单检查；发布保留成套数据备份与旧镜像，同时升级应用和Runner。联合验证：完整后端 **363通过、5跳过**（缺少sqlite3命令行）；前端 **269通过**，类型检查和生产构建通过；旧PDF与本机回传25项专项通过；技能包格式通过；26份Markdown、315条本地链接和242条实际HTTP路由核对通过。模型响应使用模拟流，真实stdio→HTTP→领域API链路在隔离环境通过。线上发布结果单独记录。


浏览器补充修复：初始化读取持久位置时暂停地址回写，明确深链页码/辅助栏先于旧状态应用；显式会话不可用时显示错误，不静默绑定其他会话。补充2项回归，最终前端269通过。


发布核对：代码 `e3d27c2` 与浏览器修复 `1f59edd` 已推送 main 并部署。应用迁移0026、Runner协议12、242条HTTP路由、7项预设、含MCP的6文件Skill ZIP、匿名401、上下文更新、数据库外键及公网health通过；没有新增外部令牌或服务器模型任务。Chrome已核对菜单关闭、返回首页、供应商预设和测试入口、统一批注、底部连接条；明确链接 `/#/reader/17?session=49&page=2&panel=notes` 刷新后仍为第2页与批注页。

发布前备份记录：服务器 `/tmp/firework-reading-context-backup.log`；旧应用镜像 `firework-before-reading-context:20261123`。原生CLI容器镜像及宿主全局配置未改变。此次未实际调用付费模型，视觉/1M与各真实供应商效果不在验收结论内。


## 导读旧缓存修复（2026-11-23）

修复导读辅助区将所有reading产物展开造成的混杂：同一滚动区一次只显示一份结果，结构化导读与阅读路线优先；其他结果通过选择器查看。根据真实Run purpose过滤历史翻译/解释/导读执行回执，不以旧kind标签直接判定。PDF证据/材料哈希不匹配的结果不混入当前版本，未核验历史需主动选择。保留原始会话和产物来源。

导读查询可带file_version，产物查询可带paper_id和reader_file_version；未新增HTTP路径或数据库迁移。辅助区和导读请求按论文ID+PDF哈希隔离，忽略迟到响应/错误，重新激活缓存标签时刷新。

验证：前端273通过及生产构建通过；隔离后端相关24项通过，涵盖旧分类、材料版本、导读、知识与本机回传。
