<script setup lang="ts">
// Task 6 实现完整侧栏；当前占位。
import type { ReaderDoc, Session } from '@/api/types'
defineProps<{ doc: ReaderDoc | null; session: Session | null; orchestrator?: unknown }>()
</script>

<template>
  <div class="sidebar-placeholder muted">目录 / 批注 / 译文</div>
</template>

<style scoped>
.sidebar-placeholder { padding: var(--space-4); }
</style>
