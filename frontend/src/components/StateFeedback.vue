<script setup lang="ts">
withDefaults(defineProps<{
  loading?: boolean
  error?: string | null
  empty?: boolean
  emptyText?: string
  saving?: boolean
  saved?: string | boolean
  saveError?: string | null
  retryText?: string
}>(), {
  loading: false,
  error: null,
  empty: false,
  emptyText: '暂无内容',
  saving: false,
  saved: false,
  saveError: null,
  retryText: '重试',
})

defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="state-feedback" aria-live="polite">
    <p v-if="loading" class="state loading" role="status">正在载入…</p>
    <p v-else-if="error" class="state error" role="alert">
      <span>{{ error }}</span>
      <button type="button" @click="$emit('retry')">{{ retryText }}</button>
    </p>
    <p v-if="empty && !loading && !error" class="state empty">{{ emptyText }}</p>
    <p v-if="saving" class="state saving" role="status">保存中…</p>
    <p v-if="saveError" class="state error save-error" role="alert">保存失败：{{ saveError }}</p>
    <p v-else-if="saved && !saving" class="state saved" role="status">{{ typeof saved === 'string' ? saved : '已保存' }}</p>
  </div>
</template>

<style scoped>
.state-feedback { display: grid; gap: var(--space-1); margin: 0; }
.state { margin: 0; padding: var(--space-2) var(--space-3); border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); color: var(--text-muted); }
.loading, .saving, .saved { border-color: var(--accent); color: var(--accent); }
.empty { border-style: dashed; }
.error { border-color: var(--danger); color: var(--danger); }
.error { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); flex-wrap: wrap; }
.error span { min-width: 0; overflow-wrap: anywhere; }
.error button { border-color: currentColor; color: currentColor; }
</style>
