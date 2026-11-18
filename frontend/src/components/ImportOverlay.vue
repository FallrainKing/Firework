<script setup lang="ts">
import { ref } from 'vue'
import ImportPanel from '@/views/discover/ImportPanel.vue'
import SearchPanel from '@/views/discover/SearchPanel.vue'

// 搜索/导入容器（替代旧 discover.html iframe）。
const props = withDefaults(defineProps<{ targetPaperId?: number | null }>(), { targetPaperId: null })
const emit = defineEmits<{
  close: []
  'open-paper': [paperId: number]
  'open-session': [sessionId: number]
  'library-updated': []
}>()
const page = ref<'import' | 'search'>('import')
</script>

<template>
  <div class="import-overlay">
    <div class="import-bar">
      <button @click="emit('close')">← 返回工作台</button>
      <div class="import-tabs">
        <button :aria-current="page === 'import' ? 'page' : undefined" @click="page = 'import'">导入</button>
        <button :aria-current="page === 'search' ? 'page' : undefined" @click="page = 'search'">搜索</button>
      </div>
    </div>
    <ImportPanel v-if="page === 'import'" :target-paper-id="props.targetPaperId" @open-paper="pid => emit('open-paper', pid)" @library-updated="emit('library-updated')" />
    <SearchPanel v-else @open-session="sid => emit('open-session', sid)" @library-updated="emit('library-updated')" />
  </div>
</template>

<style scoped>
.import-overlay { position: fixed; inset: 0; background: var(--bg); z-index: 40; display: flex; flex-direction: column; }
.import-bar { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border); }
.import-tabs { display: flex; gap: var(--space-1); }
.import-tabs button[aria-current='page'] { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.import-overlay > :deep(*) { flex: 1; min-height: 0; }
</style>
