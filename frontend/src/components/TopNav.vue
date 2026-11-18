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
    <a class="work-brand" href="/">研知 <small>研究工作台</small></a>
    <nav aria-label="功能导航">
      <button
        v-for="v in views"
        :key="v.id"
        :aria-current="wb.view === v.id ? 'page' : undefined"
        :class="{ active: wb.view === v.id }"
        @click="wb.setView(v.id)"
      >{{ v.label }}</button>
    </nav>
    <span class="connection" role="status">{{ wb.loaded ? '工作区已载入' : '载入中…' }}</span>
    <button class="theme-toggle" :aria-label="theme.mode === 'light' ? '切换深色主题' : '切换浅色主题'" @click="theme.toggle()">◐</button>
    <button class="side-toggle" aria-label="展开或收起论文导航" @click="emit('toggle-side')">☰</button>
  </header>
</template>

<style scoped>
.work-top { display:flex; align-items:center; gap:24px; padding:0 24px; min-height:64px; border-bottom:1px solid var(--border); background:var(--bg); flex-shrink:0; }
.work-brand { font-weight:750; font-size:21px; letter-spacing:2px; color:var(--accent); text-decoration:none; white-space:nowrap; }
.work-brand small { display:inline-block; color:var(--text-muted); font-size:11px; font-weight:400; letter-spacing:0; margin-left:10px; }
nav { display:flex; gap:12px; flex:1; align-self:stretch; }
nav button { border:0; border-bottom:2px solid transparent; border-radius:0; background:none; color:var(--text-muted); padding:0 14px; white-space:nowrap; }
nav button.active { color:var(--accent); border-bottom-color:var(--accent); font-weight:650; }
.connection { color:var(--text-muted); font-size:11px; white-space:nowrap; }
.theme-toggle,.side-toggle { padding:4px 8px; border-color:transparent; background:var(--surface); }
@media(max-width:1050px) { .work-brand small,.connection { display:none; } .work-top { gap:12px; padding:0 12px; } nav { gap:0; } }
@media(max-width:600px) { .work-top { min-height:54px; gap:6px; flex-wrap:wrap; padding:8px 12px 0; } .work-brand { font-size:18px; margin-right:auto; } nav { order:5; width:100%; flex:auto; height:42px; overflow-x:auto; } nav button { flex:1; padding:0 8px; font-size:12px; } }
</style>
