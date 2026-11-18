<script setup lang="ts">
import { onMounted, ref } from 'vue'
import TopNav from '@/components/TopNav.vue'
import SideNav from '@/components/SideNav.vue'
import PaperTabs from '@/components/PaperTabs.vue'
import ImportOverlay from '@/components/ImportOverlay.vue'
import WelcomeView from './WelcomeView.vue'
import ReadingView from './ReadingView.vue'
import LibraryView from './LibraryView.vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useLibraryStore } from '@/stores/library'
import type { Template } from '@/api/types'

const wb = useWorkbenchStore()
const lib = useLibraryStore()
const sideHidden = ref(false)
const importOpen = ref(false)

// Task 5 接入 TaskDialog：记录任务请求意图（新建阅读/模板/讨论）。
const taskRequest = ref<null | { mode: 'read' | 'compare' | 'chat' | 'review'; question?: string; template?: Template }>(null)

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
</script>

<template>
  <div class="workbench">
    <TopNav @toggle-side="sideHidden = !sideHidden" />
    <div class="work-layout">
      <SideNav
        v-show="!sideHidden"
        @new-task="taskRequest = { mode: 'read' }"
        @open-import="importOpen = true"
        @new-domain="taskRequest = { mode: 'read' }"
      />
      <main class="work-main">
        <section v-show="wb.view === 'read'" class="reading-workspace">
          <PaperTabs @add="taskRequest = { mode: 'read' }" @home="goHome" />
          <ReadingView v-if="wb.activePaperId !== null" :paper-id="wb.activePaperId" :session-id="activeSessionId()" />
          <WelcomeView
            v-else
            @start="q => (taskRequest = { mode: 'read', question: q })"
            @open-import="importOpen = true"
            @use-template="t => (taskRequest = { mode: 'read', template: t })"
            @compare="wb.setView('compare')"
            @discuss="taskRequest = { mode: 'chat' }"
          />
        </section>
        <section v-if="wb.view === 'compare'" class="module-placeholder">
          <h1>论文比较</h1>
          <p class="muted">比较视图迁移中。</p>
        </section>
        <section v-if="wb.view === 'schedules'" class="module-placeholder">
          <h1>定时任务</h1>
          <p class="muted">定时任务视图迁移中。</p>
        </section>
        <LibraryView v-if="wb.view === 'library'" />
      </main>
    </div>
    <ImportOverlay v-if="importOpen" @close="importOpen = false" />
  </div>
</template>

<style scoped>
.workbench { display: flex; flex-direction: column; height: 100dvh; }
.work-layout { display: flex; flex: 1; min-height: 0; }
.work-main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.reading-workspace { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow-y: auto; }
.module-placeholder { padding: var(--space-6); }
</style>
