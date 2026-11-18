<script setup lang="ts">
defineProps<{ text: string }>()
</script>

<template>
  <p class="empty-state muted">{{ text }}</p>
</template>

<style scoped>
.empty-state { padding: var(--space-4); text-align: center; }
</style>
