<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { sessionsApi } from '@/api/sessions'
import { useSchedulesStore } from '@/stores/schedules'
import type { Session } from '@/api/types'

const emit = defineEmits<{ close: [] }>()
const store = useSchedulesStore()

const title = ref('')
const conversationId = ref<number | null>(null)
const prompt = ref('')
const intervalHours = ref(24)
const sessions = ref<Session[]>([])
const saving = ref(false)
const error = ref('')

onMounted(async () => {
  const { sessions: list } = await sessionsApi.list({ archived: false, limit: 100 })
  sessions.value = list.filter(s => s.skill !== 'paper_import')
})

async function save() {
  if (!title.value.trim() || !prompt.value.trim() || conversationId.value === null) return
  saving.value = true
  error.value = ''
  try {
    // 新建任务默认暂停，避免意外产生模型调用。
    await store.create({ title: title.value.trim(), conversation_id: conversationId.value, prompt: prompt.value, interval_hours: intervalHours.value, enabled: false })
    emit('close')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '创建定时任务失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="schedule-dialog" role="dialog" aria-label="新建定时任务">
    <div class="dialog-heading">
      <h2>新建定时任务</h2>
      <button type="button" aria-label="关闭" @click="emit('close')">×</button>
    </div>
    <p class="muted">复用已有任务会话，按间隔交给现有智能体执行。新建任务默认暂停。</p>
    <label>任务名称
      <input v-model="title" data-field="title" maxlength="160" placeholder="如：论文阅读回顾" />
    </label>
    <label>关联会话
      <select v-model="conversationId" data-field="conversation">
        <option :value="null" disabled>选择会话…</option>
        <option v-for="s in sessions" :key="s.id" :value="s.id">{{ s.title }}</option>
      </select>
    </label>
    <label>每次执行的要求
      <textarea v-model="prompt" data-field="prompt" rows="3" maxlength="3000" />
    </label>
    <label>间隔（小时）
      <input v-model.number="intervalHours" data-field="interval" type="number" min="1" max="8760" />
    </label>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <div class="dialog-footer">
      <button type="button" @click="emit('close')">取消</button>
      <button type="button" class="primary" data-action="create" :disabled="saving || !title.trim() || !prompt.trim() || conversationId === null" @click="save">
        {{ saving ? '创建中…' : '创建（默认暂停）' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.schedule-dialog { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-4); background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); width: min(520px, 92vw); max-height: 86dvh; overflow-y: auto; }
.dialog-heading { display: flex; justify-content: space-between; align-items: center; }
.dialog-heading h2 { margin: 0; font-size: 16px; }
.dialog-heading button { border: none; background: none; font-size: 18px; }
label { display: flex; flex-direction: column; gap: var(--space-1); font-size: 13px; color: var(--text-muted); }
.dialog-footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
.form-error { color: var(--danger); margin: 0; }
</style>
