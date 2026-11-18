<script setup lang="ts">
import { useWorkbenchStore } from '@/stores/workbench'
import { useLibraryStore } from '@/stores/library'

const wb = useWorkbenchStore()
const lib = useLibraryStore()
const emit = defineEmits<{ add: []; home: [] }>()

function title(paperId: number): string {
  return lib.papersById[paperId]?.title ?? `论文 ${paperId}`
}
</script>

<template>
  <div class="paper-tab-row">
    <div class="paper-tabs" role="tablist" aria-label="打开的论文">
      <div
        v-for="tab in wb.tabs"
        :key="tab.paper_id"
        class="paper-tab"
        :class="{ active: wb.activePaperId === tab.paper_id }"
        role="tab"
        :aria-selected="wb.activePaperId === tab.paper_id"
        tabindex="0"
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
    <button class="tab-home" aria-label="回到阅读起始页" @click="emit('home')">⌂</button>
  </div>
</template>

<style scoped>
.paper-tab-row { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border); background: var(--surface); }
.paper-tabs { display: flex; gap: var(--space-1); overflow-x: auto; flex: 1; }
.paper-tab { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-1) var(--space-3); border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg); cursor: pointer; white-space: nowrap; max-width: 220px; }
.paper-tab.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
.tab-title { overflow: hidden; text-overflow: ellipsis; }
.tab-close { border: none; background: none; padding: 0 var(--space-1); color: var(--text-muted); font-size: 14px; }
.tab-close:hover { color: var(--danger); }
.tab-add, .tab-home { padding: var(--space-1) var(--space-2); }
</style>
