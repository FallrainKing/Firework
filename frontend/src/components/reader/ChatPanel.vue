<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { agentApi } from '@/api/agent'
import { sessionsApi } from '@/api/sessions'
import { workbenchApi } from '@/api/workbench'
import { uid32 } from '@/api/client'
import type { Attachment, Run, SelectionContext, Session, Template } from '@/api/types'

const props = defineProps<{ session: Session | null; paperId: number; orchestrator?: { jump: (ctx: SelectionContext) => void; refreshAnnotations: () => Promise<void> } }>()

const QUICK: Template[] = [
  { id: 'quick_overview', name: '快速概览', description: '', kind: 'reading', skill: 'chat', prompt: '请概述当前论文的研究问题、方法、主要结论与材料覆盖范围。', builtin: 0 },
  { id: 'explain_method', name: '解释方法', description: '', kind: 'reading', skill: 'chat', prompt: '请结合当前论文的原文，逐步解释核心方法与关键公式。', builtin: 0 },
  { id: 'inspect_experiment', name: '检查实验', description: '', kind: 'reading', skill: 'chat', prompt: '请核对当前论文的实验设置、对照方法和结论支持程度，列出证据与疑问。', builtin: 0 },
]

const runs = ref<Run[]>([])
const question = ref('')
const context = ref<SelectionContext | null>(null)
const attachments = ref<Attachment[]>([])
const templates = ref<Template[]>([])
const busy = ref(false)
const uploading = ref(false)
const loading = ref(true)
const toast = ref('')
const chatBox = ref<HTMLElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

let epoch = 0
let saveTimer: ReturnType<typeof setTimeout> | null = null
let saveQueue: Promise<unknown> = Promise.resolve()
const watching = new Set<string>()
let stopped = false
onUnmounted(() => { stopped = true })
let currentSession: Session | null = props.session

const STATES: Record<string, string> = { queued: '排队', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const canSend = computed(() => !busy.value && !uploading.value && !!currentSession && !currentSession.archived)
const agentState = computed(() => uploading.value ? '上传图片中…' : busy.value ? '智能体正在执行…' : currentSession?.native_ready ? '继续当前原生会话' : '发送后才调用智能体')

function showToast(m: string) { toast.value = m; setTimeout(() => { toast.value = '' }, 5000) }
function scroll() { if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight }

async function loadTemplates() {
  const data = await sessionsApi.templates()
  templates.value = [...data.templates.filter(t => t.skill === currentSession?.skill || t.skill === 'chat'), ...QUICK]
}

async function load(session: Session) {
  const e = ++epoch
  currentSession = session
  loading.value = true
  busy.value = false
  context.value = null
  attachments.value = []
  runs.value = []
  const [data, draft] = await Promise.all([sessionsApi.runs(session.id, undefined, 100), workbenchApi.getDraft(session.id, props.paperId)])
  if (e !== epoch) return
  question.value = draft.prompt || (!data.runs.length ? session.draft_prompt : '') || ''
  context.value = draft.context
  attachments.value = draft.attachments ?? []
  runs.value = data.runs
  for (const r of data.runs) if (['queued', 'running'].includes(r.status)) { busy.value = true; void watchRun(r.id, session.id) }
  loading.value = false
  await loadTemplates()
  scroll()
}

async function restoreDraft() {
  if (loading.value || !currentSession) return
  const sid = currentSession.id
  const draft = await workbenchApi.getDraft(sid, props.paperId)
  if (currentSession?.id !== sid) return
  question.value = draft.prompt
  context.value = draft.context
  attachments.value = draft.attachments ?? []
}

function scheduleDraft() {
  if (loading.value || !currentSession) return
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => { void flushDraft().catch(e => showToast('草稿尚未保存：' + (e instanceof Error ? e.message : ''))) }, 400)
}

function flushDraft(): Promise<unknown> {
  if (saveTimer) clearTimeout(saveTimer)
  if (loading.value || !currentSession) return saveQueue
  const snapshot = { prompt: question.value, context: context.value, attachment_ids: attachments.value.map(a => a.id) }
  const sid = currentSession.id
  saveQueue = saveQueue.catch(() => {}).then(() => workbenchApi.saveDraft(sid, props.paperId, snapshot))
  return saveQueue
}

function setContext(ctx: SelectionContext | null) {
  context.value = ctx
  scheduleDraft()
}

function removeAttachment(id: string) {
  attachments.value = attachments.value.filter(a => a.id !== id)
  scheduleDraft()
}

