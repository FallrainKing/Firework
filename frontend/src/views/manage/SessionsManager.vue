<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { sessionsApi } from '@/api/sessions'
import { agentApi } from '@/api/agent'
import { uid32 } from '@/api/client'
import type { Category, Run, Session } from '@/api/types'
import TemplateManager from '@/components/manage/TemplateManager.vue'
import TaskDialog from '@/components/TaskDialog.vue'

const emit = defineEmits<{ 'open-paper': [paperId: number, sessionId: number]; 'open-import': [] }>()

const sessions = ref<Session[]>([])
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
const busy = ref(false)
const error = ref('')
const templatesOpen = ref(false)
const taskOpen = ref(false)
const renameValue = ref('')
const renaming = ref(false)

const STATES: Record<string, string> = { draft: '待开始', queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const polling = new Set<string>()

async function loadSessions() {
  const params: Record<string, unknown> = { q: q.value, archived: showArchived.value }
  if (kindFilter.value) params.kind = kindFilter.value
  if (categoryFilter.value !== '') params.category_id = Number(categoryFilter.value)
  sessions.value = (await sessionsApi.list(params as never)).sessions
}

onMounted(async () => {
  const [t, c] = await Promise.all([sessionsApi.templates(), sessionsApi.categories()])
  kinds.value = t.kinds
  categories.value = c.categories
  await loadSessions()
})

async function openSession(id: number) {
  error.value = ''
  const data = await sessionsApi.get(id)
  current.value = data.session
  papers.value = data.papers
  prompt.value = data.session.draft_prompt || ''
  const result = await sessionsApi.runs(id)
  if (current.value?.id !== id) return
  runs.value = result.runs
  older.value = result.next_before
  hasMore.value = result.has_more
  for (const r of result.runs) if (['queued', 'running'].includes(r.status)) void poll(r.id, id)
}

async function loadOlder() {
  if (!current.value || older.value === null) return
  const d = await sessionsApi.runs(current.value.id, older.value)
  runs.value = [...d.runs.slice().reverse(), ...runs.value]
  older.value = d.next_before
  hasMore.value = d.has_more
}

function upsertRun(r: Run) {
  const i = runs.value.findIndex(x => x.id === r.id)
  if (i >= 0) runs.value[i] = r
  else runs.value.push(r)
}

async function poll(runId: string, sessionId: number) {
  if (polling.has(runId)) return
  polling.add(runId)
  busy.value = true
  try {
    for (;;) {
      const r = await agentApi.getRun(runId)
      if (current.value?.id === sessionId) upsertRun(r)
      if (['succeeded', 'failed', 'cancelled'].includes(r.status)) {
        localStorage.removeItem('research-pending-session-' + sessionId)
        if (current.value?.id === sessionId) {
          busy.value = false
          current.value = (await sessionsApi.get(sessionId)).session
        }
        await loadSessions()
        break
      }
      await new Promise(r => setTimeout(r, 2000))
    }
  } catch {
    error.value = '任务状态暂时无法获取。重新打开会话会继续检查，不会自动重复调用。'
  } finally {
    polling.delete(runId)
    busy.value = false
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
  busy.value = true
  try {
    const run = await agentApi.createRun(body as never)
    if (current.value?.id === id) { upsertRun(run); prompt.value = '' }
    void poll(run.id, id)
    await loadSessions()
  } catch (e) {
    busy.value = false
    error.value = e instanceof Error ? e.message : '发送失败'
  }
}

async function patch(field: 'pinned' | 'archived') {
  if (!current.value) return
  current.value = await sessionsApi.update(current.value.id, { [field]: !current.value[field] })
  await loadSessions()
}

async function rename() {
  if (!current.value || !renameValue.value.trim()) return
  current.value = await sessionsApi.update(current.value.id, { title: renameValue.value.trim() })
  renaming.value = false
  await loadSessions()
}

async function setCategory(value: string) {
  if (!current.value) return
  current.value = await sessionsApi.update(current.value.id, { category_id: value ? Number(value) : null })
  await loadSessions()
}

function onCreated(session: Session, startingPrompt: string) {
  taskOpen.value = false
  prompt.value = startingPrompt
  void openSession(session.id)
}

function renderMd(text: string): string {
  if (window.mdRender) return window.mdRender(text)
  return text.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!))
}
</script>

