<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { sessionsApi } from '@/api/sessions'
import type { Template } from '@/api/types'

const emit = defineEmits<{ close: [] }>()
const templates = ref<Template[]>([])
const skills = ref<Array<{ id: string; name: string }>>([])
const name = ref('')
const description = ref('')
const skill = ref('chat')
const prompt = ref('')
const error = ref('')
const saving = ref(false)

onMounted(async () => {
  const data = await sessionsApi.templates()
  templates.value = data.templates
  skills.value = data.skills
})

async function save() {
  if (!name.value.trim()) { error.value = '请填写模板名称'; return }
  saving.value = true
  error.value = ''
  try {
    await sessionsApi.createTemplate({ name: name.value.trim(), description: description.value, skill: skill.value, prompt: prompt.value })
    templates.value = (await sessionsApi.templates()).templates
    name.value = ''; description.value = ''; prompt.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="template-manager" role="dialog" aria-label="模板管理">
    <div class="dialog-heading">
      <h2>任务模板</h2>
      <button type="button" aria-label="关闭" @click="emit('close')">×</button>
    </div>
    <ul class="template-list">
      <li v-for="t in templates" :key="t.id">
        <strong>{{ t.name }}</strong>
        <span class="muted">{{ t.skill }}{{ t.builtin ? ' · 内置' : '' }}</span>
      </li>
    </ul>
    <h3>新增模板</h3>
    <label>名称<input v-model="name" maxlength="80" /></label>
    <label>说明<input v-model="description" maxlength="400" /></label>
    <label>能力
      <select v-model="skill">
        <option v-for="s in skills" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
    </label>
    <label>起步提示词<textarea v-model="prompt" rows="3" maxlength="3000"></textarea></label>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <div class="dialog-footer">
      <button type="button" class="primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存模板' }}</button>
    </div>
  </div>
</template>

<style scoped>
.template-manager { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-4); background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); width: min(520px, 92vw); max-height: 86dvh; overflow-y: auto; }
.dialog-heading { display: flex; justify-content: space-between; align-items: center; }
.dialog-heading h2 { margin: 0; font-size: 16px; }
.dialog-heading button { border: none; background: none; font-size: 18px; }
.template-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-1); }
.template-list li { display: flex; justify-content: space-between; gap: var(--space-2); padding: var(--space-1) var(--space-2); border: 1px solid var(--border); border-radius: var(--radius); }
h3 { font-size: 13px; margin: 0; color: var(--text-muted); }
label { display: flex; flex-direction: column; gap: var(--space-1); font-size: 13px; color: var(--text-muted); }
.dialog-footer { display: flex; justify-content: flex-end; }
.form-error { color: var(--danger); margin: 0; }
</style>
