<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { guidesApi, type PaperGuide, type GuideItem } from '@/api/guides'
import { renderMarkdown } from '@/shared/markdown'
import type { SelectionContext } from '@/api/types'
const props = defineProps<{ paperId: number; fileVersion: string; jump: (ctx: SelectionContext) => void }>()
const emit = defineEmits<{ close: [] }>()
const guides = ref<PaperGuide[]>([]), selectedId = ref(''), loading = ref(false), error = ref('')
const selected = computed(() => guides.value.find(g => g.id === selectedId.value))
const sameVersion = computed(() => selected.value?.file_version === props.fileVersion)
const labels: Record<string, string> = { published: '已发布', partial: '部分材料', stale: '旧文件版本', failed: '失败', cancelled: '已取消', running: '执行中', queued: '排队中', dispatching: '提交中', staging: '校验中' }
const summaryLabels = { problem_md: '研究问题', approach_md: '核心思路', contributions_md: '贡献', limitations_md: '范围与边界' }
const panel = ref<HTMLElement | null>(null), priorFocus = document.activeElement as HTMLElement | null
let disposed = false
async function load() {
  loading.value = true; error.value = ''
  try { const data = await guidesApi.history(props.paperId); if (disposed) return; guides.value = data.guides; selectedId.value = data.guides[0]?.id ?? '' }
  catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : '历史导读载入失败' }
  finally { if (!disposed) loading.value = false }
}
function locate(item: GuideItem) {
  const anchor = item.anchors[0], guide = selected.value
  if (!guide || !anchor || !sameVersion.value) return
  props.jump({ paper_id: props.paperId, file_version: guide.file_version, page: anchor.page, quote: anchor.status === 'verified' ? anchor.quote : '', rects: anchor.rects })
  emit('close')
}
function exportGuide() {
  const g = selected.value
  if (!g?.result) return
  const text = ['# 历史论文导读', `论文：${props.paperId}\nPDF SHA-256：${g.file_version}\nSkill：${g.skill_id} / ${g.skill_version_id}\nRun：${g.agent_run_id ?? '未提供'}\n状态：${g.status}`, ...Object.entries(g.result.summary).map(([k, v]) => `## ${summaryLabels[k as keyof typeof summaryLabels]}\n\n${v}`), '## 阅读路线', ...g.result.reading_route.map(r => `### ${r.title}\n\n${r.goal_md}`), ...g.items.map(i => `## ${i.item.title}\n\n${i.item.why_important_md}\n\n${i.item.explanation_md}\n\n${i.anchors.map(a => `物理页 ${a.page}（${a.status}）：${a.quote}`).join('\n\n')}`), '## 材料缺口', ...g.result.unknown_fields.map(u => `${u.path}：${u.reason}`)].join('\n\n')
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' })), a = document.createElement('a')
  a.href = url; a.download = `paper-${props.paperId}-guide-${g.id}.md`; a.click(); URL.revokeObjectURL(url)
}
function keys(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); emit('close'); return }
  if (event.key !== 'Tab') return
  const elements = Array.from(panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled),select') ?? []), first = elements[0], last = elements.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
onMounted(() => { panel.value?.focus(); void load() })
onUnmounted(() => { disposed = true; if (priorFocus?.isConnected) priorFocus.focus() })
</script>
<template>
  <Teleport to="body"><div class="guide-history-overlay" @click.self="emit('close')"><section ref="panel" tabindex="-1" class="guide-history-dialog" role="dialog" aria-modal="true" aria-label="历史导读" @keydown="keys">
    <header><h2>历史导读</h2><button aria-label="关闭历史导读" @click="emit('close')">×</button></header>
    <p class="muted">只读查看最近 30 次导读，不生成新任务，不替换当前 AI 批注图层。</p>
    <p v-if="loading" role="status">正在载入…</p><p v-if="error" role="alert">{{error}} <button @click="load">重试</button></p>
    <p v-if="!loading && !error && !guides.length">暂无历史导读</p>
    <label v-if="guides.length">导读记录<select v-model="selectedId" aria-label="选择历史导读"><option v-for="g in guides" :key="g.id" :value="g.id">{{ g.created_at || g.id }} · {{ labels[g.status] || g.status }} · {{g.skill_id}} v{{g.skill_version_id}}{{g.hidden?' · 已隐藏':''}}</option></select></label>
    <article v-if="selected">
      <p class="source">PDF：{{selected.file_version}}<br>Run：{{selected.agent_run_id || '未提供'}} · {{labels[selected.status] || selected.status}}</p>
      <p v-if="!sameVersion" class="version-warning">此导读来自不同 PDF 版本，仅供查阅；不会在当前原文定位或叠加旧批注。</p>
      <p v-if="selected.error" role="status">{{selected.error}}</p>
      <template v-if="selected.result">
        <button @click="exportGuide">导出此导读 MD</button>
        <section v-for="(label,key) in summaryLabels" :key="key"><h3>{{label}}</h3><div class="markdown-content" v-html="renderMarkdown(selected.result.summary[key])" /></section>
        <h3>建议阅读路线</h3><ol><li v-for="r in selected.result.reading_route" :key="r.key"><strong>{{r.title}}</strong><div class="markdown-content" v-html="renderMarkdown(r.goal_md)" /></li></ol>
        <section v-for="i in selected.items" :key="i.id" class="history-item"><h3>{{i.item.title}}</h3><div class="markdown-content" v-html="renderMarkdown(i.item.why_important_md)"/><div class="markdown-content" v-html="renderMarkdown(i.item.explanation_md)"/><blockquote v-for="(a,index) in i.anchors" :key="index">物理页 {{a.page}} · {{a.status==='verified'?'引文已核验':'页级参考'}}<br>{{a.quote}}</blockquote><button v-if="i.anchors.length" :disabled="!sameVersion" @click="locate(i)">定位当前版本原文</button></section>
        <p v-for="u in selected.result.unknown_fields" :key="u.path">材料缺口：{{u.reason}}</p>
      </template><p v-else>此记录没有可发布的导读结果。</p>
    </article>
  </section></div></Teleport>
</template>
<style scoped>
.guide-history-overlay{position:fixed;inset:0;z-index:85;display:grid;place-items:center;padding:16px;background:rgb(0 0 0 / .3)}.guide-history-dialog{width:min(850px,100%);max-height:88dvh;overflow:auto;box-sizing:border-box;padding:24px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:var(--radius-panel,10px);box-shadow:var(--shadow)}header{display:flex;align-items:center;justify-content:space-between}h2{font-size:20px;margin:0}h3{font-size:15px;margin-top:20px}label{display:grid;gap:8px}select{width:100%;min-width:0}.source{font-size:12px;overflow-wrap:anywhere;color:var(--text-muted)}.muted{color:var(--text-muted);font-size:13px}.version-warning{padding:10px;background:var(--accent-soft);color:var(--accent)}.history-item{border-top:1px solid var(--border);margin-top:16px}blockquote{border-left:2px solid var(--border);margin:12px 0;padding:4px 12px;font-size:13px;white-space:pre-wrap}[role='alert']{color:var(--danger)}
</style>
