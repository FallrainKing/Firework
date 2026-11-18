<script setup lang="ts">
// Task 6 实现 iframe 池与 postMessage 保存协议；当前为占位。
defineProps<{ paperId: number; sessionId: number | null }>()
</script>

<template>
  <div class="reading-placeholder muted">阅读视图加载中（论文 {{ paperId }}）…</div>
</template>

<style scoped>
.reading-placeholder { padding: var(--space-6); }
</style>
