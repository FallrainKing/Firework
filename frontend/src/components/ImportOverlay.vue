<script setup lang="ts">
// 搜索/导入：沿用现有 discover.html（计划五 Vue 化）。
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <div class="import-overlay">
    <div class="import-bar">
      <button @click="emit('close')">← 返回工作台</button>
    </div>
    <iframe class="import-frame" src="/discover.html" title="搜索、导入与会话" />
  </div>
</template>

<style scoped>
.import-overlay { position: fixed; inset: 0; background: var(--bg); z-index: 40; display: flex; flex-direction: column; }
.import-bar { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border); }
.import-frame { flex: 1; width: 100%; border: none; }
</style>
