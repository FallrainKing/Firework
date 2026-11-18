<script setup lang="ts">
import { computed } from 'vue'
// 搜索/导入：沿用现有 discover.html（计划五 Vue 化）。
const props = withDefaults(defineProps<{ targetPaperId?: number | null }>(), { targetPaperId: null })
const emit = defineEmits<{ close: [] }>()
const src = computed(() =>
  props.targetPaperId !== null ? '/discover.html?target_paper_id=' + props.targetPaperId : '/discover.html',
)
</script>

<template>
  <div class="import-overlay">
    <div class="import-bar">
      <button @click="emit('close')">← 返回工作台</button>
    </div>
    <iframe class="import-frame" :src="src" title="搜索、导入与会话" />
  </div>
</template>

<style scoped>
.import-overlay { position: fixed; inset: 0; background: var(--bg); z-index: 40; display: flex; flex-direction: column; }
.import-bar { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border); }
.import-frame { flex: 1; width: 100%; border: none; }
</style>
