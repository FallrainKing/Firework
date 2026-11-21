<script setup lang="ts">
import { renderMarkdown } from '@/shared/markdown'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { sessionsApi } from '@/api/sessions'
import { agentApi } from '@/api/agent'
import { uid32 } from '@/api/client'
import type { Category, Run, Session } from '@/api/types'
import TemplateManager from '@/components/manage/TemplateManager.vue'
import TaskDialog from '@/components/TaskDialog.vue'
import StateFeedback from '@/components/StateFeedback.vue'

const props = withDefaults(defineProps<{ initialSessionId?: number | null }>(), { initialSessionId: null })
const emit = defineEmits<{ 'open-paper': [paperId: number, sessionId: number]; 'open-import': [] }>()

const sessions = ref<Session[]>([])
const sessionsLoading = ref(false)
const sessionsError = ref<string | null>(null)
const runsLoading = ref(false)
const runsError = ref<string | null>(null)
const loadingOlder = ref(false)
const actionSaving = ref(false)
const saved = ref(false)
const saveError = ref<string | null>(null)
const categories = ref<Category[]>([])
const kinds = ref<Record<string, string>>({})
const q = ref('')
const kindFilter = ref('')
const categoryFilter = ref('')
const showArchived = ref(false)
const current = ref<Session | null>(null)
const papers = ref<Array<{ id: number; title: string }>>([])
const runs = ref<Run[]>([])
const older = ref<number | null>(null)
const hasMore = ref(false)
const prompt = ref('')
// 对照旧版 S.busy：按会话 id 记录忙碌，避免跨会话串扰。
const busySet = ref<Set<number>>(new Set())
const busy = computed(() => !!current.value && busySet.value.has(current.value.id))
const error = ref('')
const templatesOpen = ref(false)
const taskOpen = ref(false)
const renameValue = ref('')
const renaming = ref(false)
const statusFilter = ref('all')
const statusOptions = [
  { id: 'all', label: '全部' }, { id: 'active', label: '进行中' },
  { id: 'attention', label: '需检查' }, { id: 'succeeded', label: '已完成' },
]
function matchesStatus(s: Session, status: string) {
  if (status === 'active') return ['queued', 'running'].includes(s.last_status)
  if (status === 'attention') return ['failed', 'cancelled'].includes(s.last_status)
  return status === 'all' || s.last_status === status
}
function sessionPriority(s: Session) {
  if (['queued', 'running'].includes(s.last_status)) return 0
  if (['failed', 'cancelled'].includes(s.last_status)) return 1
  return s.pinned ? 2 : 3
}
const visibleSessions = computed(() => sessions.value.filter(s => matchesStatus(s, statusFilter.value)).slice().sort((a, b) =>
  sessionPriority(a) - sessionPriority(b) || b.updated_at.localeCompare(a.updated_at)))

