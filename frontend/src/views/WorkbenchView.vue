<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { parseDeepLink } from '@/shared/deeplink'
import TopNav from '@/components/TopNav.vue'
import SideNav from '@/components/SideNav.vue'
import ActivityPanel from '@/components/ActivityPanel.vue'
import PaperTabs from '@/components/PaperTabs.vue'
import ImportOverlay from '@/components/ImportOverlay.vue'
import TaskDialog from '@/components/TaskDialog.vue'
import OpenPaperDialog from '@/components/OpenPaperDialog.vue'
import StateFeedback from '@/components/StateFeedback.vue'
import { papersApi } from '@/api/papers'
import WelcomeView from './WelcomeView.vue'
import ReadingView from './ReadingView.vue'
import LibraryView from './LibraryView.vue'
import CompareView from './CompareView.vue'
import SchedulesView from './SchedulesView.vue'
import FrontierView from './FrontierView.vue'
import SkillsView from './SkillsView.vue'
import SettingsView from './SettingsView.vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useLibraryStore } from '@/stores/library'
import { useActivityStore } from '@/stores/activity'
import type { Paper, Session, Template } from '@/api/types'

const wb = useWorkbenchStore()
const lib = useLibraryStore()
const sideHidden = ref(window.innerWidth <= 760)
const pickerOpen = ref(false)
const readablePaperId = ref<number | null>(null)
const missingPaper = ref<Paper | null>(null)
const openingPaper = ref(false)
const openingError = ref('')
let openEpoch = 0

// All entry points (sidebar, restored tabs, comparison and deep links) pass this
// boundary before mounting a reader or creating its conversation.
async function checkFullText(paperId: number | null) {
  const epoch = ++openEpoch
  readablePaperId.value = null
  missingPaper.value = null
  openingError.value = ''
  openingPaper.value = paperId !== null
  if (paperId === null) return
  try {
    const paper = await papersApi.get(paperId)
    if (epoch !== openEpoch) return
    lib.papersById[paperId] = paper
    if (paper.has_pdf) readablePaperId.value = paperId
    else missingPaper.value = paper
  } catch (e) {
    if (epoch === openEpoch) openingError.value = e instanceof Error ? e.message : '论文载入失败'
  } finally { if (epoch === openEpoch) openingPaper.value = false }
}
watch(() => wb.activePaperId, id => {
  sideHidden.value = id !== null || window.innerWidth <= 760
  void checkFullText(id)
}, { immediate: true })

function openPaper(paperId: number, sessionId?: number) {
  try {
    pickerOpen.value = false
    wb.openPaper(paperId, sessionId)
    wb.setView('read')
  } catch (e) { showToast(e instanceof Error ? e.message : '打开失败') }
}
async function openImportedPaper(paperId: number) {
  importOpen.value = false
  openPaper(paperId)
  // Replacing the PDF of the active paper does not change its tab id.
  await checkFullText(paperId)
  await lib.refresh()
}
const importOpen = ref(false)

const taskRequest = ref<null | { mode: 'read' | 'compare' | 'chat' | 'review'; question?: string; template?: Template }>(null)
const domainOpen = ref(false)
const domainName = ref('')
const domainError = ref('')
const domainSaving = ref(false)
const domainSaved = ref(false)
const toast = ref('')
const importTarget = ref<number | null>(null)
const librarySession = ref<number | null>(null)
const activity = useActivityStore()
let toastTimer: ReturnType<typeof setTimeout> | null = null

function showToast(message: string) {
  toast.value = message
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 5000)
}

watch(() => activity.lastTerminal, t => {
  if (!t) return
  const label = t.status === 'succeeded' ? '任务完成' : t.status === 'cancelled' ? '任务已取消' : '任务失败'
  showToast(label + (t.error ? '：' + t.error : ''))
})

function openImport(paperId?: number) {
  importTarget.value = paperId ?? null
  importOpen.value = true
}

const route = useRoute()

function openSessionInLibrary(sessionId: number) {
  librarySession.value = sessionId
  wb.setView('library')
}

onMounted(async () => {
  try {
    await Promise.all([wb.load(), lib.refresh()])
    const deep = parseDeepLink(route)
    if (deep) {
      openPaper(deep.paperId, deep.sessionId ?? undefined)
    }
  } catch (e) {
    showToast(e instanceof Error ? e.message : '工作台加载失败')
  }
})

function goHome() {
  wb.activePaperId = null
  wb.schedulePersist()
}

function activeSessionId(): number | null {
  return wb.tabs.find(t => t.paper_id === wb.activePaperId)?.session_id ?? null
}

function onCreated(session: Session, _startingPrompt: string) {
  taskRequest.value = null
  if (session.paper_ids.length) {
    for (const pid of session.paper_ids) openPaper(pid, session.id)
    wb.setView('read')
  } else {
    // 无论文的研究讨论：打开会话管理视图（旧版 openSession 行为）。
    librarySession.value = session.id
    wb.setView('library')
  }
  void lib.refresh()
}

function openDomainDialog() {
  domainOpen.value = true
  domainSaved.value = false
  domainError.value = ''
}

async function createDomain() {
  const name = domainName.value.trim()
  if (!name || domainSaving.value) return
  domainSaving.value = true
  domainSaved.value = false
  domainError.value = ''
  try {
    await lib.createCollection(name)
    domainName.value = ''
    domainSaved.value = true
  } catch (e) {
    domainError.value = e instanceof Error ? e.message : '新增领域失败'
  } finally {
    domainSaving.value = false
  }
}
</script>

