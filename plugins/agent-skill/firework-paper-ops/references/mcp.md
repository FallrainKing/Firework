# Firework MCP：本机处理与成果回传

使用Python 3，无第三方依赖。解压完整Skill包，保留scripts/firework.py与firework_mcp.py相邻；将MCP服务加入支持stdio的本机智能体：

```json
{"mcpServers":{"firework":{"command":"python3","args":["/absolute/path/firework-paper-ops/scripts/firework_mcp.py"],"env":{"FIREWORK_URL":"https://your-firework.example","FIREWORK_TOKEN_FILE":"/absolute/path/private-token","FIREWORK_UPLOAD_ROOT":"/absolute/path/research-files"}}}}
```

令牌在Firework“外部智能体接入”中创建，以私有文件保存（macOS/Linux权限600），不要放入提示词或提交到Git。上传/下载只能访问显式指定研究目录，不能上传令牌文件。没有对应授权的工具会被拒绝，不自动重试。

## 页面上下文

右上角用户菜单开启当前页面共享。context:read用于窗口列表及上下文；读取论文仍需papers:read，读取PDF需files:read。多个窗口必须明确选择context_id；get_context返回revision，read_current_resource要求expected_revision。切页、过期、登出或停止共享后，旧目标不能继续作为“当前页面”。不读取浏览器历史、草稿、API设置或系统其他窗口。

选区需在PDF浮层显式共享，额外授权context:selection；分享有5分钟期限，不与普通页面共享混同。

## 本机成果提交

先读取原文身份与页面，再在本机运行自己的Skill。附件用firework_upload_file上传取得文件ID；firework_download_pdf可把PDF下载至研究目录。不需要服务器重新调用模型。

firework_submit_research接受body与稳定request_key，例如：

```json
{
  "request_key":"local-review-upload-1",
  "body":{
    "schema_version":"research-submission/v1",
    "client_job_id":"my-review-1",
    "declared_skill":"my-paper-reviewer@1",
    "artifact":{"title":"论文阅读概要","kind":"guide","markdown":"## 研究问题\n本机生成的阅读结果","paper_ids":[27],"status":"complete","file_ids":[]},
    "annotations":[],
    "target_language":"zh-CN"
  }
}
```

artifact字段复用references/api.md中的产物接口，支持kind reading/review/comparison/guide/frontier/note/file。导读与阅读成果出现在左侧导读及研究产物库。annotations为标准Annotation字段（paper_id、file_version、page、kind、quote、rects、content、color），批注必须属于关联论文；高亮必须有可核验引句，几何位置重新对照原PDF解析，不能猜页码/坐标。服务器标记为AI来源，用户可采纳后编辑。

提交translation时填写原文Context（paper_id、file_version、page、quote、rects），artifact.markdown作为译文，target_language为语言。原文无法唯一定位时提交失败，不制造假的服务器Run。知识使用firework_submit_knowledge提交候选，仍由Web审核；前沿报告使用firework_submit_frontier_report，复用既有报告格式和待批准条目。

回执包含artifact_id/revision、annotation_ids、translation_id及链接，标明external与model_called=false。网络结果未知时，用firework_sync_receipt(client_job_id)核对，或以原request_key重试相同body。相同client_job_id不得用于不同内容；更新产物使用expected_revision。附件先上传，结果后原子提交，失败不会保存一半批注；已上传附件可复用。不要因界面切到论文B就把此前论文A的结果改绑到B。

## 权限

- 查页面：context:read；选区另需context:selection。
- 读论文/下载：papers:read / files:read。
- 产物/附件/同步回执：artifacts:read/write；批注与翻译回传另需annotations:write。
- 前沿报告：frontier:read/write；知识候选/召回：knowledge:write/read。

遵守论文白名单、账号隔离、版本和幂等规则。本机Skill名称/版本是调用方声明，不冒充服务器注册Skill或服务器Run。MCP不提供用户管理、服务器模型执行或任意浏览器控制。
