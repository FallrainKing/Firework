<script setup lang="ts">
// Task 5 实现完整聊天面板；当前占位。
import type { Session } from '@/api/types'
defineProps<{ session: Session | null; paperId: number; orchestrator?: unknown }>()
</script>

<template>
  <div class="chat-placeholder muted">会话面板加载中…</div>
</template>

<style scoped>
.chat-placeholder { padding: var(--space-4); }
</style>
