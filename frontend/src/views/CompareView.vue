<script setup lang="ts">
import { onMounted, ref } from 'vue'
import TaskDialog from '@/components/TaskDialog.vue'
import { sessionsApi } from '@/api/sessions'
import { useWorkbenchStore } from '@/stores/workbench'
import type { Session } from '@/api/types'

const wb = useWorkbenchStore()
const comparisons = ref<Session[]>([])
const dialogOpen = ref(false)
const loading = ref(false)

async function refresh() {
  loading.value = true
  try {
    const { sessions } = await sessionsApi.list({ kind: 'comparison', archived: false, limit: 100 })
    comparisons.value = sessions
  } finally {
    loading.value = false
  }
}

onMounted(refresh)

function open(session: Session) {
  for (const pid of session.paper_ids) wb.openPaper(pid, session.id)
  wb.setView('read')
}

function onCreated(session: Session, _prompt: string) {
  dialogOpen.value = false
  void refresh()
  open(session)
}
</script>

<template>
  <section class="compare-workspace">
    <div class="module-heading">
      <div>
        <p class="eyebrow">COMPARE & CONNECT</p>
        <h1>把方法放在一起看</h1>
        <p class="muted">选择至少两篇论文，建立可延续的比较会话。</p>
      </div>
      <button class="primary" data-action="new" @click="dialogOpen = true">＋ 新建论文比较</button>
    </div>
    <div class="comparison-list">
      <article v-for="s in comparisons" :key="s.id" class="comparison-card">
        <div class="comparison-info">
          <strong>{{ s.title }}</strong>
          <span class="muted">{{ s.paper_ids.length }} 篇论文 · {{ s.last_status }}</span>
          <span v-if="s.preview" class="muted preview">{{ s.preview }}</span>
        </div>
        <button data-action="open" @click="open(s)">打开论文标签</button>
      </article>
      <p v-if="!comparisons.length && !loading" class="muted">暂无比较会话。</p>
    </div>
    <div v-if="dialogOpen" class="dialog-overlay" @click.self="dialogOpen = false">
      <TaskDialog mode="compare" @created="onCreated" @close="dialogOpen = false" />
    </div>
  </section>
</template>

<style scoped>
.compare-workspace { padding: var(--space-5); overflow-y: auto; }
.module-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-4); margin-bottom: var(--space-4); }
.eyebrow { color: var(--accent); font-size: 11px; letter-spacing: 0.12em; margin: 0 0 var(--space-1); }
h1 { margin: 0 0 var(--space-1); font-size: 22px; }
.comparison-list { display: flex; flex-direction: column; gap: var(--space-3); }
.comparison-card { display: flex; justify-content: space-between; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
.comparison-info { display: flex; flex-direction: column; gap: var(--space-1); min-width: 0; }
.preview { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 480px; }
.dialog-overlay { position: fixed; inset: 0; background: rgb(0 0 0 / 0.25); display: flex; align-items: center; justify-content: center; z-index: 50; }
</style>
