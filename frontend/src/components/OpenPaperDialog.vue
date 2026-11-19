<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { papersApi } from '@/api/papers'
import type { Paper } from '@/api/types'
import StateFeedback from '@/components/StateFeedback.vue'

const emit = defineEmits<{ close: []; open: [paperId: number]; import: [] }>()
const query = ref('')
const papers = ref<Paper[]>([])
const loading = ref(false)
const error = ref('')
const hasMore = ref(false)
const searchInput = ref<HTMLInputElement | null>(null)
let epoch = 0
let timer: ReturnType<typeof setTimeout> | undefined
async function search(more = false) {
  const current = ++epoch
  loading.value = true
  error.value = ''
  try {
    const result = await papersApi.list({ q: query.value.trim(), offset: more ? papers.value.length : 0, limit: 30 })
    if (current !== epoch) return
    papers.value = more ? [...papers.value, ...result.papers] : result.papers
    hasMore.value = result.has_more
  } catch (e) {
    if (current === epoch) error.value = e instanceof Error ? e.message : '论文列表载入失败'
  } finally { if (current === epoch) loading.value = false }
}
watch(query, () => {
  ++epoch // Discard old results immediately, even during the debounce interval.
  loading.value = true
  clearTimeout(timer)
  timer = setTimeout(() => void search(), 200)
})
onMounted(() => { void search(); searchInput.value?.focus() })
onUnmounted(() => { ++epoch; clearTimeout(timer) })
</script>

<template>
  <div class="dialog-overlay" @click.self="emit('close')" @keydown.esc="emit('close')">
    <section class="open-paper-dialog" role="dialog" aria-modal="true" aria-labelledby="open-paper-title">
      <header><div><span class="eyebrow">READING MATERIALS</span><h2 id="open-paper-title">打开一篇论文</h2></div><button aria-label="关闭论文选择" @click="emit('close')">×</button></header>
      <p class="muted">从论文库选择，或导入新的阅读材料。</p>
      <div class="picker-search"><input ref="searchInput" v-model="query" type="search" placeholder="搜索标题、作者或摘要…" aria-label="查找库中论文" /><button @click="emit('import')">＋ 导入新论文</button></div>
      <div class="open-paper-list" :aria-busy="loading">
        <StateFeedback class="list-feedback" :loading="loading && !papers.length" :error="error || null" :empty="!loading && !error && !papers.length" empty-text="还没有匹配的论文，可以导入 PDF、链接或书目。" @retry="search()" />
        <button v-for="paper in papers" :key="paper.id" class="open-paper-row" :disabled="loading" @click="emit('open', paper.id)">
          <img v-if="paper.thumbnail_url" :src="paper.thumbnail_url" alt="" loading="lazy" /><span v-else class="paper-cover" aria-hidden="true">▤</span>
          <span class="paper-detail"><strong>{{ paper.title }}</strong><small>{{ paper.authors?.slice(0, 3).join(' · ') || '作者信息待补全' }}</small></span>
          <span :class="['paper-availability', { missing: !paper.has_pdf }]">{{ paper.has_pdf ? '打开原文 ↗' : '补充全文' }}</span>
        </button>
        <button v-if="hasMore" class="load-more" :disabled="loading" @click="search(true)">{{ loading ? '载入中…' : '显示更多论文' }}</button>
      </div>
      <footer class="muted">已打开的论文会切换到原标签。关闭标签会保留论文和阅读记录。</footer>
    </section>
  </div>
</template>

<style scoped>
.dialog-overlay { position:fixed; inset:0; z-index:50; background:rgb(22 39 32 / .3); display:flex; align-items:center; justify-content:center; padding:20px; backdrop-filter:blur(3px); }
.open-paper-dialog { width:min(720px,100%); max-height:85dvh; background:var(--bg); border:1px solid var(--border); border-radius:18px; padding:24px; box-shadow:0 16px 64px rgb(0 0 0 / .12); display:flex; flex-direction:column; }
header { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.eyebrow { font-size:9px; letter-spacing:.15em; color:var(--accent); }
h2 { font-size:21px; margin:5px 0 0; font-weight:600; }
header button { padding:2px 10px; font-size:23px; border:0; }
p.muted { font-size:12px; margin:10px 0 20px; }
.picker-search { display:flex; gap:8px; margin-bottom:16px; }
.picker-search input { flex:1; min-width:0; font-size:12px; }
.picker-search button { white-space:nowrap; font-size:12px; padding:8px 12px; }
.open-paper-list { overflow-y:auto; min-height:80px; }
.open-paper-row { width:100%; display:flex; align-items:center; gap:14px; padding:14px 4px; border:0; border-bottom:1px solid var(--border); border-radius:0; text-align:left; }
.open-paper-row:hover { background:var(--surface); }
.open-paper-row img,.paper-cover { width:44px; height:54px; flex-shrink:0; object-fit:cover; background:var(--surface); border:1px solid var(--border); border-radius:5px; }
.paper-cover { display:grid; place-items:center; color:var(--accent); font-size:23px; }
.paper-detail { flex:1; min-width:0; display:flex; flex-direction:column; gap:5px; }
.paper-detail strong { font-size:12px; font-weight:550; overflow-wrap:anywhere; }
.paper-detail small { font-size:10px; color:var(--text-muted); }
.paper-availability { color:var(--accent); font-size:10px; flex-shrink:0; }
.paper-availability.missing { color:var(--text-muted); }
.list-feedback { padding:16px 0; }
.list-message { padding:20px; font-size:12px; text-align:center; }.load-more { width:100%; margin-top:12px; font-size:12px; }
footer { margin-top:18px; font-size:10px; }
@media(max-width:500px) { .open-paper-dialog { padding:18px; } .paper-availability { max-width:30px; } }
</style>
