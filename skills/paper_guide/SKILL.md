---
name: paper_guide
version: 1.0.0
---
用户明确触发的论文导读和智能批注。你负责总结、选重点、解释；平台负责证据校验、坐标计算和批注发布。不能直接调用普通批注写入，不能生成矩形坐标或修改个人批注。

1. 首先 reader_guide_context，读取绑定论文版本、真实目录、max_pages、max_items 和阅读目标。
2. 调用 reader_guide_material 提供页码数组，总共不超过 max_pages。优先摘要/引言、核心方法或总览、关键实验/结论；没有目录时可选开头、中间、末尾代表页。只根据实际返回的文本分析，明确没有读取的章节。当前无视觉/代码能力，figures_read/code_read 必须 false。不要为未读部分编造结论。
3. 用 reader_guide_submit 提交完整 paper-guide/v1 JSON（详见工具 Schema）：
   - material_manifest_id 来自 context；coverage.material_ids 来自 material。
   - summary 四个字段：问题、核心思路、贡献、边界，短中文 Markdown，缺材料明确未知。
   - reading_route 每步说明先看什么、为什么看，item_keys 引用本次重点 key，block_ids 必须来自工具。
   - items 最多 max_items 个，建议少量精确重点。每条给 category、priority、title、why_important_md、explanation_md、claim_type、anchors、follow_up_questions、uncertainties；每条解释简短具体，不把阅读问题当作论文缺陷。
   - text anchor 使用真实 block_id 与从该块原样摘录的一句短英文/中文 quote；需要整块说明可用 block anchor。无需 prefix/suffix 时省略。不能引用材料之外的块，不能发 asset anchor。
   - 区分 author_claim / reported_evidence / agent_interpretation / reading_question。
   - unknown_fields 明确哪些内容未核查。coverage.scope 在部分页面时使用 selected_pages。
4. 同一次提交同时包含总结、路线及重点解释。工具反馈定位不确定时如实保留；不要反复付费重试。最多一次结果提交，结构无效可按明确报错有界修正一次。
5. 不分站等待回复，不自动开启其他阅读任务。最后简短告知已提交，覆盖以工具记录为准。后续是否阅读/继续精读由用户触发。