const STATES: Record<string, string> = { draft: '待开始', queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const polling = new Set<string>()
let stopped = false
let openEpoch = 0

function setBusy(id: number, on: boolean) {
  const next = new Set(busySet.value)
  if (on) next.add(id)
  else next.delete(id)
  busySet.value = next
}

onUnmounted(() => { stopped = true })
watch(() => props.initialSessionId, sid => { if (sid) void openSession(sid) })

async function loadSessions() {
  if (sessionsLoading.value) return
  sessionsLoading.value = true
  sessionsError.value = null
  const params: Record<string, unknown> = { q: q.value, archived: showArchived.value }
  if (kindFilter.value) params.kind = kindFilter.value
  if (categoryFilter.value !== '') params.category_id = Number(categoryFilter.value)
  try {
    sessions.value = (await sessionsApi.list(params as never)).sessions
  } catch (e) {
    sessionsError.value = e instanceof Error ? e.message : '会话列表载入失败'
  } finally {
    sessionsLoading.value = false
  }
}

onMounted(async () => {
  try {
    const [t, c] = await Promise.all([sessionsApi.templates(), sessionsApi.categories()])
    kinds.value = t.kinds
    categories.value = c.categories
  } catch (e) {
    sessionsError.value = e instanceof Error ? e.message : '会话筛选信息载入失败'
  }
  await loadSessions()
  if (props.initialSessionId) await openSession(props.initialSessionId)
})

async function openSession(id: number) {
  const epoch = ++openEpoch
  error.value = ''
  runsLoading.value = true
  runsError.value = null
  try {
    const data = await sessionsApi.get(id)
    if (epoch !== openEpoch) return
    current.value = data.session
    runs.value = []
    hasMore.value = false
    older.value = null
    papers.value = data.papers
    const pending = (() => { try { return JSON.parse(localStorage.getItem('research-pending-session-' + id) || 'null') } catch { return null } })()
    prompt.value = pending?.prompt || data.session.draft_prompt || ''
    const result = await sessionsApi.runs(id)
    if (epoch !== openEpoch) return
    runs.value = result.runs
    older.value = result.next_before
    hasMore.value = result.has_more
    for (const r of result.runs) if (['queued', 'running'].includes(r.status)) void poll(r.id, id)
  } catch (e) {
    if (epoch === openEpoch) runsError.value = e instanceof Error ? e.message : '会话详情载入失败'
  } finally {
    if (epoch === openEpoch) runsLoading.value = false
  }
}

async function loadOlder() {
  if (!current.value || older.value === null || loadingOlder.value) return
  loadingOlder.value = true
  runsError.value = null
  try {
    const d = await sessionsApi.runs(current.value.id, older.value)
    runs.value = [...d.runs.slice().reverse(), ...runs.value]
    older.value = d.next_before
    hasMore.value = d.has_more
  } catch (e) {
    runsError.value = e instanceof Error ? e.message : '历史载入失败'
  } finally {
    loadingOlder.value = false
  }
}

function upsertRun(r: Run) {
  const i = runs.value.findIndex(x => x.id === r.id)
  if (i >= 0) runs.value[i] = r
  else runs.value.push(r)
}

async function poll(runId: string, sessionId: number) {
  if (polling.has(runId)) return
  polling.add(runId)
  setBusy(sessionId, true)
  try {
    while (!stopped) {
      const r = await agentApi.getRun(runId)
      if (stopped) break
      if (current.value?.id === sessionId) upsertRun(r)
      if (['succeeded', 'failed', 'cancelled'].includes(r.status)) {
        localStorage.removeItem('research-pending-session-' + sessionId)
        setBusy(sessionId, false)
        if (current.value?.id === sessionId) current.value = (await sessionsApi.get(sessionId)).session
        await loadSessions()
        break
      }
      await new Promise(r => setTimeout(r, 2000))
    }
  } catch {
    if (!stopped) error.value = '任务状态暂时无法获取。重新打开会话会继续检查，不会自动重复调用。'
  } finally {
    polling.delete(runId)
    setBusy(sessionId, false)
  }
}

async function submit() {
  if (!current.value) return
  const id = current.value.id
  const text = prompt.value.trim()
  if (!text) { error.value = '请输入任务要求'; return }
  if (busy.value) { error.value = '当前会话已有任务在执行'; return }
  const storage = 'research-pending-session-' + id
  let body: Record<string, unknown>
  try {
    const cached = JSON.parse(localStorage.getItem(storage) || 'null')
    body = cached?.prompt === text ? cached : { conversation_id: id, prompt: text, request_key: uid32() }
  } catch {
    body = { conversation_id: id, prompt: text, request_key: uid32() }
  }
  localStorage.setItem(storage, JSON.stringify(body))
  setBusy(id, true)
  try {
    const run = await agentApi.createRun(body as never)
    if (current.value?.id === id) { upsertRun(run); prompt.value = '' }
    void poll(run.id, id)
    await loadSessions()
  } catch (e) {
    setBusy(id, false)
    error.value = e instanceof Error ? e.message : '发送失败'
  }
}

async function patch(field: 'pinned' | 'archived') {
  if (!current.value) return
  await updateCurrent({ [field]: !current.value[field] })
}

async function rename() {
  if (!current.value || !renameValue.value.trim()) return
  await updateCurrent({ title: renameValue.value.trim() })
  renaming.value = false
}

async function setCategory(value: string) {
  if (!current.value) return
  await updateCurrent({ category_id: value ? Number(value) : null })
}

async function updateCurrent(patch: Record<string, unknown>) {
  if (!current.value || actionSaving.value) return
  actionSaving.value = true
  saveError.value = null
  saved.value = false
  try {
    current.value = await sessionsApi.update(current.value.id, patch as never)
    saved.value = true
    await loadSessions()
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : '会话保存失败'
  } finally {
    actionSaving.value = false
  }
}

function onCreated(session: Session, startingPrompt: string) {
  taskOpen.value = false
  prompt.value = startingPrompt
  void openSession(session.id)
}

function renderMd(text: string): string { return renderMarkdown(text) }
</script>

<template>
  <div class="sessions-manager">
    <div class="sessions-list-pane">
      <header class="session-list-heading"><strong>研究会话</strong><button type="button" :disabled="sessionsLoading" @click="loadSessions">刷新</button></header>
      <p class="session-list-hint muted">进行中的任务和需检查的结果优先展示</p>
      <div class="list-toolbar">
        <input v-model="q" type="search" placeholder="搜索会话…" aria-label="搜索会话" @input="loadSessions" />
        <select v-model="kindFilter" aria-label="任务类型" @change="loadSessions">
          <option value="">全部任务</option>
          <option v-for="(name, id) in kinds" :key="id" :value="id">{{ name }}</option>
        </select>
        <select v-model="categoryFilter" aria-label="会话分类" @change="loadSessions">
          <option value="">全部分类</option>
          <option value="0">未分类</option>
          <option v-for="c in categories" :key="c.id" :value="String(c.id)">{{ c.name }}</option>
        </select>
        <label class="checkbox"><input v-model="showArchived" type="checkbox" @change="loadSessions" />含归档</label>
      </div>
      <div class="list-actions">
        <button class="primary" @click="taskOpen = true">＋ 新建任务</button>
        <button @click="templatesOpen = true">模板管理</button>
      </div>
      <nav class="status-filters" aria-label="会话状态筛选">
        <button v-for="option in statusOptions" :key="option.id" type="button" :aria-pressed="statusFilter === option.id" @click="statusFilter = option.id">{{ option.label }} <span>{{ sessions.filter(s => matchesStatus(s, option.id)).length }}</span></button>
      </nav>
      <small class="muted">数量基于当前搜索与分类结果</small>
      <button v-for="s in visibleSessions" :key="s.id" class="session-item" :class="{ selected: current?.id === s.id }" :aria-current="current?.id === s.id ? 'true' : undefined" @click="openSession(s.id)">
        <span class="session-item-title"><i class="status-dot" :class="s.last_status" aria-hidden="true"></i>{{ s.pinned ? '置顶 · ' : '' }}{{ s.title }}</span>
        <small class="muted">{{ kinds[s.kind] || s.kind }} · {{ STATES[s.last_status] || s.last_status }} · {{ s.run_count }} 轮</small>
        <small v-if="s.preview" class="session-preview">{{ s.preview }}</small>
        <small v-if="s.draft_prompt" class="draft-indicator">有未发送草稿</small>
      </button>
      <StateFeedback
        :loading="sessionsLoading && !sessions.length"
        :error="sessionsError"
        :empty="!sessionsLoading && !sessionsError && !visibleSessions.length"
        empty-text="暂无匹配会话"
        :saving="actionSaving"
        :saved="saved"
        :save-error="saveError"
        @retry="loadSessions"
      />
    </div>

    <div class="conversation-pane">
      <template v-if="current">
        <div class="conversation-header">
          <h2>{{ current.title }}</h2>
          <div class="badges">
            <span class="badge">{{ kinds[current.kind] || current.kind }}</span>
            <span class="badge">{{ current.native_ready ? '原生会话可延续' : '首次执行后建立原生上下文' }}</span>
          </div>
          <div class="session-actions">
            <button class="archive-session" @click="patch('archived')">{{ current.archived ? '取消归档' : '归档' }}</button>
            <button @click="patch('pinned')">{{ current.pinned ? '取消置顶' : '置顶' }}</button>
            <button @click="renaming = true; renameValue = current.title">重命名</button>
            <select :value="current.category_id ?? ''" aria-label="会话分类" @change="setCategory(($event.target as HTMLSelectElement).value)">
              <option value="">未分类</option>
              <option v-for="c in categories" :key="c.id" :value="String(c.id)">{{ c.name }}</option>
            </select>
          </div>
          <div v-if="renaming" class="rename-row">
            <input v-model="renameValue" maxlength="160" @keydown.enter="rename" />
            <button @click="rename">保存</button>
          </div>
          <div class="associated-papers">
            <button v-for="p in papers" :key="p.id" class="paper-chip" @click="emit('open-paper', p.id, current!.id)">{{ p.title }} ↗</button>
            <StateFeedback v-if="!papers.length" empty empty-text="未关联论文。" />
          </div>
        </div>
        <p v-if="current.archived" class="muted archive-notice">已归档；取消归档后可继续。</p>
        <div class="messages">
          <StateFeedback
            :loading="runsLoading && !runs.length"
            :error="runsError"
            :empty="!runsLoading && !runsError && !runs.length"
            empty-text="会话已保存。发送起步要求后开始，之后可以随时返回继续。"
          />
          <button v-if="hasMore" class="load-older" :disabled="loadingOlder" @click="loadOlder">{{ loadingOlder ? '正在载入历史…' : '加载更早' }}</button>
          <article v-for="r in runs" :key="r.id" class="message">
            <div class="message-head muted">{{ STATES[r.status] || r.status }} · {{ r.created_at }}</div>
            <div class="user-prompt">{{ r.prompt }}</div>
            <div v-if="r.answer" class="answer markdown-content" v-html="renderMd(r.answer)"></div>
            <p v-if="r.error" class="tool-error">{{ r.error }}</p>
            <details v-if="r.tool_calls.length" class="execution-group"><summary>执行过程 · {{ r.tool_calls.length }} 次工具调用</summary>
            <details v-for="(call, i) in r.tool_calls" :key="i" class="source">
              <summary>{{ call.ok ? '来源已读取' : '工具失败' }} · {{ call.tool }}{{ call.query ? ' · ' + call.query : '' }}</summary>
              <p v-if="call.error" class="tool-error">{{ call.error }}</p>
            </details>
            </details>
            <p v-if="r.usage && 'input_tokens' in r.usage" class="usage muted">本轮输入 {{ r.usage.input_tokens }} / 输出 {{ r.usage.output_tokens }} tokens</p>
          </article>
        </div>
        <form class="composer" @submit.prevent="submit">
          <textarea v-model="prompt" rows="2" maxlength="3000" placeholder="继续当前任务…" :disabled="busy || current.archived"></textarea>
          <button class="primary" type="submit" :disabled="busy || current.archived || !prompt.trim()">发送</button>
        </form>
      </template>
      <div v-else class="welcome muted">
        <StateFeedback :loading="runsLoading" :error="runsError" empty-text="创建或选择一个任务会话。" />
        <h2>研究任务会话</h2>
        <p>创建或选择一个任务会话；会话与结果保存在这里，可随时返回继续。</p>
      </div>
      <StateFeedback v-if="error" :error="error" @retry="submit" />
    </div>

    <div v-if="templatesOpen" class="dialog-overlay" @click.self="templatesOpen = false">
      <TemplateManager @close="templatesOpen = false" />
    </div>
    <div v-if="taskOpen" class="dialog-overlay" @click.self="taskOpen = false">
      <TaskDialog mode="read" @created="onCreated" @close="taskOpen = false" @open-import="emit('open-import')" />
    </div>
  </div>
</template>

<style scoped>
.session-list-heading { display:flex; align-items:center; justify-content:space-between; }
.session-list-heading button { font-size:12px; }
.session-list-hint { font-size:12px; margin:0; }
.status-filters { display:grid; grid-template-columns:1fr 1fr; gap:4px; }
.status-filters button { font-size:12px; padding:6px; display:flex; justify-content:space-between; }
.status-filters [aria-pressed="true"] { color:var(--accent); border-color:var(--accent); background:var(--accent-soft); }
.session-item-title { display:flex; align-items:baseline; gap:6px; }
.status-dot { display:inline-block; width:7px; height:7px; flex-shrink:0; border-radius:50%; background:var(--text-muted); }
.status-dot.running,.status-dot.queued,.status-dot.succeeded { background:var(--accent); }
.status-dot.failed,.status-dot.cancelled { background:var(--danger); }
.session-preview { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; line-height:1.5; color:var(--text-muted); }
.draft-indicator { font-size:12px; color:var(--accent); }
.execution-group { font-size:12px; color:var(--text-muted); padding-top:8px; border-top:1px dashed var(--border); }
.message { flex-shrink:0; }
.sessions-manager { display: flex; height: 100%; min-height: 0; }
.sessions-list-pane { flex:0 0 280px; min-width:0; width:280px; border-right: 1px solid var(--border); background: var(--surface); padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-2); overflow-y: auto; }
.list-toolbar { display: flex; flex-direction: column; gap: var(--space-1); }
.list-toolbar .checkbox { flex-direction: row; display: flex; gap: var(--space-1); align-items: center; font-size: 12px; }
.list-actions { display: flex; gap: var(--space-1); }
.session-item { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; text-align: left; border: 1px solid transparent; background: none; padding: var(--space-2); }
.session-item.selected { border-color:transparent; background:var(--accent-soft); }
.conversation-pane { flex: 1; display: flex; flex-direction: column; min-width: 0; padding: var(--space-3); gap: var(--space-2); }
.conversation-header { display: flex; flex-direction: column; gap: var(--space-2); }
.conversation-header h2 { margin: 0; font-size: 17px; }
.badges { display: flex; gap: var(--space-1); }
.badge { font-size: 12px; background: var(--accent-soft); color: var(--accent); padding: 1px var(--space-2); border-radius: 10px; }
.session-actions { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.session-actions button, .session-actions select { padding: var(--space-1) var(--space-2); font-size: 12px; }
.rename-row { display: flex; gap: var(--space-1); }
.associated-papers { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.paper-chip { font-size: 12px; padding: var(--space-1) var(--space-2); }
.messages > :first-child { margin: 0; }
.messages { flex: 1; min-height:0; overflow-wrap:anywhere; overflow-y: auto; display: flex; flex-direction: column; gap: var(--space-2); }
.message { border:0; border-bottom:1px solid var(--border); padding:16px 4px 24px; display:flex; flex-direction:column; gap:var(--space-2); }
.message-head { font-size: 12px; }
.user-prompt { font-weight: 600; }
.tool-error { color: var(--danger); }
.usage { font-size: 12px; }
.composer { display: flex; gap: var(--space-2); align-items: flex-end; }
.composer textarea { flex: 1; min-width:0; }
.welcome { margin: auto; text-align: center; }
.dialog-overlay { position: fixed; inset: 0; background: rgb(0 0 0 / 0.25); display: flex; align-items: center; justify-content: center; z-index: 50; }
.form-error { color: var(--danger); }
.archive-notice { margin: 0; }
.session-item { min-width:0; overflow-wrap:anywhere; }
.conversation-header { overflow-wrap:anywhere; }
@media(max-width:760px) {
  .sessions-manager { flex-direction:column; overflow-y:auto; }
  .sessions-list-pane { flex:0 0 auto; width:100%; max-height:230px; border-right:0; border-bottom:1px solid var(--border); }
  .conversation-pane { flex:1 0 320px; min-height:320px; }
}
</style>