async function uploadFiles(files: File[]) {
  if (!files.length || !currentSession) return
  if (files.length + attachments.value.length > 3) throw new Error('每次提问最多 3 张图片')
  if (files.some(f => f.size > 5 * 1024 * 1024)) throw new Error('每张图片不超过 5MB')
  const sid = currentSession.id
  uploading.value = true
  try {
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      form.append('conversation_id', String(sid))
      form.append('paper_id', String(props.paperId))
      const a = await workbenchApi.uploadImage(form)
      if (currentSession?.id === sid) {
        attachments.value.push(a)
        await flushDraft()
      } else {
        const old = await workbenchApi.getDraft(sid, props.paperId)
        await workbenchApi.saveDraft(sid, props.paperId, { prompt: old.prompt, context: old.context, attachment_ids: [...old.attachment_ids, a.id].slice(0, 3) })
      }
    }
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function onFiles() {
  const files = Array.from(fileInput.value?.files ?? [])
  void uploadFiles(files).catch(e => showToast(e instanceof Error ? e.message : '上传失败'))
}

function applyTemplate(id: string) {
  const t = templates.value.find(x => x.id === id)
  if (t?.prompt) question.value = [question.value, t.prompt].filter(Boolean).join('\n\n')
  scheduleDraft()
}

function upsertRun(r: Run) {
  const i = runs.value.findIndex(x => x.id === r.id)
  if (i >= 0) runs.value[i] = r
  else runs.value.push(r)
}

async function ask(prompt: string, contexts: SelectionContext[] = [], purpose = 'chat') {
  if (!prompt.trim() || !currentSession) return
  if (busy.value || uploading.value) throw new Error('当前会话仍在处理，请稍候')
  const sid = currentSession.id
  const storage = 'reader-pending-' + sid
  const attachment_ids = attachments.value.map(a => a.id)
  let body: Record<string, unknown> | null = null
  try {
    const old = JSON.parse(localStorage.getItem(storage) || 'null')
    body = old && old.prompt === prompt && JSON.stringify(old.contexts) === JSON.stringify(contexts) && JSON.stringify(old.attachment_ids || []) === JSON.stringify(attachment_ids) ? old : null
  } catch { /* ignore */ }
  body = body ?? { conversation_id: sid, prompt, contexts, purpose, attachment_ids, request_key: uid32() }
  localStorage.setItem(storage, JSON.stringify(body))
  busy.value = true
  try {
    const run = await agentApi.createRun(body as never)
    if (currentSession?.id === sid) {
      upsertRun(run)
      question.value = ''
      attachments.value = []
      setContext(null)
      await flushDraft()
      scroll()
    }
    void watchRun(run.id, sid)
  } catch (e) {
    busy.value = false
    throw e
  }
}

async function watchRun(id: string, sid = currentSession?.id) {
  if (watching.has(id)) return
  watching.add(id)
  if (currentSession?.id === sid) busy.value = true
  try {
    while (!stopped) {
      const r = await agentApi.getRun(id)
      if (stopped) break
      if (currentSession?.id === sid) upsertRun(r)
      if (['succeeded', 'failed', 'cancelled'].includes(r.status)) {
        localStorage.removeItem('reader-pending-' + sid)
        if (currentSession?.id === sid) {
          busy.value = false
          currentSession = (await sessionsApi.get(sid!)).session
          scroll()
        }
        await props.orchestrator?.refreshAnnotations()
        break
      }
      await new Promise(r => setTimeout(r, 2000))
    }
  } catch {
    if (!stopped) showToast('任务状态连接中断，重新打开会话可继续查看。')
  } finally {
    watching.delete(id)
  }
}

function reedit(run: Run) {
  question.value = run.prompt
  attachments.value = (run.attachment_ids || []).map(id => ({ id, url: '/api/workbench/images/' + id, filename: '本轮图片' } as Attachment))
  setContext(run.contexts?.[0] ?? null)
  scheduleDraft()
}

function submit() {
  void ask(question.value, context.value ? [context.value] : []).catch(e => showToast(e instanceof Error ? e.message : '发送失败'))
}

function progressText(run: Run): string {
  const p = run.progress ?? {}
  return (p.tools?.length ? '正在调用 ' + p.tools.join('、') : '') + (p.text ? ' · ' + p.text : '')
}

function renderMd(text: string): string {
  if (window.mdRender) return window.mdRender(text).innerHTML
  return text.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!))
}

const bridge = { ask, watch: watchRun, flushDraft, restoreDraft, setContext, load }
defineExpose({ bridge, attachments, uploadFiles })

watch(() => props.session, s => { if (s) void load(s) }, { immediate: true })
</script>

