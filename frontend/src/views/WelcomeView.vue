<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { sessionsApi } from '@/api/sessions'
import type { Template } from '@/api/types'

const emit = defineEmits<{
  start: [question: string]
  'open-import': []
  'open-picker': []
  'use-template': [template: Template]
  compare: []
  discuss: []
}>()

const question = ref('')
const templateError = ref('')
const templates = ref<Template[]>([])

onMounted(async () => {
  try {
    const { templates: list } = await sessionsApi.templates()
    templates.value = list.filter(t => t.builtin && ['paper_read', 'paper_review', 'paper_compare', 'chat'].includes(t.skill)).slice(0, 6)
  } catch { templateError.value = '模板暂时无法载入，你仍可选择论文开始阅读。' }
})

function submit() {
  const text = question.value.trim()
  if (text) emit('start', text)
}
</script>

<template>
  <section class="work-welcome">
    <div class="welcome-mark" aria-hidden="true">▤</div>
    <p class="eyebrow">RESEARCH WORKSPACE</p>
    <h1>从一篇论文，开始新的发现</h1>
    <p class="muted">打开原文，与智能体一起阅读、提问和整理思路。上次的进度会为你保留。</p>
    <form @submit.prevent="submit">
      <label class="sr-only" for="work-question">这次想研究什么</label>
      <textarea id="work-question" v-model="question" rows="3" maxlength="3000" placeholder="例如：阅读这篇论文，解释核心方法，并帮我检查实验结论…" />
      <div class="start-actions">
        <button type="button" @click="emit('open-picker')">＋ 选择 / 导入论文</button>
        <button class="primary" :disabled="!question.trim()">开始阅读 →</button>
      </div>
    </form>
    <p class="input-hint muted">先选择阅读材料，再开始会话。选择论文和模板不会调用智能体。</p>
    <div class="welcome-templates">
      <h2>常用任务模板</h2>
      <p v-if="templateError" class="muted" role="status">{{ templateError }}</p>
      <div class="template-grid">
        <button v-for="t in templates" :key="t.id" class="template-card" @click="emit('use-template', t)">
          <span class="template-symbol" aria-hidden="true">{{ t.skill === 'paper_compare' ? '⇄' : t.skill === 'paper_review' ? '✓' : t.skill === 'chat' ? '✧' : '▤' }}</span><strong>{{ t.name }}</strong>
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
.work-welcome { width:100%; max-width:920px; padding:clamp(32px,7vh,80px) 40px 32px; margin:0 auto; overflow-y:auto; }
.welcome-mark { width:36px; height:36px; display:grid; place-items:center; background:var(--accent-soft); color:var(--accent); border-radius:10px; font-size:21px; margin-bottom:12px; }
.eyebrow { color:var(--accent); font-size:12px; letter-spacing:.1em; font-weight:600; margin:0 0 10px; }
h1 { margin:0 0 10px; font-size:clamp(26px,2.6vw,34px); letter-spacing:-.04em; font-weight:650; }
.work-welcome > .muted { font-size:13px; line-height:1.9; }
form { margin:20px 0 10px; padding:18px; border:1px solid var(--border); border-radius:var(--radius-panel); background:var(--bg); box-shadow:none; }
form:focus-within { border-color:var(--accent); }
textarea { width:100%; padding:4px; min-height:80px; border:0; outline:none!important; resize:vertical; line-height:1.8; font-size:14px; }
.start-actions { display:flex; align-items:center; gap:8px; justify-content:space-between; margin-top:12px; }
.start-actions button { font-size:12px; }
.start-actions button:first-child { border:0; background:var(--surface); }
.input-hint { font-size:12px; margin:0 4px 22px; }
.welcome-templates h2 { font-size:12px; font-weight:500; color:var(--text-muted); margin:0 0 14px; }
.template-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.template-card { display:flex; flex-direction:column; gap:8px; align-items:flex-start; text-align:left; padding:14px; background:var(--bg); border-radius:var(--radius); }
.template-card:hover { background:var(--accent-soft); }
.template-symbol { color:var(--accent); font-size:18px; }
.template-card strong { font-size:13px; font-weight:600; }
.template-card .muted { font-size:12px; line-height:1.8; }
.welcome-foot { display:flex; justify-content:center; gap:16px; margin-top:18px; }
.welcome-foot button { font-size:12px; border:0; background:none; color:var(--text-muted); padding:4px 0; }
@media(max-width:1000px) { .work-welcome { padding:32px 24px; } .template-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(max-width:480px) { .work-welcome { padding:24px 18px; } .template-grid { grid-template-columns:1fr 1fr; gap:8px; } .template-card { padding:12px; } .start-actions { align-items:stretch; } }
</style>
