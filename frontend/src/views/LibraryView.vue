<script setup lang="ts">
import { ref, watch } from 'vue'
import LibraryGrid from './manage/LibraryGrid.vue'
import SessionsManager from './manage/SessionsManager.vue'

// 论文库管理容器：论文库 / 任务会话两页（替代旧 manage.html iframe）。
const props = withDefaults(defineProps<{ sessionId?: number | null }>(), { sessionId: null })
const emit = defineEmits<{ 'open-paper': [paperId: number, sessionId?: number]; 'open-import': [paperId?: number] }>()

const page = ref<'library' | 'sessions'>(props.sessionId ? 'sessions' : 'library')
watch(() => props.sessionId, sid => { if (sid) page.value = 'sessions' })
</script>

<template>
  <div class="manage-view">
    <div class="manage-nav">
      <button :aria-current="page === 'library' ? 'page' : undefined" @click="page = 'library'">论文库</button>
      <button :aria-current="page === 'sessions' ? 'page' : undefined" @click="page = 'sessions'">任务会话</button>
    </div>
    <LibraryGrid v-if="page === 'library'" @open-paper="pid => emit('open-paper', pid)" @open-import="pid => emit('open-import', pid)" />
    <SessionsManager v-else :initial-session-id="sessionId" @open-paper="(pid, sid) => emit('open-paper', pid, sid)" @open-import="emit('open-import')" />
  </div>
</template>

<style scoped>
.manage-view { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.manage-nav { display: flex; gap: var(--space-1); padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border); }
.manage-nav button[aria-current='page'] { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.manage-view > :deep(*) { flex: 1; min-height: 0; }
</style>
