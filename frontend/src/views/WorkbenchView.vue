<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { attachBridge } from '@/shared/bridge'
import TopNav from '@/components/TopNav.vue'
import SideNav from '@/components/SideNav.vue'
import PaperTabs from '@/components/PaperTabs.vue'
import ImportOverlay from '@/components/ImportOverlay.vue'
import TaskDialog from '@/components/TaskDialog.vue'
import WelcomeView from './WelcomeView.vue'
import ReadingView from './ReadingView.vue'
import LibraryView from './LibraryView.vue'
import CompareView from './CompareView.vue'
import SchedulesView from './SchedulesView.vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useLibraryStore } from '@/stores/library'
import { useActivityStore } from '@/stores/activity'
import type { Session, Template } from '@/api/types'

const wb = useWorkbenchStore()
const lib = useLibraryStore()
const sideHidden = ref(false)
const importOpen = ref(false)

const taskRequest = ref<null | { mode: 'read' | 'compare' | 'chat' | 'review'; question?: string; template?: Template }>(null)
const domainOpen = ref(false)
const domainName = ref('')
const domainError = ref('')
const toast = ref('')
const importTarget = ref<number | null>(null)
const librarySession = ref<number | null>(null)
const activity = useActivityStore()
let toastTimer: ReturnType<typeof setTimeout> | null = null
let detachShell: (() => void) | null = null

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

onMounted(async () => {
  // shell 级桥接：覆盖阅读池 + 论文库 + 导入 iframe（origin/source 校验在 bridge 内）。
  detachShell = attachBridge(() => Array.from(document.querySelectorAll('iframe')), {
    onOpenPaper: (pid, sid) => { wb.openPaper(pid, sid); wb.setView('read') },
    onOpenImport: pid => openImport(pid),
    onNavigate: view => wb.setView(view as 'read' | 'compare' | 'schedules' | 'library'),
    onSession: (pid, sid) => wb.setTabSession(pid, sid),
    onLibraryUpdated: () => void lib.refresh(),
  })
  try {
    await Promise.all([wb.load(), lib.refresh()])
  } catch (e) {
    showToast(e instanceof Error ? e.message : '工作台加载失败')
  }
})

onBeforeUnmount(() => detachShell?.())

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
    for (const pid of session.paper_ids) wb.openPaper(pid, session.id)
    wb.setView('read')
  } else {
    // 无论文的研究讨论：打开会话管理视图（旧版 openSession 行为）。
    librarySession.value = session.id
    wb.setView('library')
  }
  void lib.refresh()
}

async function createDomain() {
  const name = domainName.value.trim()
  if (!name) return
  try {
    await lib.createCollection(name)
    domainOpen.value = false
    domainName.value = ''
    domainError.value = ''
  } catch (e) {
    domainError.value = e instanceof Error ? e.message : '新增领域失败'
  }
}
</script>

<template>
  <div class="workbench">
    <TopNav @toggle-side="sideHidden = !sideHidden" />
    <div class="work-layout">
      <SideNav
        v-show="!sideHidden"
        @new-task="taskRequest = { mode: 'read' }"
        @open-import="openImport()"
        @new-domain="domainOpen = true"
      />
      <main class="work-main">
        <section v-show="wb.view === 'read'" class="reading-workspace">
          <PaperTabs @add="taskRequest = { mode: 'read' }" @home="goHome" />
          <ReadingView :paper-id="wb.activePaperId" :session-id="activeSessionId()" @open-import="openImport" @open-paper="(pid, sid) => { wb.openPaper(pid, sid); wb.setView('read') }" @session-bound="(pid, sid) => wb.setTabSession(pid, sid)" @save-failed="showToast" />
          <WelcomeView
            v-if="wb.activePaperId === null"
            @start="q => (taskRequest = { mode: 'read', question: q })"
            @open-import="openImport()"
            @use-template="t => (taskRequest = { mode: t.skill === 'paper_compare' ? 'compare' : t.skill === 'chat' ? 'chat' : 'read', template: t })"
            @compare="wb.setView('compare')"
            @discuss="taskRequest = { mode: 'chat' }"
          />
        </section>
        <CompareView v-if="wb.view === 'compare'" />
        <SchedulesView v-if="wb.view === 'schedules'" />
        <LibraryView v-if="wb.view === 'library'" :session-id="librarySession" />
      </main>
    </div>
    <div v-if="toast" class="work-toast" role="status">{{ toast }}</div>
    <ImportOverlay v-if="importOpen" :target-paper-id="importTarget" @close="importOpen = false" />
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
    <div v-if="domainOpen" class="dialog-overlay" @click.self="domainOpen = false">
      <div class="domain-dialog" role="dialog" aria-label="新增论文领域">
        <h2>新增论文领域</h2>
        <input v-model="domainName" maxlength="80" placeholder="领域名称，如：基础模型" @keydown.enter="createDomain" />
        <p v-if="domainError" class="form-error" role="alert">{{ domainError }}</p>
        <div class="dialog-footer">
          <button type="button" @click="domainOpen = false">取消</button>
          <button type="button" class="primary" :disabled="!domainName.trim()" @click="createDomain">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workbench { display: flex; flex-direction: column; height: 100dvh; }
.work-layout { display: flex; flex: 1; min-height: 0; }
.work-main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.reading-workspace { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow-y: auto; }
.module-placeholder { padding: var(--space-6); }
.dialog-overlay { position: fixed; inset: 0; background: rgb(0 0 0 / 0.25); display: flex; align-items: center; justify-content: center; z-index: 50; }
.domain-dialog { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-4); background: var(--bg); border-radius: var(--radius); width: min(400px, 92vw); }
.domain-dialog h2 { margin: 0; font-size: 16px; }
.dialog-footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
.form-error { color: var(--danger); margin: 0; }
.work-toast { position: fixed; bottom: var(--space-5); left: 50%; transform: translateX(-50%); background: var(--text); color: var(--bg); padding: var(--space-2) var(--space-4); border-radius: var(--radius); z-index: 60; max-width: 80vw; }
</style>
