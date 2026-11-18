<script setup lang="ts">
import { useWorkbenchStore } from '@/stores/workbench'
import { useLibraryStore } from '@/stores/library'

const wb = useWorkbenchStore()
const lib = useLibraryStore()
const emit = defineEmits<{ add: []; home: [] }>()

function moveTab(paperId: number, delta: number, event: KeyboardEvent) {
  const index = wb.tabs.findIndex(t => t.paper_id === paperId)
  const next = (index + delta + wb.tabs.length) % wb.tabs.length
  wb.activate(wb.tabs[next].paper_id)
  const list = (event.currentTarget as HTMLElement).parentElement
  ;(list?.children[next] as HTMLElement)?.focus()
}

function title(paperId: number): string {
  return lib.papersById[paperId]?.title ?? `论文 ${paperId}`
}
</script>

<template>
  <div class="paper-tab-row">
    <button class="tab-home" :class="{ active: wb.activePaperId === null }" aria-label="回到阅读起始页" @click="emit('home')">⌂ <span>阅读起始页</span></button>
    <div class="paper-tabs" role="tablist" aria-label="打开的论文">
      <div
        v-for="tab in wb.tabs"
        :key="tab.paper_id"
        class="paper-tab"
        :class="{ active: wb.activePaperId === tab.paper_id }"
        role="tab"
        :aria-selected="wb.activePaperId === tab.paper_id"
        :tabindex="wb.activePaperId === tab.paper_id ? 0 : -1"
        @keydown.space.prevent="wb.activate(tab.paper_id)"
        @keydown.delete.prevent="wb.closeTab(tab.paper_id)"
        @keydown.arrow-right.prevent="moveTab(tab.paper_id, 1, $event)"
        @keydown.arrow-left.prevent="moveTab(tab.paper_id, -1, $event)"
        @click="wb.activate(tab.paper_id)"
        @keydown.enter="wb.activate(tab.paper_id)"
      >
        <span class="tab-title">{{ title(tab.paper_id) }}</span>
        <button
          class="tab-close"
          :aria-label="'关闭标签 ' + title(tab.paper_id)"
          @click.stop="wb.closeTab(tab.paper_id)"
        >×</button>
      </div>
    </div>
    <button class="tab-add" aria-label="新增论文标签" @click="emit('add')">＋</button>

  </div>
</template>

<style scoped>
.paper-tab-row { display:flex; align-items:stretch; gap:0; padding:8px 12px 0; border-bottom:1px solid var(--border); background:var(--surface); flex-shrink:0; min-height:46px; }
.paper-tabs { display:flex; gap:4px; overflow-x:auto; flex:1; min-width:0; scrollbar-width:thin; }
.paper-tab { display:flex; align-items:center; gap:12px; padding:8px 10px 8px 14px; border:1px solid transparent; border-bottom:0; border-radius:8px 8px 0 0; background:none; cursor:pointer; white-space:nowrap; max-width:240px; min-width:130px; color:var(--text-muted); font-size:12px; }
.paper-tab.active { border-color:var(--border); background:var(--bg); color:var(--text); box-shadow:inset 0 2px var(--accent); }
.tab-title { overflow:hidden; text-overflow:ellipsis; }
.tab-close { border:0; background:none; padding:0 4px; color:var(--text-muted); font-size:15px; margin-left:auto; }
.tab-close:hover { color:var(--danger); }
.tab-add,.tab-home { padding:6px 10px; margin-bottom:4px; border:0; background:none; font-size:12px; white-space:nowrap; flex-shrink:0; }
.tab-home { margin-right:8px; color:var(--text-muted); }.tab-home.active { color:var(--accent); background:var(--accent-soft); }
@media(max-width:600px) { .tab-home span { display:none; }.paper-tab { max-width:170px; }.paper-tab-row { padding-left:4px; padding-right:4px; } }
</style>
