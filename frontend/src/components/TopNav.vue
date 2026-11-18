<script setup lang="ts">
import { useWorkbenchStore } from '@/stores/workbench'
import { useThemeStore } from '@/shared/theme/store'

const wb = useWorkbenchStore()
const theme = useThemeStore()
const emit = defineEmits<{ 'toggle-side': [] }>()

const views = [
  { id: 'read', label: '读论文' },
  { id: 'compare', label: '论文比较' },
  { id: 'schedules', label: '定时任务' },
  { id: 'library', label: '论文库管理' },
] as const
</script>

<template>
  <header class="work-top">
    <a class="work-brand" href="/v2/">研知 <small>研究工作台</small></a>
    <nav aria-label="功能导航">
      <button
        v-for="v in views"
        :key="v.id"
        :aria-current="wb.view === v.id ? 'page' : undefined"
        :class="{ active: wb.view === v.id }"
        @click="wb.setView(v.id)"
      >{{ v.label }}</button>
    </nav>
    <span class="connection" role="status">{{ wb.loaded ? '已连接' : '连接中…' }}</span>
    <button class="theme-toggle" :aria-label="theme.mode === 'light' ? '切换深色主题' : '切换浅色主题'" @click="theme.toggle()">◐</button>
    <button class="side-toggle" aria-label="展开或收起论文导航" @click="emit('toggle-side')">☰</button>
  </header>
</template>

<style scoped>
.work-top { display: flex; align-items: center; gap: var(--space-4); padding: var(--space-2) var(--space-4); border-bottom: 1px solid var(--border); background: var(--bg); }
.work-brand { font-weight: 600; color: var(--text); text-decoration: none; }
.work-brand small { color: var(--text-muted); font-weight: 400; margin-left: var(--space-1); }
nav { display: flex; gap: var(--space-1); flex: 1; }
nav button { border: none; background: none; color: var(--text-muted); padding: var(--space-2) var(--space-3); }
nav button.active { color: var(--accent); background: var(--accent-soft); }
.connection { color: var(--text-muted); font-size: 12px; }
.theme-toggle, .side-toggle { padding: var(--space-1) var(--space-2); }
</style>
