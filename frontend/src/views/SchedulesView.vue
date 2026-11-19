<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ScheduleDialog from '@/components/ScheduleDialog.vue'
import { useSchedulesStore } from '@/stores/schedules'
import StateFeedback from '@/components/StateFeedback.vue'

const store = useSchedulesStore()
const dialogOpen = ref(false)
const busyId = ref<number | null>(null)
const actionError = ref<string | null>(null)
const actionSaved = ref(false)

onMounted(() => store.refresh())

async function toggle(id: number, enabled: boolean) {
  busyId.value = id
  actionError.value = null
  actionSaved.value = false
  try {
    await store.toggle(id, enabled)
    actionSaved.value = true
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : '定时任务保存失败'
  } finally {
    busyId.value = null
  }
}

async function run(id: number) {
  busyId.value = id
  actionError.value = null
  try {
    await store.run(id)
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : '定时任务执行失败'
  } finally {
    busyId.value = null
  }
}
</script>

<template>
  <section class="schedule-workspace">
    <div class="module-heading">
      <div>
        <p class="eyebrow">RESEARCH ROUTINES</p>
        <h1>定时任务</h1>
        <p class="muted">复用已有任务会话，按间隔交给现有智能体执行；新建任务默认暂停。</p>
      </div>
      <button class="primary" data-action="new" @click="dialogOpen = true">＋ 新建定时任务</button>
    </div>
    <div class="schedule-list">
      <StateFeedback
        :loading="store.loading && !store.schedules.length"
        :error="store.error"
        :empty="!store.loading && !store.error && !store.schedules.length"
        empty-text="暂无定时任务。"
        :saving="busyId !== null"
        :saved="actionSaved"
        :save-error="actionError"
        @retry="store.refresh"
      />
      <article v-for="s in store.schedules" :key="s.id" class="schedule-card">
        <div class="schedule-info">
          <strong>{{ s.title }}</strong>
          <span class="muted">{{ s.session_title ?? '会话 ' + s.conversation_id }} · 每 {{ s.interval_hours }} 小时</span>
          <span class="muted">下次：{{ s.next_at ?? '—' }}<template v-if="s.last_run_id"> · 最近已提交</template></span>
        </div>
        <div class="schedule-actions">
          <span class="state" :class="{ on: s.enabled }">{{ s.enabled ? '已启用' : '已暂停' }}</span>
          <button data-action="toggle" :disabled="busyId === s.id" @click="toggle(s.id, !s.enabled)">{{ s.enabled ? '暂停' : '启用' }}</button>
          <button data-action="run" :disabled="busyId === s.id" @click="run(s.id)">执行一次</button>
        </div>
      </article>
    </div>
    <div v-if="dialogOpen" class="dialog-overlay" @click.self="dialogOpen = false">
      <ScheduleDialog @close="dialogOpen = false" />
    </div>
  </section>
</template>

<style scoped>
.schedule-workspace { padding: var(--space-5); overflow-y: auto; }
.module-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-4); margin-bottom: var(--space-4); }
.eyebrow { color: var(--accent); font-size: 11px; letter-spacing: 0.12em; margin: 0 0 var(--space-1); }
h1 { margin: 0 0 var(--space-1); font-size: 22px; }
.schedule-list { display: flex; flex-direction: column; gap: var(--space-3); }
.schedule-card { display: flex; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) var(--space-4); border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
.schedule-info { display: flex; flex-direction: column; gap: var(--space-1); min-width: 0; }
.schedule-actions { display: flex; align-items: center; gap: var(--space-2); flex-shrink: 0; }
.state { font-size: 12px; color: var(--text-muted); }
.state.on { color: var(--success); }
.dialog-overlay { position: fixed; inset: 0; background: rgb(0 0 0 / 0.25); display: flex; align-items: center; justify-content: center; z-index: 50; }
</style>
