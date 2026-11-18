<script setup lang="ts">
import { computed, ref } from 'vue'
import ActivityPanel from './ActivityPanel.vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useLibraryStore } from '@/stores/library'

const wb = useWorkbenchStore()
const lib = useLibraryStore()
const emit = defineEmits<{ 'new-task': []; 'open-import': []; 'new-domain': []; 'open-paper': [paperId: number, sessionId?: number] }>()
const expanded = ref<number | null>(null)
const recentPapers = computed(() => lib.recent.filter((r, i, all) => all.findIndex(x => x.paper_id === r.paper_id) === i).slice(0, 8))

function paperTitle(id: number): string {
  return lib.papersById[id]?.title ?? `论文 ${id}`
}

async function toggleCollection(id: number) {
  expanded.value = expanded.value === id ? null : id
  if (expanded.value === id && !lib.papersByCollection[id]) await lib.loadCollection(id)
}

function openRecent(paperId: number, sessionId: number) {
  emit('open-paper', paperId, sessionId)
}

function openPaper(paperId: number) {
  emit('open-paper', paperId)
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
      <button v-for="r in recentPapers" :key="r.paper_id + '-' + r.conversation_id" class="side-item" :class="{ selected: wb.activePaperId === r.paper_id && wb.view === 'read' }" @click="openRecent(r.paper_id, r.conversation_id)">
        <span class="paper-icon" aria-hidden="true">▤</span><span class="item-title">{{ paperTitle(r.paper_id) }}</span>
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
          <span class="folder-icon" aria-hidden="true">{{ expanded === c.id ? '▾' : '▸' }}</span><span class="item-title">{{ c.name }}</span>
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
@media(max-width:760px) { .work-sidebar { position:absolute; inset:0 auto 0 0; z-index:35; box-shadow:8px 0 24px rgb(0 0 0 / .12); } }
</style>
