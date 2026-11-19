<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { agentApi } from '@/api/agent'
import { sessionsApi } from '@/api/sessions'
import { importsApi } from '@/api/imports'
import { uid32 } from '@/api/client'
import type { Run } from '@/api/types'
import StateFeedback from '@/components/StateFeedback.vue'

const emit = defineEmits<{ 'open-session': [sessionId: number]; 'library-updated': [] }>()

interface SearchPaper { title?: string; authors?: string[]; abstract?: string; arxiv_id?: string; doi?: string; url?: string; source?: string; published?: string; year?: string }

const query = ref('')
const source = ref('arxiv')
const busy = ref(false)
const status = ref('')
const results = ref<SearchPaper[]>([])
const sessionId = ref<number | null>(null)
const error = ref('')
const savingResult = ref(false)
const savedMessage = ref('')
const saveError = ref<string | null>(null)
let stopped = false
onUnmounted(() => { stopped = true })

onMounted(async () => {
  // 对照旧版 discovery.js boot：恢复上次搜索的会话链接与结果跟踪。
  try {
    const cached = JSON.parse(sessionStorage.getItem('research-last-search') || 'null')
    if (cached?.id) {
      sessionId.value = cached.sid
      status.value = '智能体正在检索…'
      await watchSearch(cached.id)
    }
  } catch { /* ignore */ }
})

function renderResults(run: Run) {
  const unique = new Set<string>()
  const out: SearchPaper[] = []
  for (const call of run.tool_calls ?? []) {
    const papers = (call.result as { papers?: SearchPaper[] } | undefined)?.papers ?? []
    for (const p of papers) {
      const key = p.arxiv_id || p.doi || p.url || p.title || ''
      if (unique.has(key)) continue
      unique.add(key)
      out.push(p)
    }
  }
  results.value = out
}

async function watchSearch(id: string) {
  while (!stopped) {
    const run = await agentApi.getRun(id)
    if (stopped) return
    if (['succeeded', 'failed', 'cancelled'].includes(run.status)) {
      renderResults(run)
      status.value = run.status === 'succeeded' ? '搜索结果已保存，可回到会话继续。' : run.status === 'cancelled' ? '搜索已取消。' : '搜索未完成：' + (run.error || '请查看会话')
      return
    }
    await new Promise(r => setTimeout(r, 2000))
  }
}

async function search() {
  const q = query.value.trim()
  if (!q || busy.value) return
  busy.value = true
  error.value = ''
  results.value = []
  try {
    const session = await sessionsApi.create({ template_id: 'discover', title: '搜索：' + q.slice(0, 100), starting_prompt: '', paper_ids: [] })
    sessionId.value = session.session.id
    const run = await agentApi.createRun({
      conversation_id: session.session.id,
      prompt: `请调用 paper_search 搜索 ${source.value === 'both' ? 'arxiv 和 crossref 两个来源（各一次）' : source.value + ' 来源（一次）'}，query 为：${q}。每个来源最多 3 篇。简短说明即可，原始工具结果交由界面展示。`,
      request_key: uid32(),
    })
    status.value = '智能体正在检索…'
    sessionStorage.setItem('research-last-search', JSON.stringify({ id: run.id, sid: session.session.id }))
    await watchSearch(run.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '搜索失败'
  } finally {
    busy.value = false
  }
}

async function addToLibrary(p: SearchPaper) {
  const value = p.arxiv_id || p.doi
  if (!value) return
  savingResult.value = true
  savedMessage.value = ''
  saveError.value = null
  try {
    await importsApi.source({ value, channel: 'auto', request_key: uid32() })
    emit('library-updated')
    status.value = ''
    savedMessage.value = '已提交入库：' + value
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : '入库失败'
  } finally {
    savingResult.value = false
  }
}

function safeUrl(url?: string): string | null {
  if (!url) return null
  try {
    const u = new URL(url)
    return u.protocol === 'https:' ? u.href : null
  } catch {
    return null
  }
}
</script>

<template>
  <div class="search-panel">
    <h2>搜索论文</h2>
    <form @submit.prevent="search">
      <input v-model="query" required maxlength="200" placeholder="关键词，如 diffusion policy" aria-label="搜索关键词" />
      <select v-model="source" aria-label="搜索来源">
        <option value="arxiv">arXiv</option>
        <option value="crossref">Crossref</option>
        <option value="both">两者</option>
      </select>
      <button class="primary" type="submit" :disabled="busy">搜索</button>
    </form>
    <button v-if="sessionId !== null" class="link" @click="emit('open-session', sessionId)">打开搜索会话 →</button>
    <StateFeedback
      :loading="busy"
      :error="error || null"
      :empty="!busy && !error && !results.length"
      :empty-text="status || '输入关键词开始搜索。'"
      :saving="savingResult"
      :saved="savedMessage"
      :save-error="saveError"
      @retry="search()"
    />
    <article v-for="(p, i) in results" :key="i" class="result-card">
      <h3>{{ p.title || '未命名论文' }}</h3>
      <p class="muted">{{ (p.authors ?? []).join(' · ') }}</p>
      <small class="muted">{{ p.source || '' }} · {{ p.published || p.year || '' }}</small>
      <p class="abstract">{{ p.abstract || '该来源未返回摘要。' }}</p>
      <div class="result-actions">
        <button v-if="p.arxiv_id || p.doi" @click="addToLibrary(p)">添加到论文库</button>
        <a v-if="safeUrl(p.url)" :href="safeUrl(p.url)!" target="_blank" rel="noopener noreferrer">查看来源 ↗</a>
      </div>
    </article>
  </div>
</template>

<style scoped>
.search-panel { padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-2); overflow-y: auto; height: 100%; }
h2 { margin: 0; font-size: 17px; }
form { display: flex; gap: var(--space-2); }
form input { flex: 1; }
.result-card { border: 1px solid var(--border); border-radius: var(--radius); padding: var(--space-3); background: var(--surface); display: flex; flex-direction: column; gap: var(--space-1); }
.result-card h3 { margin: 0; font-size: 14px; }
.result-card p { margin: 0; font-size: 12px; }
.abstract { display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
.result-actions { display: flex; gap: var(--space-2); align-items: center; }
.result-actions button { padding: var(--space-1) var(--space-2); font-size: 12px; }
.link { border: none; background: none; color: var(--accent); padding: 0; text-align: left; }
.form-error { color: var(--danger); }
</style>
