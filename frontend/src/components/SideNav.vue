<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ActivityPanel from './ActivityPanel.vue'
import StateFeedback from './StateFeedback.vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useLibraryStore } from '@/stores/library'
import { sessionsApi } from '@/api/sessions'
import type { Session } from '@/api/types'

const wb = useWorkbenchStore()
const lib = useLibraryStore()
const emit = defineEmits<{ 'new-task': []; 'open-import': []; 'new-domain': []; 'open-paper': [paperId: number, sessionId?: number] }>()
const expanded = ref<number | null>(null)
const navMode = ref<'papers' | 'sessions'>('papers')
const paperQuery = ref('')
const sessionQuery = ref('')
const sessionFilter = ref<'recent' | 'pinned' | 'running' | 'archived'>('recent')
const sessions = ref<Session[]>([])
const sessionsLoading = ref(false)
const sessionsError = ref('')
const busySessionId = ref<number | null>(null)
const paperNavError = ref<string | null>(null)
const collectionLoadingId = ref<number | null>(null)
const collectionError = ref<string | null>(null)
const sessionSaved = ref(false)
const sessionSaveError = ref<string | null>(null)

const recentPapers = computed(() => lib.recent
  .filter((r, i, all) => all.findIndex(x => x.paper_id === r.paper_id) === i)
  .filter(r => paperTitle(r.paper_id).toLowerCase().includes(paperQuery.value.trim().toLowerCase()))
  .slice(0, 8))

const filteredCollections = computed(() => lib.collections.filter(c =>
  c.name.toLowerCase().includes(paperQuery.value.trim().toLowerCase())))

const filteredSessions = computed(() => {
  const q = sessionQuery.value.trim().toLowerCase()
  return sessions.value.filter(session => {
    if (sessionFilter.value === 'archived') return session.archived
    if (session.archived) return false
    if (sessionFilter.value === 'pinned') return session.pinned
    if (sessionFilter.value === 'running') return session.last_status === 'queued' || session.last_status === 'running'
    return true
  }).filter(session => {
    if (!q) return true
    return session.title.toLowerCase().includes(q) || session.preview.toLowerCase().includes(q)
  })
})

const sessionGroups = computed(() => {
  const groups = new Map<string, { paperId: number | null; title: string; sessions: Session[] }>()
  for (const session of filteredSessions.value) {
    const paperId = session.paper_ids[0] ?? null
    const title = paperId ? paperTitle(paperId) : '无论文任务'
    const key = paperId === null ? 'none' : String(paperId)
    const group = groups.get(key) ?? { paperId, title, sessions: [] }
    group.sessions.push(session)
    groups.set(key, group)
  }
  return [...groups.values()]
})

function paperTitle(id: number): string {
  return lib.papersById[id]?.title ?? `论文 ${id}`
}

async function loadCollection(id: number) {
  collectionLoadingId.value = id
  collectionError.value = null
  try {
    await lib.loadCollection(id)
  } catch (e) {
    collectionError.value = e instanceof Error ? e.message : '领域论文载入失败'
  } finally {
    collectionLoadingId.value = null
  }
}

async function toggleCollection(id: number) {
  if (expanded.value === id) {
    expanded.value = null
    return
  }
  expanded.value = id
  if (!lib.papersByCollection[id]) await loadCollection(id)
}

function openRecent(paperId: number, sessionId: number) {
  emit('open-paper', paperId, sessionId)
}

function openPaper(paperId: number, sessionId?: number) {
  emit('open-paper', paperId, sessionId)
}

async function refreshNavigation() {
  paperNavError.value = null
  sessionsError.value = ''
  try {
    await Promise.all([lib.refresh(), refreshSessions()])
  } catch (e) {
    paperNavError.value = e instanceof Error ? e.message : '论文导航载入失败'
  }
}

async function refreshSessions() {
  sessionsLoading.value = true
  sessionsError.value = ''
  try {
    const data = await sessionsApi.list({
      q: sessionQuery.value.trim() || undefined,
      archived: sessionFilter.value === 'archived',
      limit: 100,
    })
    sessions.value = data.sessions
  } catch (e) {
    sessionsError.value = e instanceof Error ? e.message : '任务导航载入失败'
  } finally {
    sessionsLoading.value = false
  }
}

function setNavMode(mode: 'papers' | 'sessions') {
  navMode.value = mode
  if (mode === 'sessions') void refreshSessions()
}

function statusLabel(session: Session): string {
  if (session.archived) return '已归档'
  if (session.last_status === 'running') return '运行中'
  if (session.last_status === 'queued') return '排队中'
  if (session.last_status === 'failed') return '失败'
  if (session.last_status === 'succeeded') return '已完成'
  return '草稿'
}

async function renameSession(session: Session) {
  const title = window.prompt('新的任务名称', session.title)?.trim()
  if (!title) return
  await updateSession(session, { title })
}

async function togglePinned(session: Session) {
  await updateSession(session, { pinned: !session.pinned })
}

