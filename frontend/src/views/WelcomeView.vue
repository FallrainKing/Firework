<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { sessionsApi } from '@/api/sessions'
import type { Template } from '@/api/types'

const emit = defineEmits<{
  start: [question: string]
  'open-import': []
  'use-template': [template: Template]
  compare: []
  discuss: []
}>()

const question = ref('')
const templates = ref<Template[]>([])

onMounted(async () => {
  const { templates: list } = await sessionsApi.templates()
  templates.value = list.filter(t => t.builtin)
})

function submit() {
  const text = question.value.trim()
  if (text) emit('start', text)
}
</script>

<template>
  <section class="work-welcome">
    <p class="eyebrow">YOUR RESEARCH, CONTINUED</p>
    <h1>打开一篇论文，继续你的研究</h1>
    <p class="muted">从左侧选择论文开始阅读，或创建一个新的研究任务。</p>
    <form @submit.prevent="submit">
      <label class="sr-only" for="work-question">这次想研究什么</label>
      <textarea id="work-question" v-model="question" rows="3" maxlength="3000" placeholder="例如：阅读这篇论文，解释核心方法，并帮我检查实验结论…" />
      <div class="start-actions">
        <button type="button" @click="emit('open-import')">选择 / 导入论文</button>
        <button class="primary" :disabled="!question.trim()">开始阅读 →</button>
      </div>
    </form>
    <div class="welcome-templates">
      <h2>常用任务模板</h2>
      <div class="template-grid">
        <button v-for="t in templates" :key="t.id" class="template-card" @click="emit('use-template', t)">
          <strong>{{ t.name }}</strong>
          <span class="muted">{{ t.description }}</span>
        </button>
      </div>
    </div>
    <div class="welcome-foot">
      <button data-action="compare" @click="emit('compare')">比较多篇论文</button>
      <button data-action="discuss" @click="emit('discuss')">独立研究讨论</button>
    </div>
  </section>
</template>

<style scoped>
.work-welcome { padding: var(--space-6); max-width: 760px; margin: 0 auto; }
.eyebrow { color: var(--accent); font-size: 11px; letter-spacing: 0.12em; margin: 0 0 var(--space-2); }
h1 { margin: 0 0 var(--space-2); font-size: 26px; }
form { margin: var(--space-5) 0; display: flex; flex-direction: column; gap: var(--space-3); }
textarea { width: 100%; resize: vertical; }
.start-actions { display: flex; gap: var(--space-2); justify-content: flex-end; }
.welcome-templates h2 { font-size: 14px; color: var(--text-muted); }
.template-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: var(--space-3); }
.template-card { display: flex; flex-direction: column; gap: var(--space-1); align-items: flex-start; text-align: left; padding: var(--space-3); background: var(--surface); }
.template-card span { font-size: 12px; }
.welcome-foot { display: flex; gap: var(--space-2); margin-top: var(--space-5); }
</style>