<template>
  <div class="sessions-manager">
    <div class="sessions-list-pane">
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
      <button v-for="s in sessions" :key="s.id" class="session-item" :class="{ selected: current?.id === s.id }" @click="openSession(s.id)">
        <span>{{ s.pinned ? '置顶 · ' : '' }}{{ s.title }}</span>
        <small class="muted">{{ kinds[s.kind] || s.kind }} · {{ STATES[s.last_status] || s.last_status }}</small>
      </button>
      <p v-if="!sessions.length" class="muted">暂无匹配会话</p>
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
            <span v-if="!papers.length" class="muted">未关联论文</span>
          </div>
        </div>
        <p v-if="current.archived" class="muted archive-notice">已归档；取消归档后可继续。</p>
        <div class="messages">
          <button v-if="hasMore" class="load-older" @click="loadOlder">加载更早</button>
          <article v-for="r in runs" :key="r.id" class="message">
            <div class="message-head muted">{{ STATES[r.status] || r.status }} · {{ r.created_at }}</div>
            <div class="user-prompt">{{ r.prompt }}</div>
            <div v-if="r.answer" class="answer" v-html="renderMd(r.answer)"></div>
            <p v-if="r.error" class="tool-error">{{ r.error }}</p>
            <details v-for="(call, i) in r.tool_calls" :key="i" class="source">
              <summary>{{ call.ok ? '来源已读取' : '工具失败' }} · {{ call.tool }}{{ call.query ? ' · ' + call.query : '' }}</summary>
              <p v-if="call.error" class="tool-error">{{ call.error }}</p>
            </details>
            <p v-if="r.usage && 'input_tokens' in r.usage" class="usage muted">本轮输入 {{ r.usage.input_tokens }} / 输出 {{ r.usage.output_tokens }} tokens</p>
          </article>
          <p v-if="!runs.length" class="muted">会话已保存。发送起步要求后开始，之后可以随时返回继续。</p>
        </div>
        <form class="composer" @submit.prevent="submit">
          <textarea v-model="prompt" rows="2" maxlength="3000" placeholder="继续当前任务…" :disabled="busy || current.archived"></textarea>
          <button class="primary" type="submit" :disabled="busy || current.archived || !prompt.trim()">发送</button>
        </form>
      </template>
      <div v-else class="welcome muted">
        <h2>研究任务会话</h2>
        <p>创建或选择一个任务会话；会话与结果保存在这里，可随时返回继续。</p>
      </div>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
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
.sessions-manager { display: flex; height: 100%; min-height: 0; }
.sessions-list-pane { width: 300px; border-right: 1px solid var(--border); background: var(--surface); padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-2); overflow-y: auto; }
.list-toolbar { display: flex; flex-direction: column; gap: var(--space-1); }
.list-toolbar .checkbox { flex-direction: row; display: flex; gap: var(--space-1); align-items: center; font-size: 12px; }
.list-actions { display: flex; gap: var(--space-1); }
.session-item { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; text-align: left; border: 1px solid transparent; background: none; padding: var(--space-2); }
.session-item.selected { border-color: var(--accent); background: var(--accent-soft); }
.conversation-pane { flex: 1; display: flex; flex-direction: column; min-width: 0; padding: var(--space-3); gap: var(--space-2); }
.conversation-header { display: flex; flex-direction: column; gap: var(--space-2); }
.conversation-header h2 { margin: 0; font-size: 17px; }
.badges { display: flex; gap: var(--space-1); }
.badge { font-size: 11px; background: var(--accent-soft); color: var(--accent); padding: 1px var(--space-2); border-radius: 10px; }
.session-actions { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.session-actions button, .session-actions select { padding: var(--space-1) var(--space-2); font-size: 12px; }
.rename-row { display: flex; gap: var(--space-1); }
.associated-papers { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.paper-chip { font-size: 12px; padding: var(--space-1) var(--space-2); }
.messages { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: var(--space-2); }
.message { border: 1px solid var(--border); border-radius: var(--radius); padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-1); }
.message-head { font-size: 11px; }
.user-prompt { font-weight: 600; }
.tool-error { color: var(--danger); }
.usage { font-size: 11px; }
.composer { display: flex; gap: var(--space-2); align-items: flex-end; }
.composer textarea { flex: 1; }
.welcome { margin: auto; text-align: center; }
.dialog-overlay { position: fixed; inset: 0; background: rgb(0 0 0 / 0.25); display: flex; align-items: center; justify-content: center; z-index: 50; }
.form-error { color: var(--danger); }
.archive-notice { margin: 0; }
</style>
