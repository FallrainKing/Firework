"""Stable, non-secret reasons derived from stored events; no paid replay."""
import json
REASONS={
 'connection_unavailable':('connection_unavailable','连接已停用、修订或凭据不可用，本轮没有调用模型。'),
 'runner_protocol_mismatch':('runner_protocol_mismatch','Runner 版本不支持当前额度配置；本轮没有调用模型，请升级运行服务。'),
 'error_max_budget_usd':('budget_usd','本轮达到 CLI 估价金额上限；不是服务商账单或余额不足。'),
 'error_max_turns':('max_turns','本轮达到推理轮次上限。'),
}
def describe(status,metadata,error=''):
    subtype=metadata.get('subtype')
    if subtype in REASONS:return REASONS[subtype]
    text=(error or '').lower()
    if status=='succeeded':return ('completed','本轮已完成。')
    if status=='cancelled':return ('user_cancel','本轮已取消。')
    if status in ('queued','running'):return (status,'本轮尚未结束。')
    if 'timed out' in text:return ('wall_timeout','本轮超过执行时长上限。')
    if 'restarted' in text:return ('runner_restart','运行服务重启，本轮已中断；没有自动重跑。')
    if 'tool call limit' in text:return ('max_tool_calls','本轮达到工具调用上限。')
    return ('execution_error','本轮执行失败，请查看已记录的结果与工具信息；不会自动重试。')

def view(row):
    r=dict(row);meta=json.loads(r.get('metadata_json') or '{}');policy=json.loads(r.get('execution_policy_json') or '{}')
    reason,message=describe(r['status'],meta,r.get('error'))
    return {'finish_reason':reason,'message':message,'subtype':meta.get('subtype'),'effective_budget':{k:policy.get(k) for k in ['max_turns','max_output_tokens','max_calls','timeout_s','max_budget_usd']},'budget_snapshot':policy.get('budget_snapshot'),'connection_snapshot':policy.get('connection_snapshot'),'skill_version_id':r.get('skill_version_id'),'skill_hash':r.get('skill_hash'),'model':r.get('model'),'cost_verified':False,'cost_estimate':r.get('cli_estimated_cost_usd'),'partial_available':bool(r.get('answer')) and r['status']!='succeeded','continuation_requires_new_run':reason in ('budget_usd','max_turns','wall_timeout')}
