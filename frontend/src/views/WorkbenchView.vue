<script setup lang="ts">
import { onMounted, ref } from 'vue'
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
import type { Session, Template } from '@/api/types'

const wb = useWorkbenchStore()
const lib = useLibraryStore()
const sideHidden = ref(false)
const importOpen = ref(false)

const taskRequest = ref<null | { mode: 'read' | 'compare' | 'chat' | 'review'; question?: string; template?: Template }>(null)
const domainOpen = ref(false)
const domainName = ref('')
const domainError = ref('')

onMounted(async () => {
  await Promise.all([wb.load(), lib.refresh()])
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
  for (const pid of session.paper_ids) wb.openPaper(pid, session.id)
  wb.setView('read')
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
        @open-import="importOpen = true"
        @new-domain="domainOpen = true"
      />
      <main class="work-main">
        <section v-show="wb.view === 'read'" class="reading-workspace">
          <PaperTabs @add="taskRequest = { mode: 'read' }" @home="goHome" />
          <ReadingView v-if="wb.activePaperId !== null" :paper-id="wb.activePaperId" :session-id="activeSessionId()" @open-import="importOpen = true" />
          <WelcomeView
            v-else
            @start="q => (taskRequest = { mode: 'read', question: q })"
            @open-import="importOpen = true"
            @use-template="t => (taskRequest = { mode: 'read', template: t })"
            @compare="wb.setView('compare')"
            @discuss="taskRequest = { mode: 'chat' }"
          />
        </section>
        <CompareView v-if="wb.view === 'compare'" />
        <SchedulesView v-if="wb.view === 'schedules'" />
        <LibraryView v-if="wb.view === 'library'" />
      </main>
    </div>
    <ImportOverlay v-if="importOpen" @close="importOpen = false" />
    <div v-if="taskRequest" class="dialog-overlay" @click.self="taskRequest = null">
      <TaskDialog
        :mode="taskRequest.mode"
        :question="taskRequest.question ?? ''"
        :template-id="taskRequest.template?.id ?? ''"
        @created="onCreated"
        @close="taskRequest = null"
        @open-import="importOpen = true"
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
</style>
