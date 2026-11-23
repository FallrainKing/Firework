"""Credential-free Anthropic Messages presets verified against vendor documentation."""
PRESETS=[
 {'id':'anthropic','name':'Anthropic 官方','base_url':'https://api.anthropic.com','auth_type':'api_key','source':'https://platform.claude.com/docs/en/api/messages','region':'国际'},
 {'id':'deepseek','name':'DeepSeek','base_url':'https://api.deepseek.com/anthropic','auth_type':'bearer','source':'https://api-docs.deepseek.com/guides/anthropic_api/','region':'全球'},
 {'id':'minimax','name':'MiniMax M Plan','base_url':'https://api.minimax.io/anthropic','auth_type':'bearer','source':'https://platform.minimax.io/docs/m-plan/claude-code','region':'国际'},
 {'id':'bailian','name':'阿里云百炼 · 按量付费','base_url':'https://dashscope-intl.aliyuncs.com/apps/anthropic','auth_type':'bearer','source':'https://docs.modelstudio.console.alibabacloud.com/en/model-studio/claude-code','region':'国际 · 非 Coding Plan'},
 {'id':'bailian-coding','name':'阿里云百炼 · Coding Plan','base_url':'https://coding-intl.dashscope.aliyuncs.com/apps/anthropic','auth_type':'bearer','source':'https://docs.modelstudio.console.alibabacloud.com/en/model-studio/claude-code','region':'国际 · 专用套餐 Key'},
 {'id':'kimi','name':'Kimi / Moonshot','base_url':'https://api.moonshot.ai/anthropic','auth_type':'bearer','source':'https://platform.kimi.ai/docs/guide/claude-code-kimi','region':'国际'},
 {'id':'custom','name':'自定义 Anthropic 兼容','base_url':'','auth_type':'api_key','source':None,'region':'自定义'},
]
for preset in PRESETS:preset.update(protocol='anthropic_messages',verified_at='2026-11-23',model='',vision='unknown')
