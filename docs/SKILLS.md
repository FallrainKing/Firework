# Skills 管理与扩展开发

当前基线：2026-11-19 / `13956f9`。Skill 负责研究处理，平台提供受限工具、版本、会话和产物管理。上传 ZIP 可以扩展提示与资源组织，不能自动扩展服务端任意权限。

## 1. 内置技能

| Skill ID | 作用 |
| --- | --- |
| chat | 科研讨论 |
| search_library / search_arxiv / paper_discover | 库内或外部检索 |
| paper_import | 已授权来源入库 |
| paper_read / paper_review / paper_compare | 阅读、审查与比较 |
| paper_guide | 明确触发的结构化导读与原文批注 |
| frontier_monitor | 背景前沿发现与结构化证据报告 |

执行额度以 `app/agent/catalog.py` 为准，汇总见 [架构](架构.md)。内置资源在 `skills/{id}/`；上传资源在 data/skills 中按版本保存。

## 2. ZIP 结构与限制

允许根目录入口或一个顶层技能目录中的 SKILL.md；推荐只包含一个明确入口。可选 skill.json 与 references 等资源：

```text
my-guide/
  SKILL.md
  skill.json
  references/
    reading-rules.md
```

结构预检由 `app/skills/package.py` 执行：ZIP 最大 20 MiB、展开总量 100 MiB、最多 1000 个成员、路径深度最多 12、路径长度上限 200。拒绝路径穿越、绝对路径、符号链接和重复成员等；预检/安装不执行包内脚本。可读资源扩展名为 md/txt/json/yaml/yml。

推荐 manifest 示例：

```json
{
  "slug":"my-paper-guide",
  "version":"1.0.0",
  "description":"用户确认后生成有证据的导读与解释",
  "requested_tools":["reader_guide_context","reader_guide_material","reader_guide_submit"],
  "templates":[{"name":"论文重点导读","description":"结构化重点和解释","prompt":"请根据真实材料生成导读。"}]
}
```

安装时选择名称、分类、标签和预算档位。预算 profile 以安装配置写入为准，不能靠 manifest 任意增大调用次数或权限；普通上传技能最多 4 次工具调用。short 为 1024 输出 token，read 为 8192，其他额度见执行策略。

## 3. 安装、版本与验证

1. `POST /api/skills/imports` multipart 字段 archive 上传，只做预检和暂存。
2. 查询导入报告；通过后 `POST /api/skills/imports/{id}/install` 配置安装。
3. 查看技能、版本、资源、审计并选择默认版本。追加版本指定现有自定义 skill_id 和新版本名，不能覆盖已有版本。
4. 选择模板并明确执行最小验证；`validate-run` 会创建真实任务，应限制提示与材料。
5. 验证通过再用于正式任务；可启停/归档或切回默认版本，历史 Run 仍保留原引用。

结构 validated 表示包与注册满足当前检查，不等于研究效果或图像能力已验证。新 Run 固定技能版本与哈希；修改包不会偷偷改变既有任务。不要从文件管理器直接覆盖运行资源来“升级”版本。

## 4. 可登记工具

当前白名单位于 `app/skills/service.py`：paper_search、paper_import、library_search、arxiv_search、paper_read、paper_page、skill_resource、frontier_context/search/report、reader_guide_context/material/submit。

清单有权限不代表任意任务可用。例如导入/追踪/导读内部工具还要求匹配对应任务 Run；普通会话直接声明这些工具并不能绕过任务绑定。新工具需增加实现、输入模型、授权、运行记录与兼容测试，必要时升级 Runner 协议。

skill_resource 只读取允许的资源范围，不启动包内命令。需要外部脚本、依赖安装、视觉或代码访问的技能必须先做适配，不能仅上传同名 Skill 就宣称能力完整。

## 5. 自定义导读技能

要出现在自动批注选择器，当前版本需 enabled、validated，并具有 reader_guide_context、reader_guide_material、reader_guide_submit，工具次数至少 3、输出额度至少 4096。普通上传技能需选择 read 档位才满足输出额度；这也意味着它与内置 paper_guide 的 $0.20 档位不同，界面会显示所选技能预算。

执行步骤：读取 context 获取任务/文件/清单 → material 选择用户上限内真实页面 → submit 提交 `paper-guide/v1`。当前不传任意 paper_id、文件路径或矩形，不接受 asset 图表锚点；唯一匹配、覆盖核对、落库和绘制由平台处理。

结构字段包括 summary、reading_route、items、coverage、unknown_fields。每条 item 含 key、类别、优先级、标题、why_important_md、explanation_md、claim_type、anchors、follow_up_questions、uncertainties。引用必须来自本任务材料，不把未读页、图像或代码写成已核验。

权威模型：`app/reader/guides/schemas.py`；参考 [接口设计](Skill驱动导读批注接口设计.md) 和 [验收](Skill导读与批注实现验收.md)。默认最多 6 页材料，用户确认前不执行；同配置优先复用，失败不无限重试。

## 6. 复用科研技能与来源

前沿已包含 Nature 发现流程的适配资源，来源和说明见 `skills/frontier_monitor/NOTICE.md`。完整 kelip-paper-reading、nature-reader、Paper Card 的材料链与视觉依赖仍未全部接入；平台不把简化流程冒称完整上游能力。

归档原包、资源、数据库注册表和版本引用需同日备份，见 [备份恢复](BACKUP-RESTORE.md)。

账号隔离补充：自定义包、版本引用、分类、审计、模板与原生任务工作区按账号隔离；内置通用资源共享代码。当前仅原管理员可登录，普通账号的管理状态不自动开放登录。
