# 发布一致性与界面问题修复交付

日期：2026-11-19。基线：ab7f385。修复分支：fix/release-consistency-20261119。

## 修复内容

1. 论文标题：将标题查询函数改名为 resolvePaperTitle，头部显式使用 props.paperTitle；解决函数源码被渲染成标题的问题。
2. 技能分类：按 category.id 构造技能分类列表，解决已归类技能仍显示未分类、前端筛选不命中的问题。
3. 保存反馈：修正空字符串触发 Boolean|string 的隐式布尔转换；重新保存时不同时展示旧成功提示；设置初次载入不显示已保存。
4. 同步发布：Web 与宿主 Runner 已更新，协议版本为 2。API 暴露 required_runner_protocol 与 runner_protocol_compatible；发布冒烟拒绝旧协议或离线 Runner。
5. 技能闭环所需修复：安装后的私有目录与文件对齐共享 data 目录属主，保证宿主 Runner 可读；安装失败清理只移除本次新建资源，避免重复安装请求误删已有技能包。

## 验证

- 修复前新增前端回归用例复现 4 个失败场景；修复后前端 31 个文件、168 条测试通过，构建通过。
- 后端技能、用户、迁移、Runner、发布冒烟与 Agent 相关隔离测试：60 条通过；测试模拟模型。
- 发布前备份了数据，并保留 research-assistant-app:before-release-consistency-fix 镜像。
- 发布前确认 queued=0、running=0，随后更新 app 并重启 research-agent-runner。
- 五项服务冒烟通过；真实健康响应 protocol_version=2、runner_protocol_compatible=true。
- Chrome 已确认：正确显示 Attention is All you Need；设置首次打开无已保存误提示；阅读理解筛选能命中已归类技能。

## 一次真实动态技能验证

仅新增一次模型执行，验证链路为 ZIP 上传 → 安装默认停用 → 归入阅读理解 → 启用 → 现有 Runner 执行 → 调用 skill_resource 读取包内参考文件 → 返回验证短语。安装后已先确认宿主用户可读，避免因权限问题重复请求模型。

- 技能：custom:d465f98341e845d7b5b525a5be80bb00；版本 ID：9。
- 运行：bf7babc9dbef47a3951a8194a0c146a3；状态：succeeded；返回：SKILL_RELEASE_OK_8db614b0。
- 模型：qwen4-max[1M]；输入 652、缓存读取 256、输出 96 tokens。
- CLI 估算：$0.005788，cost_verified=false，不作为实际账单。
- 已确认执行记录中的 skill_version_id 和包摘要一致，skill_resource 实际成功读取参考文件。
- 一次性验证技能与会话均已归档，保留运行和审计记录。

## 交付边界

本轮修复前次审查中列出的三个代码缺陷及 Runner 发布遗漏，并修复验证中发现的技能资源权限/失败清理问题。可视化设置、技能分类管理面板等新增交互，以及排队停用/资源重新验签等更深入的设计项，不据此宣称已经全部实现。

截图：release-fix-chrome-reading.jpg、release-fix-skill-category.jpg；完整验证记录见发布修复-动态技能验证记录.json。
