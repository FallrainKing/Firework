<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useActivityStore } from '@/stores/activity'

const activity = useActivityStore()
onMounted(() => activity.start())
onBeforeUnmount(() => activity.stop())

function summary(run: { progress?: { tools?: string[]; text?: string } }): string {
  const p = run.progress ?? {}
  const parts: string[] = []
  if (p.tools?.length) parts.push('正在调用 ' + p.tools.join('、'))
  if (p.text) parts.push(p.text)
  return parts.join(' · ') || '等待智能体响应…'
}
</script>

<template>
  <div v-if="activity.active.length" class="activity-panel" aria-label="运行中的任务">
    <h3>运行中</h3>
    <article v-for="run in activity.active" :key="run.id" class="activity-item">
      <div class="activity-info">
        <strong>{{ run.skill }}</strong>
        <span class="muted">{{ run.status === 'queued' ? '排队中' : summary(run) }}</span>
      </div>
      <button
        class="danger"
        :disabled="run.cancelling"
        :aria-label="'取消任务 ' + run.id"
        @click="activity.cancel(run.id)"
      >{{ run.cancelling ? '取消中…' : '取消' }}</button>
    </article>
  </div>
</template>

<style scoped>
.activity-panel { margin-top: var(--space-3); border-top: 1px solid var(--border); padding-top: var(--space-2); }
.activity-panel h3 { font-size: 12px; color: var(--text-muted); margin: 0 0 var(--space-2); }
.activity-item { display: flex; justify-content: space-between; align-items: center; gap: var(--space-2); padding: var(--space-2); border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg); margin-bottom: var(--space-2); }
.activity-info { display: flex; flex-direction: column; min-width: 0; }
.activity-info span { font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.activity-item button { padding: var(--space-1) var(--space-2); font-size: 12px; flex-shrink: 0; }
</style>
