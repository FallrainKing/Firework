"""Explicit registered capabilities shared by API and host Runner."""
SKILLS = {
 'chat': {'name':'科研对话','tools':[],'max_calls':0},
 'search_library': {'name':'搜索论文库','tools':['library_search'],'max_calls':2},
 'search_arxiv': {'name':'搜索 arXiv','tools':['arxiv_search'],'max_calls':2},
 'paper_read': {'name':'阅读论文','tools':['paper_read','library_search'],'max_calls':4},
 'paper_review': {'name':'审查论文','tools':['paper_read','library_search'],'max_calls':4},
 'paper_compare': {'name':'对比论文','tools':['paper_read','library_search'],'max_calls':4},
}
TEMPLATES = [
 {'id':'read','name':'阅读论文','description':'围绕关联论文逐步理解方法、实验和局限，可随时继续追问。','kind':'reading','skill':'paper_read','prompt':'请先读取关联论文的已有材料，概述研究问题、核心方法、实验和局限，说明本次覆盖范围。'},
 {'id':'compare','name':'对比论文','description':'选择两篇或以上论文，保留比较上下文和后续讨论。','kind':'comparison','skill':'paper_compare','prompt':'请读取关联论文，比较研究目标、方法、实验设置及局限。区分已有证据与待确认内容。'},
 {'id':'review','name':'审查论文','description':'检查论证与实验，逐条保留问题、证据和改进建议。','kind':'review','skill':'paper_review','prompt':'请基于关联论文的实际材料，从方法合理性、实验充分性和结论边界进行初步审查。'},
 {'id':'discover','name':'发现论文','description':'调用 arXiv 搜索，围绕一个方向持续探索。','kind':'discovery','skill':'search_arxiv','prompt':'请帮我搜索以下方向的论文：'},
 {'id':'library','name':'检索论文库','description':'检索已有论文，并保留检索记录。','kind':'discovery','skill':'search_library','prompt':'请列出论文库中与以下主题相关的论文：'},
 {'id':'chat','name':'自由讨论','description':'保存研究想法与讨论，之后回到同一会话继续。','kind':'chat','skill':'chat','prompt':''},
]
KINDS = {'reading':'阅读','comparison':'对比','review':'审查','discovery':'发现','chat':'讨论','custom':'自定义'}