<template>
  <div class="chat-panel">
    <div class="agent-state muted">{{ agentState }}</div>
    <div ref="chatBox" class="reader-chat">
      <p v-if="!runs.length && !loading" class="muted">选中原文或添加图片，再向当前论文会话提问。</p>
      <article v-for="run in runs" :key="run.id" class="chat-turn">
        <div class="turn-time muted">{{ STATES[run.status] }} · {{ run.created_at }}</div>
        <div class="question">{{ run.prompt }}</div>
        <p v-if="run.status === 'running' && progressText(run)" class="muted">{{ progressText(run) }}</p>
        <img v-for="id in run.attachment_ids" :key="id" class="chat-image" :src="'/api/workbench/images/' + id" alt="本轮提问的图片" />
        <div v-for="(c, i) in run.contexts" :key="i" class="original-context">
          <button @click="orchestrator?.jump(c)">原文 · 论文 {{ c.paper_id }} 第 {{ c.page }} 页</button>
          <div>{{ c.quote }}</div>
        </div>
        <div v-if="run.answer" class="answer" v-html="renderMd(run.answer)"></div>
        <p v-if="run.error" class="error">{{ run.error }}</p>
        <button v-if="run.status === 'failed' || run.status === 'cancelled'" class="reedit" @click="reedit(run)">重新编辑</button>
        <template v-for="(t, i) in run.tool_calls" :key="'t' + i">
          <button v-if="(t.result as any)?.text_source === 'original_pdf_page'" class="tool-source" @click="orchestrator?.jump({ paper_id: (t.result as any).paper_id, page: (t.result as any).page, file_version: '', quote: '', rects: [] })">
            核对原文：第 {{ (t.result as any).page }} 页
          </button>
        </template>
        <p v-if="run.usage && 'input_tokens' in run.usage" class="usage muted">本轮输入 {{ run.usage.input_tokens }} / 输出 {{ run.usage.output_tokens }} tokens{{ (run.metadata as any)?.session_mode === 'native_resume' ? ' · 原生续聊' : '' }}</p>
      </article>
    </div>
    <div v-if="context" class="quote-attachment">
      <button aria-label="移除选区" @click="setContext(null)">×</button>
      <strong>论文 {{ context.paper_id }} · 第 {{ context.page }} 页</strong>
      <p>{{ context.quote }}</p>
    </div>
    <div v-if="attachments.length" class="reader-attachments">
      <div v-for="a in attachments" :key="a.id" class="image-attachment">
        <img :src="a.url" :alt="a.filename || '提问图片'" />
        <button aria-label="移除图片" @click="removeAttachment(a.id)">×</button>
      </div>
    </div>
    <form class="reader-composer" @submit.prevent="submit">
      <div class="composer-tools">
        <select aria-label="提问模板" @change="applyTemplate(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
          <option value="">选择提问模板</option>
          <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }}</option>
        </select>
        <input ref="fileInput" type="file" accept="image/png,image/jpeg" multiple aria-label="上传图片" :disabled="!canSend" @change="onFiles" />
      </div>
      <textarea v-model="question" rows="3" maxlength="3000" placeholder="向当前论文会话提问…" :disabled="busy || !session || session.archived" @input="scheduleDraft"></textarea>
      <button class="primary" type="submit" :disabled="!canSend || !question.trim()">发送</button>
    </form>
    <p v-if="toast" class="chat-toast" role="status">{{ toast }}</p>
  </div>
</template>

<style scoped>
.chat-panel { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.agent-state { padding: var(--space-2) var(--space-3); font-size: 12px; border-bottom: 1px solid var(--border); }
.reader-chat { flex: 1; overflow-y: auto; padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-3); }
.chat-turn { border: 1px solid var(--border); border-radius: var(--radius); padding: var(--space-3); background: var(--bg); display: flex; flex-direction: column; gap: var(--space-2); }
.turn-time { font-size: 11px; }
.question { font-weight: 600; }
.chat-image { max-width: 160px; border-radius: var(--radius); }
.original-context { border-left: 3px solid var(--accent); padding-left: var(--space-2); font-size: 12px; }
.original-context button { border: none; background: none; color: var(--accent); padding: 0; font-size: 12px; }
.answer :deep(p) { margin: var(--space-1) 0; }
.error { color: var(--danger); }
.usage { font-size: 11px; }
.quote-attachment { margin: var(--space-2) var(--space-3); padding: var(--space-2); background: var(--accent-soft); border-radius: var(--radius); font-size: 12px; }
.reader-attachments { display: flex; gap: var(--space-2); padding: 0 var(--space-3); }
.image-attachment { position: relative; }
.image-attachment img { width: 64px; height: 64px; object-fit: cover; border-radius: var(--radius); }
.image-attachment button { position: absolute; top: -6px; right: -6px; padding: 0 6px; border-radius: 50%; }
.reader-composer { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border-top: 1px solid var(--border); }
.composer-tools { display: flex; gap: var(--space-2); align-items: center; }
.composer-tools select { flex: 1; }
.chat-toast { color: var(--danger); padding: 0 var(--space-3); font-size: 12px; }
</style>
