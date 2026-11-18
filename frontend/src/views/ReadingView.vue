<script setup lang="ts">
import ReaderPane from './ReaderPane.vue'

// KeepAlive max=3 替代旧 iframe 池：LRU 缓存阅读面板，
// deactivated 时 ReaderPane 自行 flush 草稿/位置（对照旧 save-reader 协议语义）。
defineProps<{ paperId: number | null; sessionId: number | null }>()
const emit = defineEmits<{
  'open-paper': [paperId: number, sessionId?: number]
  'open-import': [paperId: number]
  'session-bound': [paperId: number, sessionId: number]
  'save-failed': [message: string]
}>()
</script>

<template>
  <div v-show="paperId !== null" class="reading-frames">
    <KeepAlive :max="3">
      <ReaderPane
        v-if="paperId !== null"
        :key="paperId + ':' + (sessionId ?? 'new')"
        :paper-id="paperId"
        :session-id="sessionId"
        @open-paper="(pid, sid) => emit('open-paper', pid, sid)"
        @open-import="pid => emit('open-import', pid)"
        @session-bound="sid => emit('session-bound', paperId!, sid)"
        @save-failed="m => emit('save-failed', m)"
      />
    </KeepAlive>
  </div>
</template>

<style scoped>
.reading-frames { flex: 1; min-height: 0; position: relative; display: flex; flex-direction: column; }
.reading-frames > :deep(*) { flex: 1; min-height: 0; }
</style>