<template>
  <div class="workbench" :class="{ reading: wb.view === 'read' && wb.activePaperId !== null }">
    <TopNav @toggle-side="sideHidden = !sideHidden" />
    <div class="work-layout">
      <SideNav
        v-show="!sideHidden && !['frontier','library'].includes(wb.view)"
        @new-task="taskRequest = { mode: 'read' }"
        @open-import="openImport()"
        @new-domain="openDomainDialog"
        @open-paper="openPaper"
      />
      <ActivityPanel v-if="sideHidden" class="floating-activity" />
      <main class="work-main">
        <section v-show="wb.view === 'read'" class="reading-workspace">
          <PaperTabs @add="pickerOpen = true" @home="goHome" />
          <ReadingView :paper-id="readablePaperId" :session-id="activeSessionId()" @open-import="openImport" @open-paper="openPaper" @session-bound="(pid, sid) => wb.setTabSession(pid, sid)" @save-failed="showToast" />
          <section v-if="wb.activePaperId !== null && readablePaperId === null" class="fulltext-gate" role="status">
            <template v-if="missingPaper"><span class="gate-icon" aria-hidden="true">▤</span><p class="gate-kicker">已保存书目信息 · 待补充全文</p><h1>{{ missingPaper.title }}</h1><p class="muted">补充 PDF 后即可打开原文，开始批注和智能体会话。</p><div><button class="primary" @click="openImport(missingPaper.id)">＋ 为这篇论文补充 PDF</button><button @click="pickerOpen = true">选择其他论文</button></div></template>
            <StateFeedback
              v-else
              :loading="openingPaper"
              :error="openingError || null"
              retry-text="重新载入"
              @retry="checkFullText(wb.activePaperId)"
            />
          </section>
          <WelcomeView
            v-if="wb.activePaperId === null"
            @open-picker="pickerOpen = true"
            @start="q => (taskRequest = { mode: 'read', question: q })"
            @open-import="openImport()"
            @use-template="t => (taskRequest = { mode: t.skill === 'paper_compare' ? 'compare' : t.skill === 'chat' ? 'chat' : 'read', template: t })"
            @compare="wb.setView('compare')"
            @discuss="taskRequest = { mode: 'chat' }"
          />
        </section>
        <CompareView v-if="wb.view === 'compare'" />
        <FrontierView v-if="wb.view === 'frontier'" @open-paper="openPaper" @open-session="openSessionInLibrary" @library-updated="lib.refresh()" />
        <SchedulesView v-if="wb.view === 'schedules'" />
      <SkillsView v-if="wb.view === 'skills'" />
      <SettingsView v-if="wb.view === 'settings'" />
        <LibraryView v-if="wb.view === 'library'" :session-id="librarySession" @open-paper="openPaper" @open-import="openImport" @open-session="openSessionInLibrary" />
      </main>
    </div>
    <div v-if="toast" class="work-toast" role="status">{{ toast }}</div>
    <ImportOverlay v-if="importOpen" :target-paper-id="importTarget" @close="importOpen = false" @open-paper="openImportedPaper" @open-session="sid => { librarySession = sid; wb.setView('library'); importOpen = false }" @library-updated="lib.refresh()" />
    <OpenPaperDialog v-if="pickerOpen" @close="pickerOpen = false" @open="openPaper" @import="pickerOpen = false; openImport()" />
    <div v-if="taskRequest" class="dialog-overlay" @click.self="taskRequest = null">
      <TaskDialog
        :mode="taskRequest.mode"
        :question="taskRequest.question ?? ''"
        :template-id="taskRequest.template?.id ?? ''"
        @created="onCreated"
        @close="taskRequest = null"
        @open-import="openImport()"
      />
    </div>
    <div v-if="domainOpen" class="dialog-overlay" @click.self="domainOpen = !domainSaving">
      <div class="domain-dialog" role="dialog" aria-label="新增论文领域">
        <h2>新增论文领域</h2>
        <input v-model="domainName" maxlength="80" placeholder="领域名称，如：基础模型" @keydown.enter="createDomain" />
        <StateFeedback
          :saving="domainSaving"
          :saved="domainSaved"
          :save-error="domainError || null"
        />
        <div class="dialog-footer">
          <button type="button" :disabled="domainSaving" @click="domainOpen = false">取消</button>
          <button type="button" class="primary" :disabled="domainSaving || !domainName.trim()" @click="createDomain">{{ domainSaving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workbench { display: flex; flex-direction: column; height: 100dvh; }
.work-layout { position:relative; display: flex; flex: 1; min-height: 0; }
.floating-activity { position:absolute; top:var(--space-3); left:var(--space-3); z-index:30; width:min(280px,calc(100vw - 24px)); }
.work-main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.reading-workspace { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow:hidden; background:var(--surface); }
.module-placeholder { padding: var(--space-6); }
.dialog-overlay { position: fixed; inset: 0; background: rgb(0 0 0 / 0.25); display: flex; align-items: center; justify-content: center; z-index: 50; }
.domain-dialog { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-4); background: var(--bg); border-radius: var(--radius); width: min(400px, 92vw); }
.domain-dialog h2 { margin: 0; font-size: 16px; }
.dialog-footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
.form-error { color: var(--danger); margin: 0; }
.work-toast { position: fixed; bottom: var(--space-5); left: 50%; transform: translateX(-50%); background: var(--text); color: var(--bg); padding: var(--space-2) var(--space-4); border-radius: var(--radius); z-index: 60; max-width: 80vw; }
.fulltext-gate { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; gap:12px; padding:32px; overflow-y:auto; }
.fulltext-gate h1 { max-width:680px; font-size:23px; line-height:1.5; margin:0; }
.fulltext-gate p { margin:0; font-size:13px; }
.fulltext-gate .gate-kicker { color:var(--accent); font-size:11px; }
.fulltext-gate > div { display:flex; flex-wrap:wrap; justify-content:center; gap:8px; margin-top:12px; }
.gate-icon { font-size:36px; color:var(--accent); }
</style>