async function toggleArchived(session: Session) {
  await updateSession(session, { archived: !session.archived })
}

async function updateSession(session: Session, patch: { title?: string; pinned?: boolean; archived?: boolean }) {
  busySessionId.value = session.id
  sessionsError.value = ''
  sessionSaveError.value = null
  sessionSaved.value = false
  try {
    const updated = await sessionsApi.update(session.id, patch)
    sessions.value = sessions.value.map(item => item.id === session.id ? updated : item)
    sessionSaved.value = true
  } catch (e) {
    sessionSaveError.value = e instanceof Error ? e.message : '任务更新失败'
  } finally {
    busySessionId.value = null
  }
}

onMounted(() => {
  void refreshSessions()
})
</script>

<template>
  <aside class="work-sidebar">
    <button class="primary" @click="emit('new-task')">＋ 新建论文阅读</button>
    <button @click="emit('open-import')">搜索 / 导入论文</button>

    <div class="nav-modes" role="tablist" aria-label="阅读导航">
      <button :class="{ active: navMode === 'papers' }" role="tab" :aria-selected="navMode === 'papers'" @click="setNavMode('papers')">论文</button>
      <button :class="{ active: navMode === 'sessions' }" role="tab" :aria-selected="navMode === 'sessions'" @click="setNavMode('sessions')">会话</button>
    </div>

    <template v-if="navMode === 'papers'">
      <div class="side-title">
        <h2>最近阅读</h2>
        <button aria-label="刷新论文导航" @click="refreshNavigation()">↻</button>
      </div>
      <input v-model="paperQuery" class="nav-search" type="search" placeholder="搜索论文" aria-label="搜索论文">
      <div class="recent-reading">
        <button v-for="r in recentPapers" :key="r.paper_id + '-' + r.conversation_id" class="side-item" :class="{ selected: wb.activePaperId === r.paper_id && wb.view === 'read' }" @click="openRecent(r.paper_id, r.conversation_id)">
          <span class="paper-icon" aria-hidden="true">▤</span><span class="item-title">{{ paperTitle(r.paper_id) }}</span>
        </button>
        <StateFeedback
          :loading="lib.loading && !recentPapers.length"
          :error="paperNavError"
          :empty="!lib.loading && !paperNavError && !recentPapers.length"
          empty-text="暂无匹配论文。"
          @retry="refreshNavigation()"
        />
      </div>

      <div class="side-title">
        <h2>论文领域</h2>
        <button aria-label="新增论文领域" @click="emit('new-domain')">＋</button>
      </div>
      <div class="domain-papers">
        <div v-for="c in filteredCollections" :key="c.id" class="domain">
          <button class="side-item domain-head" @click="toggleCollection(c.id)">
            <span class="folder-icon" aria-hidden="true">{{ expanded === c.id ? '▾' : '▸' }}</span><span class="item-title">{{ c.name }}</span>
            <span class="muted">{{ c.count ?? 0 }}</span>
          </button>
          <div v-if="expanded === c.id" class="domain-list">
            <button v-for="p in lib.papersByCollection[c.id] ?? []" :key="p.id" class="side-item" @click="openPaper(p.id)">
              <span class="item-title">{{ p.title }}</span>
              <span v-if="!p.has_pdf" class="muted no-pdf">缺全文</span>
            </button>
            <StateFeedback
              :loading="collectionLoadingId === c.id && !(lib.papersByCollection[c.id] ?? []).length"
              :error="collectionError"
              :empty="collectionLoadingId !== c.id && !collectionError && !(lib.papersByCollection[c.id] ?? []).length"
              empty-text="该领域暂无论文。"
              @retry="loadCollection(c.id)"
            />
          </div>
        </div>
        <StateFeedback
          :loading="lib.loading && !filteredCollections.length"
          :error="paperNavError"
          :empty="!lib.loading && !paperNavError && !filteredCollections.length"
          empty-text="暂无匹配领域。"
          @retry="refreshNavigation()"
        />
      </div>
    </template>

    <template v-else>
      <div class="side-title">
        <h2>任务会话</h2>
        <button aria-label="刷新任务导航" @click="refreshSessions()">↻</button>
      </div>
      <input v-model="sessionQuery" class="nav-search" type="search" placeholder="搜索任务或运行内容" aria-label="搜索任务或运行内容" @keyup.enter="refreshSessions()">
      <div class="session-filters" role="group" aria-label="会话筛选">
        <button v-for="filter in ['recent', 'pinned', 'running', 'archived'] as const" :key="filter" :class="{ active: sessionFilter === filter }" @click="sessionFilter = filter; refreshSessions()">
          {{ filter === 'recent' ? '最近' : filter === 'pinned' ? '固定' : filter === 'running' ? '运行中' : '归档' }}
        </button>
      </div>
      <StateFeedback
        :loading="sessionsLoading && !sessions.length"
        :error="sessionsError || null"
        :empty="!sessionsLoading && !sessionsError && !sessionSaveError && !filteredSessions.length"
        empty-text="暂无匹配任务。"
        :saving="busySessionId !== null"
        :saved="sessionSaved"
        :save-error="sessionSaveError"
        @retry="refreshSessions()"
      />
      <div class="session-nav">
        <section v-for="group in sessionGroups" :key="group.paperId ?? 'none'" class="session-paper">
          <button class="side-item paper-head" type="button" :disabled="group.paperId === null" @click="group.paperId !== null && openPaper(group.paperId)">
            <span class="paper-icon" aria-hidden="true">▤</span>
            <span class="item-title">{{ group.title }}</span>
            <span class="muted">{{ group.sessions.length }}</span>
          </button>
          <div class="session-list">
            <article v-for="session in group.sessions" :key="session.id" class="session-item">
              <button class="session-open" type="button" :disabled="group.paperId === null" @click="group.paperId !== null && openPaper(group.paperId, session.id)">
                <strong>{{ session.title }}</strong>
                <span class="muted">{{ statusLabel(session) }} · {{ session.run_count }} 次运行</span>
              </button>
              <div class="session-actions">
                <button type="button" :disabled="busySessionId === session.id" @click="renameSession(session)">改名</button>
                <button type="button" :disabled="busySessionId === session.id" @click="togglePinned(session)">{{ session.pinned ? '取消固定' : '固定' }}</button>
                <button type="button" :disabled="busySessionId === session.id" @click="toggleArchived(session)">{{ session.archived ? '恢复' : '归档' }}</button>
              </div>
            </article>
          </div>
        </section>
      </div>
    </template>

    <button class="side-schedule" @click="wb.setView('schedules')">◷ 定时任务</button>
    <ActivityPanel />
    <p class="muted sidebar-tip">阅读位置与会话自动保存<br />切换标签不会调用智能体</p>
  </aside>
