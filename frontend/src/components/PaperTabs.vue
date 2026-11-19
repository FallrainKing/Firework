<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useLibraryStore } from '@/stores/library'

const wb = useWorkbenchStore()
const lib = useLibraryStore()
const emit = defineEmits<{ add: []; home: [] }>()
const overflowOpen = ref(false)
const viewportWidth = ref(window.innerWidth)
const tabsRow = ref<HTMLElement | null>(null)

const visibleCount = computed(() => {
  if (viewportWidth.value <= 600) return 1
  if (viewportWidth.value <= 900) return Math.max(1, Math.floor((viewportWidth.value - 260) / 180))
  return Math.max(1, Math.floor((viewportWidth.value - 380) / 190))
})
const visibleTabs = computed(() => wb.tabs.slice(0, visibleCount.value))
const overflowTabs = computed(() => wb.tabs.slice(visibleCount.value))
const hasOverflow = computed(() => overflowTabs.value.length > 0)

function resize() { viewportWidth.value = window.innerWidth }
onMounted(() => window.addEventListener('resize', resize))
onBeforeUnmount(() => window.removeEventListener('resize', resize))

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

function statusOf(paperId: number): { key: 'draft' | 'running' | 'failed'; label: string } | null {
  const status = wb.tabStatuses[paperId]
  if (!status) return null
  if (status.running) return { key: 'running', label: '运行中' }
  if (status.failed) return { key: 'failed', label: '失败' }
  if (status.draft) return { key: 'draft', label: '有草稿' }
  return null
}

function tabLabel(tab: { paper_id: number }): string {
  const status = statusOf(tab.paper_id)
  return status ? `${title(tab.paper_id)}（${status.label}）` : title(tab.paper_id)
}
</script>

<template>
  <div ref="tabsRow" class="paper-tab-row">
    <button class="tab-home" :class="{ active: wb.activePaperId === null }" aria-label="回到阅读起始页" @click="emit('home')">⌂ <span>阅读起始页</span></button>
    <div class="paper-tabs" role="tablist" aria-label="打开的论文">
      <div
        v-for="tab in visibleTabs"
        :key="tab.paper_id"
        class="paper-tab"
        :class="{ active: wb.activePaperId === tab.paper_id }"
        role="tab"
        :aria-selected="wb.activePaperId === tab.paper_id"
        :aria-label="tabLabel(tab)"
        :title="title(tab.paper_id)"
        :tabindex="wb.activePaperId === tab.paper_id ? 0 : -1"
        @keydown.space.prevent="wb.activate(tab.paper_id)"
        @keydown.delete.prevent="wb.closeTab(tab.paper_id)"
        @keydown.arrow-right.prevent="moveTab(tab.paper_id, 1, $event)"
        @keydown.arrow-left.prevent="moveTab(tab.paper_id, -1, $event)"
        @click="wb.activate(tab.paper_id)"
        @keydown.enter="wb.activate(tab.paper_id)"
      >
        <span class="tab-title">{{ title(tab.paper_id) }}</span>
        <span v-if="statusOf(tab.paper_id)" class="status-dot" :class="statusOf(tab.paper_id)!.key" :aria-label="statusOf(tab.paper_id)!.label" :title="statusOf(tab.paper_id)!.label"></span>
        <button
          class="tab-close"
          :aria-label="'关闭标签 ' + title(tab.paper_id)"
          @click.stop="wb.closeTab(tab.paper_id)"
        >×</button>
      </div>
    </div>
    <button class="tab-add" aria-label="新增论文标签" @click="emit('add')">＋</button>
    <div v-if="hasOverflow" class="overflow-wrap">
      <button class="tab-overflow" :aria-expanded="overflowOpen" aria-haspopup="true" @click="overflowOpen = !overflowOpen">⋯</button>
      <div v-if="overflowOpen" class="overflow-menu" role="menu" aria-label="更多论文标签">
        <button
          v-for="tab in overflowTabs"
          :key="tab.paper_id"
          role="menuitem"
          :class="{ active: wb.activePaperId === tab.paper_id }"
          :title="title(tab.paper_id)"
          @click="wb.activate(tab.paper_id); overflowOpen = false"
        >
          <span class="overflow-title">{{ title(tab.paper_id) }}</span>
          <span v-if="statusOf(tab.paper_id)" class="status-dot" :class="statusOf(tab.paper_id)!.key"></span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.paper-tab-row { position:relative; display:flex; align-items:stretch; gap:0; padding:8px 12px 0; border-bottom:1px solid var(--border); background:var(--surface); flex-shrink:0; min-height:46px; max-width:100%; min-width:0; }
.paper-tabs { display:flex; gap:4px; overflow:hidden; flex:0 1 auto; min-width:0; }
.paper-tab { display:flex; align-items:center; gap:8px; flex:0 1 180px; width:180px; max-width:180px; min-width:72px; padding:8px 8px 8px 10px; border:1px solid transparent; border-bottom:0; border-radius:8px 8px 0 0; background:none; cursor:pointer; white-space:nowrap; color:var(--text-muted); font-size:12px; }
.paper-tab.active { border-color:var(--border); background:var(--bg); color:var(--text); box-shadow:inset 0 2px var(--accent); }
.tab-title { overflow:hidden; text-overflow:ellipsis; min-width:0; flex:1; }
.status-dot { width:7px; height:7px; border-radius:50%; flex-shrink:0; }
.status-dot.draft { background:var(--warning, #d97706); }
.status-dot.running { background:var(--accent); animation: tab-pulse 1.2s infinite; }
.status-dot.failed { background:var(--danger); }
@keyframes tab-pulse { 50% { opacity:.35; } }
.tab-close { border:0; background:none; padding:0 4px; color:var(--text-muted); font-size:15px; margin-left:auto; flex-shrink:0; }
.tab-close:hover { color:var(--danger); }
.tab-add,.tab-home { padding:6px 10px; margin-bottom:4px; border:0; background:none; font-size:12px; white-space:nowrap; flex-shrink:0; }
.tab-home { margin-right:8px; color:var(--text-muted); }.tab-home.active { color:var(--accent); background:var(--accent-soft); }
.overflow-wrap { margin-left:auto; position:relative; display:flex; align-items:center; flex-shrink:0; }
.tab-overflow { border:0; background:none; padding:6px 8px; color:var(--text-muted); }
.overflow-menu { position:absolute; top:100%; right:0; z-index:40; min-width:220px; max-width:min(320px,90vw); max-height:50vh; overflow:auto; background:var(--bg); border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow); }
.overflow-menu button { display:flex; align-items:center; gap:8px; width:100%; padding:8px 10px; border:0; background:none; text-align:left; color:var(--text); }
.overflow-menu button.active { color:var(--accent); background:var(--accent-soft); }
.overflow-title { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
@media(max-width:600px) { .tab-home span { display:none; }.paper-tab { flex:1 1 auto; max-width:none; }.paper-tab-row { padding-left:4px; padding-right:4px; }.overflow-menu { right:-4px; } }
</style>
