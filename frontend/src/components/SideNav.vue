<script setup lang="ts">
import { ref } from 'vue'
import ActivityPanel from './ActivityPanel.vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useLibraryStore } from '@/stores/library'

const wb = useWorkbenchStore()
const lib = useLibraryStore()
const emit = defineEmits<{ 'new-task': []; 'open-import': []; 'new-domain': [] }>()
const expanded = ref<number | null>(null)

function paperTitle(id: number): string {
  return lib.papersById[id]?.title ?? `论文 ${id}`
}

async function toggleCollection(id: number) {
  expanded.value = expanded.value === id ? null : id
  if (expanded.value === id && !lib.papersByCollection[id]) await lib.loadCollection(id)
}

function openRecent(paperId: number, sessionId: number) {
  wb.openPaper(paperId, sessionId)
  wb.setView('read')
}

function openPaper(paperId: number) {
  wb.openPaper(paperId)
  wb.setView('read')
}
</script>

<template>
  <aside class="work-sidebar">
    <button class="primary" @click="emit('new-task')">＋ 新建论文阅读</button>
    <button @click="emit('open-import')">搜索 / 导入论文</button>

    <div class="side-title">
      <h2>最近阅读</h2>
      <button aria-label="刷新论文导航" @click="lib.refresh()">↻</button>
    </div>
    <div class="recent-reading">
      <button v-for="r in lib.recent" :key="r.paper_id + '-' + r.conversation_id" class="side-item" @click="openRecent(r.paper_id, r.conversation_id)">
        <span class="item-title">{{ paperTitle(r.paper_id) }}</span>
      </button>
      <p v-if="!lib.recent.length" class="muted">暂无阅读记录</p>
    </div>

    <div class="side-title">
      <h2>论文领域</h2>
      <button aria-label="新增论文领域" @click="emit('new-domain')">＋</button>
    </div>
    <div class="domain-papers">
      <div v-for="c in lib.collections" :key="c.id" class="domain">
        <button class="side-item domain-head" @click="toggleCollection(c.id)">
          <span class="item-title">{{ c.name }}</span>
          <span class="muted">{{ c.count ?? 0 }}</span>
        </button>
        <div v-if="expanded === c.id" class="domain-list">
          <button v-for="p in lib.papersByCollection[c.id] ?? []" :key="p.id" class="side-item" @click="openPaper(p.id)">
            <span class="item-title">{{ p.title }}</span>
            <span v-if="!p.has_pdf" class="muted no-pdf">缺全文</span>
          </button>
        </div>
      </div>
      <p v-if="!lib.collections.length" class="muted">暂无领域分类</p>
    </div>

    <button class="side-schedule" @click="wb.setView('schedules')">◷ 定时任务</button>
    <ActivityPanel />
    <p class="muted sidebar-tip">阅读位置与会话自动保存<br />切换标签不会调用智能体</p>
  </aside>
</template>

<style scoped>
.work-sidebar { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border-right: 1px solid var(--border); background: var(--surface); width: 250px; overflow-y: auto; }
.side-title { display: flex; align-items: center; justify-content: space-between; margin-top: var(--space-3); }
.side-title h2 { font-size: 12px; color: var(--text-muted); margin: 0; font-weight: 600; }
.side-title button { border: none; background: none; padding: 0 var(--space-1); color: var(--text-muted); }
.side-item { display: flex; justify-content: space-between; gap: var(--space-2); width: 100%; border: none; background: none; text-align: left; padding: var(--space-1) var(--space-2); border-radius: var(--radius); }
.side-item:hover { background: var(--accent-soft); color: var(--accent); }
.item-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.domain-list { padding-left: var(--space-3); }
.no-pdf { font-size: 11px; flex-shrink: 0; }
.side-schedule { margin-top: var(--space-3); }
.sidebar-tip { font-size: 11px; margin-top: auto; padding-top: var(--space-3); }
</style>
