<script setup lang="ts">
import { computed } from 'vue'
// 论文库管理：沿用现有 manage.html（计划五 Vue 化）。
// view=library 直达论文网格；sessionId 用于打开无论文的研究讨论会话。
const props = withDefaults(defineProps<{ sessionId?: number | null }>(), { sessionId: null })
const src = computed(() =>
  props.sessionId !== null
    ? '/manage.html?embed=1&session_id=' + props.sessionId
    : '/manage.html?view=library&embed=1',
)
</script>

<template>
  <iframe class="library-frame" :src="src" title="论文库管理" />
</template>

<style scoped>
.library-frame { width: 100%; height: 100%; border: none; }
</style>