</template>

<style scoped>
.work-sidebar { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border-right: 1px solid var(--border); background: var(--surface); width: 248px; flex-shrink: 0; overflow-y: auto; padding: 20px 14px; }
.side-title { display: flex; align-items: center; justify-content: space-between; margin-top: var(--space-3); }
.side-title h2 { font-size: 12px; color: var(--text-muted); margin: 0; font-weight: 600; }
.side-title button { border: none; background: none; padding: 0 var(--space-1); color: var(--text-muted); }
.side-item { display: flex; justify-content: space-between; gap: var(--space-2); width: 100%; border: none; background: none; text-align: left; padding: var(--space-1) var(--space-2); border-radius: var(--radius); }
.side-item:hover { background: var(--accent-soft); color: var(--accent); }
.side-item.selected { background: var(--accent-soft); color: var(--accent); }
.paper-icon,.folder-icon { color:var(--text-muted); flex-shrink:0; }
.item-title { flex:1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.domain-list { padding-left: var(--space-3); }
.no-pdf { font-size: 11px; flex-shrink: 0; }
.side-schedule { margin-top: var(--space-3); }
.sidebar-tip { font-size: 11px; margin-top: auto; padding-top: var(--space-3); }
.side-item { padding:9px 8px; font-size:12px; }
.side-title { margin-top:20px; margin-bottom:4px; padding:0 8px; }
.work-sidebar > .primary { text-align:left; padding:10px 12px; box-shadow:0 3px 8px rgb(36 116 95 / .1); }
.sidebar-tip { line-height:1.9; border-top:1px solid var(--border); }
.nav-modes { display:grid; grid-template-columns:1fr 1fr; gap:2px; margin-top:var(--space-3); padding:2px; border:1px solid var(--border); border-radius:var(--radius); background:var(--bg); }
.nav-modes button { border:0; background:none; padding:6px 4px; border-radius:6px; color:var(--text-muted); font-size:12px; }
.nav-modes button.active { background:var(--surface); color:var(--accent); font-weight:650; }
.nav-search { width:100%; }
.session-filters { display:grid; grid-template-columns:repeat(4,1fr); gap:3px; }
.session-filters button { padding:5px 3px; font-size:11px; border-color:transparent; background:var(--bg); color:var(--text-muted); }
.session-filters button.active { color:var(--accent); border-color:var(--accent); background:var(--accent-soft); }
.session-nav { display:flex; flex-direction:column; gap:var(--space-2); }
.session-paper { display:flex; flex-direction:column; gap:2px; }
.paper-head { align-items:center; }
.session-list { display:flex; flex-direction:column; gap:4px; padding-left:var(--space-3); }
.session-item { display:grid; gap:4px; padding:6px; border:1px solid var(--border); border-radius:var(--radius); background:var(--bg); }
.session-open { display:flex; flex-direction:column; gap:2px; border:0; background:none; text-align:left; color:var(--text); }
.session-open span { font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.session-actions { display:flex; gap:4px; }
.session-actions button { flex:1; padding:3px; font-size:10px; border-color:transparent; background:var(--surface); }
@media(max-width:760px) { .work-sidebar { position:absolute; inset:0 auto 0 0; z-index:35; box-shadow:8px 0 24px rgb(0 0 0 / .12%); } }
</style>
