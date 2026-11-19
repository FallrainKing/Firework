<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { agentApi } from '@/api/agent'
import { sessionsApi } from '@/api/sessions'
import { readerApi } from '@/api/reader'
import { workbenchApi } from '@/api/workbench'
import { uid32 } from '@/api/client'
import type { Attachment, Run, SelectionContext, Session, Template } from '@/api/types'

const props = defineProps<{ session: Session | null; paperId: number; paperTitle?: string; orchestrator?: { jump: (ctx: SelectionContext) => void; refreshAnnotations: () => Promise<void> } }>()

const QUICK: Template[] = [
  { id: 'quick_overview', name: '快速概览', description: '', kind: 'reading', skill: 'chat', prompt: '请概述当前论文的研究问题、方法、主要结论与材料覆盖范围。', builtin: 0 },
  { id: 'explain_method', name: '解释方法', description: '', kind: 'reading', skill: 'chat', prompt: '请结合当前论文的原文，逐步解释核心方法与关键公式。', builtin: 0 },
  { id: 'inspect_experiment', name: '检查实验', description: '', kind: 'reading', skill: 'chat', prompt: '请核对当前论文的实验设置、对照方法和结论支持程度，列出证据与疑问。', builtin: 0 },
]

const runs = ref<Run[]>([])
const question = ref('')
const contexts = ref<SelectionContext[]>([])
const attachments = ref<Attachment[]>([])
const templates = ref<Template[]>([])
const associatedPapers = ref<Array<{ id: number; title: string }>>([])
const busy = ref(false)
const uploading = ref(false)
const loading = ref(true)
const loadingOlder = ref(false)
const hasMoreRuns = ref(false)
const nextBefore = ref<number | null>(null)
const atBottom = ref(true)
const newContent = ref(false)
const cancellingRun = ref(false)
const toast = ref('')
const uploadError = ref('')
const failedFiles = ref<File[]>([])
const slashMenuOpen = ref(false)
const mentionMenuOpen = ref(false)
const slashQuery = ref('')
const mentionQuery = ref('')
const dragging = ref(false)
const chatBox = ref<HTMLElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

let epoch = 0
let saveTimer: ReturnType<typeof setTimeout> | null = null
let saveQueue: Promise<unknown> = Promise.resolve()
const watching = new Set<string>()
let stopped = false
onUnmounted(() => { stopped = true })
const currentSession = ref<Session | null>(props.session)

const STATES: Record<string, string> = { queued: '排队', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const canSend = computed(() => !loading.value && !busy.value && !uploading.value && !!currentSession.value && !currentSession.value.archived)
const agentState = computed(() => uploading.value ? '上传图片中…' : busy.value ? '智能体正在执行…' : currentSession.value?.native_ready ? '继续当前原生会话' : '发送后才调用智能体')
const activeRun = computed(() => [...runs.value].reverse().find(run => run.status === 'queued' || run.status === 'running') ?? null)
const visibleTemplates = computed(() => {
  const q = slashQuery.value.trim().toLowerCase()
  return templates.value.filter(t => !q || t.name.toLowerCase().includes(q) || t.prompt.toLowerCase().includes(q)).slice(0, 8)
})
const visiblePapers = computed(() => {
  const q = mentionQuery.value.trim().toLowerCase()
  return associatedPapers.value.filter(p => !q || p.title.toLowerCase().includes(q)).slice(0, 8)
})

function showToast(m: string) { toast.value = m; setTimeout(() => { toast.value = '' }, 5000) }
function scroll() {
  if (!chatBox.value) return
  const el = chatBox.value
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 40
  if (nearBottom) {
    atBottom.value = true
    newContent.value = false
    el.scrollTop = el.scrollHeight
  } else {
    atBottom.value = false
    newContent.value = true
  }
}

function handleScroll() {
  if (!chatBox.value) return
  const el = chatBox.value
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight <= 40
  if (atBottom.value) newContent.value = false
}

function jumpToBottom() {
  if (!chatBox.value) return
  chatBox.value.scrollTop = chatBox.value.scrollHeight
  atBottom.value = true
  newContent.value = false
}
function paperTitle(id: number): string {
  return associatedPapers.value.find(p => p.id === id)?.title ?? (id === props.paperId ? (props.paperTitle || `论文 ${id}`) : `论文 ${id}`)
}

async function loadTemplates() {
  const data = await sessionsApi.templates()
  templates.value = [...data.templates.filter(t => t.skill === currentSession.value?.skill || t.skill === 'chat'), ...QUICK]
}

async function load(session: Session) {
  const e = ++epoch
  currentSession.value = session
  loading.value = true
  busy.value = false
  contexts.value = []
  attachments.value = []
  runs.value = []
  hasMoreRuns.value = false
  nextBefore.value = null
  atBottom.value = true
  newContent.value = false
  closeMenus()
  const [data, draft, detail] = await Promise.all([
    sessionsApi.runs(session.id, undefined, 100),
    workbenchApi.getDraft(session.id, props.paperId),
    sessionsApi.get(session.id),
  ])
  if (e !== epoch) return
  question.value = draft.prompt || (!data.runs.length ? session.draft_prompt : '') || ''
  contexts.value = draft.contexts?.length ? draft.contexts : draft.context ? [draft.context] : []
  attachments.value = draft.attachments ?? []
  associatedPapers.value = detail.papers.map(p => ({ id: p.id, title: p.title }))
  runs.value = data.runs
  hasMoreRuns.value = data.has_more
  nextBefore.value = data.next_before
  for (const r of data.runs) if (['queued', 'running'].includes(r.status)) { busy.value = true; void watchRun(r.id, session.id) }
  loading.value = false
  await loadTemplates()
  scroll()
}

async function restoreDraft() {
  if (loading.value || !currentSession.value) return
  const sid = currentSession.value.id
  const draft = await workbenchApi.getDraft(sid, props.paperId)
  if (currentSession.value?.id !== sid) return
  question.value = draft.prompt
  contexts.value = draft.contexts?.length ? draft.contexts : draft.context ? [draft.context] : []
  attachments.value = draft.attachments ?? []
}

function scheduleDraft() {
  if (loading.value || !currentSession.value) return
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => { void flushDraft().catch(e => showToast('草稿尚未保存：' + (e instanceof Error ? e.message : ''))) }, 400)
}

function flushDraft(): Promise<unknown> {
  if (saveTimer) clearTimeout(saveTimer)
  if (loading.value || !currentSession.value) return saveQueue
  const snapshot = { prompt: question.value, contexts: contexts.value, attachment_ids: attachments.value.map(a => a.id) }
  const sid = currentSession.value.id
  saveQueue = saveQueue.catch(() => {}).then(() => workbenchApi.saveDraft(sid, props.paperId, snapshot))
  return saveQueue
}

function setContext(ctx: SelectionContext | null) {
  if (!ctx) {
    contexts.value = contexts.value.filter(c => !c.quote)
  } else {
    contexts.value = [ctx, ...contexts.value.filter(c => c.paper_id !== ctx.paper_id || !c.quote)].slice(0, 3)
  }
  scheduleDraft()
}

function removeContext(index: number) {
  contexts.value = contexts.value.filter((_, i) => i !== index)
  scheduleDraft()
}

function removeAttachment(id: string) {
  attachments.value = attachments.value.filter(a => a.id !== id)
  scheduleDraft()
}

function validateImageFiles(files: File[]) {
  if (!files.length) return
  if (!currentSession.value) throw new Error('请先选择论文会话')
  if (files.length + attachments.value.length > 3) throw new Error('每次提问最多 3 张图片')
  for (const file of files) {
    if (!['image/png', 'image/jpeg'].includes(file.type)) throw new Error('图片仅支持 PNG 或 JPEG')
    if (file.size > 5 * 1024 * 1024) throw new Error('每张图片不超过 5MB')
    if (file.size === 0) throw new Error('图片文件不能为空')
  }
}

async function uploadFiles(files: File[]) {
  if (!files.length || !currentSession.value) return
  try {
    validateImageFiles(files)
  } catch (e) {
    uploadError.value = e instanceof Error ? e.message : '图片校验失败'
    failedFiles.value = files
    throw e
  }
  const sid = currentSession.value.id
  uploading.value = true
  uploadError.value = ''
  try {
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      form.append('conversation_id', String(sid))
      form.append('paper_id', String(props.paperId))
      const a = await workbenchApi.uploadImage(form)
      if (currentSession.value?.id === sid) {
        attachments.value.push(a)
        await flushDraft()
      } else {
        const old = await workbenchApi.getDraft(sid, props.paperId)
        await workbenchApi.saveDraft(sid, props.paperId, { prompt: old.prompt, contexts: old.contexts ?? (old.context ? [old.context] : []), attachment_ids: [...old.attachment_ids, a.id].slice(0, 3) })
      }
    }
    failedFiles.value = []
  } catch (e) {
    uploadError.value = e instanceof Error ? e.message : '上传失败'
    failedFiles.value = files
    throw e
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function loadOlder() {
  if (!currentSession.value || loadingOlder.value || nextBefore.value === null) return
  const sid = currentSession.value.id
  const before = nextBefore.value
  loadingOlder.value = true
  try {
    const el = chatBox.value
    const previousHeight = el?.scrollHeight ?? 0
    const previousTop = el?.scrollTop ?? 0
    const data = await sessionsApi.runs(sid, before, 50)
    if (currentSession.value?.id !== sid) return
    const existing = new Set(runs.value.map(r => r.id))
    runs.value = [...data.runs.filter(r => !existing.has(r.id)), ...runs.value]
    hasMoreRuns.value = data.has_more
    nextBefore.value = data.next_before
    await nextTick()
    if (el) el.scrollTop = el.scrollHeight - previousHeight + previousTop
  } catch (e) {
    showToast(e instanceof Error ? e.message : '历史载入失败')
  } finally {
    loadingOlder.value = false
  }
}

function elapsedText(run: Run): string {
  const created = Date.parse(run.created_at)
  const finished = run.finished_at ? Date.parse(run.finished_at) : Date.now()
  if (!Number.isFinite(created) || !Number.isFinite(finished) || finished < created) return '未提供'
  const seconds = Math.max(0, Math.round((finished - created) / 1000))
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} 分 ${seconds % 60} 秒`
  return `${Math.floor(minutes / 60)} 时 ${minutes % 60} 分`
}

async function cancelActiveRun() {
  if (!activeRun.value || cancellingRun.value) return
  cancellingRun.value = true
  try {
    const updated = await agentApi.cancelRun(activeRun.value.id)
    upsertRun(updated)
  } catch (e) {
    showToast(e instanceof Error ? e.message : '取消失败')
  } finally {
    cancellingRun.value = false
  }
}

async function copyAnswer(run: Run) {
  try {
    await navigator.clipboard.writeText(run.answer)
    showToast('回答已复制')
  } catch {
    showToast('复制失败')
  }
}

function toolCallName(call: Record<string, unknown>): string {
  return String(call.name ?? call.tool ?? call.type ?? '工具调用')
}

function onFiles() {
  const files = Array.from(fileInput.value?.files ?? [])
  void uploadFiles(files).catch(e => showToast(e instanceof Error ? e.message : '上传失败'))
}

function retryUpload() {
  const files = failedFiles.value
  failedFiles.value = []
  void uploadFiles(files).catch(e => showToast(e instanceof Error ? e.message : '上传失败'))
}

function closeMenus() {
  slashMenuOpen.value = false
  mentionMenuOpen.value = false
}

function updateMenus(event: Event) {
  const target = event.target as HTMLTextAreaElement
  const before = target.value.slice(0, target.selectionStart ?? target.value.length)
  const slash = /\/([^/\n]*)$/.exec(before)
  const mention = /@([^@\n]*)$/.exec(before)
  slashMenuOpen.value = Boolean(slash)
  slashQuery.value = slash?.[1] ?? ''
  mentionMenuOpen.value = Boolean(mention)
  mentionQuery.value = mention?.[1] ?? ''
  if (slashMenuOpen.value) mentionMenuOpen.value = false
  if (mentionMenuOpen.value) slashMenuOpen.value = false
  scheduleDraft()
}

function removeMenuToken(marker: '/' | '@') {
  const pattern = marker === '/' ? /\/[^/\n]*$/ : /@[^@\n]*$/
  question.value = question.value.replace(pattern, '').trimEnd()
}

function chooseTemplate(template: Template) {
  removeMenuToken('/')
  if (template.prompt) question.value = [question.value, template.prompt].filter(Boolean).join('\n\n')
  closeMenus()
  scheduleDraft()
}

async function choosePaper(paper: { id: number; title: string }) {
  removeMenuToken('@')
  if (contexts.value.length >= 3) {
    showToast('上下文最多 3 条，请先移除一条')
    return
  }
  try {
    const doc = await readerApi.document(paper.id)
    if (!contexts.value.some(c => c.paper_id === paper.id && !c.quote)) {
      contexts.value.push({ paper_id: paper.id, page: 1, file_version: doc.file_version, quote: '', rects: [] })
      scheduleDraft()
    }
  } catch (e) {
    showToast((e instanceof Error ? e.message : '论文引用失败') + '；缺全文或未关联论文不能加入上下文')
  } finally {
    closeMenus()
  }
}

function onPaste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files ?? []).filter(f => f.type.startsWith('image/'))
  if (!files.length) return
  event.preventDefault()
  void uploadFiles(files).catch(e => showToast(e instanceof Error ? e.message : '上传失败'))
}

function onDrop(event: DragEvent) {
  dragging.value = false
  const files = Array.from(event.dataTransfer?.files ?? []).filter(f => f.type.startsWith('image/'))
  if (!files.length) return
  void uploadFiles(files).catch(e => showToast(e instanceof Error ? e.message : '上传失败'))
}

function applyTemplate(id: string) {
  const t = templates.value.find(x => x.id === id)
  if (t) chooseTemplate(t)
}

function upsertRun(r: Run) {
  const i = runs.value.findIndex(x => x.id === r.id)
  if (i >= 0) runs.value[i] = r
  else runs.value.push(r)
}

async function ask(prompt: string, selectedContexts: SelectionContext[] = [], purpose = 'chat') {
  if (!prompt.trim() || !currentSession.value) return
  if (busy.value || uploading.value) throw new Error('当前会话仍在处理，请稍候')
  const sid = currentSession.value.id
  const storage = 'reader-pending-' + sid
  const attachment_ids = attachments.value.map(a => a.id)
  let body: Record<string, unknown> | null = null
  try {
    const old = JSON.parse(localStorage.getItem(storage) || 'null')
    body = old && old.prompt === prompt && JSON.stringify(old.contexts) === JSON.stringify(selectedContexts) && JSON.stringify(old.attachment_ids || []) === JSON.stringify(attachment_ids) ? old : null
  } catch { /* ignore */ }
  body = body ?? { conversation_id: sid, prompt, contexts: selectedContexts, purpose, attachment_ids, request_key: uid32() }
  localStorage.setItem(storage, JSON.stringify(body))
  busy.value = true
  try {
    const run = await agentApi.createRun(body as never)
    if (currentSession.value?.id === sid) {
      upsertRun(run)
      question.value = ''
      attachments.value = []
      contexts.value = []
      await flushDraft()
      scroll()
    }
    void watchRun(run.id, sid)
  } catch (e) {
    busy.value = false
    throw e
  }
}

async function watchRun(id: string, sid = currentSession.value?.id) {
  if (watching.has(id)) return
  watching.add(id)
  if (currentSession.value?.id === sid) busy.value = true
  try {
    while (!stopped) {
      const r = await agentApi.getRun(id)
      if (stopped) break
      if (currentSession.value?.id === sid) upsertRun(r)
      if (['succeeded', 'failed', 'cancelled'].includes(r.status)) {
        localStorage.removeItem('reader-pending-' + sid)
        if (currentSession.value?.id === sid) {
          busy.value = false
          const updated = (await sessionsApi.get(sid!)).session
          if (currentSession.value?.id === sid) currentSession.value = updated
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
  contexts.value = run.contexts ?? []
  scheduleDraft()
}

function submit() {
  void ask(question.value, contexts.value).catch(e => showToast(e instanceof Error ? e.message : '发送失败'))
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
    <header class="chat-heading"><div><span class="agent-dot"></span><strong>论文助手</strong><small>当前论文</small></div><p :title="paperTitle">{{ paperTitle || ('论文 ' + paperId) }}</p><slot name="session-controls" /></header>
    <div class="agent-state muted">
      <span>{{ agentState }}</span>
      <template v-if="activeRun">
        <span class="run-meta">{{ STATES[activeRun.status] }} · 已用时 {{ elapsedText(activeRun) }}</span>
        <button class="danger stop-run" type="button" :disabled="cancellingRun" @click="cancelActiveRun">{{ cancellingRun ? '取消中…' : '停止' }}</button>
      </template>
    </div>
    <div ref="chatBox" class="reader-chat" @scroll.passive="handleScroll">
      <button v-if="hasMoreRuns" class="load-older" type="button" :disabled="loadingOlder" @click="loadOlder">{{ loadingOlder ? '正在载入历史…' : '载入更早消息' }}</button>
      <div v-if="!runs.length && !loading" class="chat-empty"><span aria-hidden="true">✧</span><strong>和原文一起思考</strong><p>输入 / 使用模板，输入 @ 引用论文，选中原文或添加图片。</p></div>
      <article v-for="run in runs" :key="run.id" class="chat-turn">
        <div class="turn-time muted">{{ STATES[run.status] }} · {{ run.created_at }}<template v-if="run.status === 'running' || run.status === 'queued'"> · 已用时 {{ elapsedText(run) }}</template></div>
        <div class="question">{{ run.prompt }}</div>
        <p v-if="run.status === 'running' && progressText(run)" class="muted">{{ progressText(run) }}</p>
        <img v-for="id in run.attachment_ids" :key="id" class="chat-image" :src="'/api/workbench/images/' + id" alt="本轮提问的图片" />
        <div v-for="(c, i) in run.contexts" :key="i" class="original-context">
          <button @click="orchestrator?.jump(c)">{{ c.quote ? '原文' : '论文引用' }} · {{ paperTitle(c.paper_id) }} 第 {{ c.page }} 页</button>
          <div v-if="c.quote">{{ c.quote }}</div>
        </div>
        <div v-if="run.answer" class="answer" v-html="renderMd(run.answer)"></div>
        <button v-if="run.answer" class="copy-answer" type="button" @click="copyAnswer(run)">复制回答</button>
        <p v-if="run.error" class="error">{{ run.error }}</p>
        <button v-if="run.status === 'failed' || run.status === 'cancelled'" class="reedit" @click="reedit(run)">重新编辑</button>
        <details v-if="run.tool_calls.length" class="tool-group">
          <summary>工具调用 {{ run.tool_calls.length }} 项（已折叠）</summary>
          <div v-for="(t, i) in run.tool_calls" :key="'t' + i" class="tool-call">
            <button v-if="(t.result as any)?.text_source === 'original_pdf_page'" type="button" @click="orchestrator?.jump({ paper_id: (t.result as any).paper_id, page: (t.result as any).page, file_version: '', quote: '', rects: [] })">
              核对原文：第 {{ (t.result as any).page }} 页
            </button>
            <strong>{{ toolCallName(t) }}</strong>
            <pre>{{ JSON.stringify(t, null, 2) }}</pre>
          </div>
        </details>
        <details class="execution-details">
          <summary>执行详情</summary>
          <dl>
            <div><dt>运行编号</dt><dd>{{ run.id }}</dd></div>
            <div><dt>技能 / 版本</dt><dd>{{ run.skill }} / {{ run.skill_version || '未提供' }}</dd></div>
            <div><dt>模型</dt><dd>{{ run.model || '未提供' }}</dd></div>
            <div><dt>开始 / 结束</dt><dd>{{ run.created_at || '未提供' }} → {{ run.finished_at || '未提供' }}</dd></div>
            <div><dt>费用估算</dt><dd>{{ run.cli_estimated_cost_usd === null ? '未提供' : `$${run.cli_estimated_cost_usd.toFixed(4)}（CLI 估算，非实际账单）` }}</dd></div>
          </dl>
        </details>
        <p v-if="run.usage && 'input_tokens' in run.usage" class="usage muted">本轮输入 {{ run.usage.input_tokens }} / 输出 {{ run.usage.output_tokens }} tokens{{ (run.metadata as any)?.session_mode === 'native_resume' ? ' · 原生续聊' : '' }}</p>
      </article>
    </div>
    <button v-if="newContent" class="new-content" type="button" @click="jumpToBottom">新内容，回到底部</button>
    <div v-if="contexts.length" class="context-bar" aria-label="本次提问上下文">
      <div v-for="(c, i) in contexts" :key="'ctx-' + c.paper_id + '-' + c.page + '-' + i" class="context-chip" :class="{ current: c.paper_id === paperId }">
        <strong>{{ c.paper_id === paperId ? '当前论文' : '引用论文' }}</strong>
        <span>{{ paperTitle(c.paper_id) }}<template v-if="c.quote"> · 第 {{ c.page }} 页原文</template></span>
        <button :aria-label="'移除上下文 ' + paperTitle(c.paper_id)" type="button" @click="removeContext(i)">×</button>
      </div>
    </div>
    <div v-if="attachments.length" class="reader-attachments">
      <div v-for="a in attachments" :key="a.id" class="image-attachment">
        <img :src="a.url" :alt="a.filename || '提问图片'" />
        <button aria-label="移除图片" type="button" @click="removeAttachment(a.id)">×</button>
      </div>
    </div>
    <form class="reader-composer" :class="{ dragging }" @submit.prevent="submit" @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop">
      <div v-if="slashMenuOpen" class="command-menu" role="listbox" aria-label="提问模板">
        <button v-for="t in visibleTemplates" :key="t.id" type="button" role="option" @mousedown.prevent="chooseTemplate(t)">
          <strong>{{ t.name }}</strong><span>{{ t.description || t.prompt }}</span>
        </button>
        <p v-if="!visibleTemplates.length" class="muted">暂无匹配模板</p>
      </div>
      <div v-if="mentionMenuOpen" class="command-menu" role="listbox" aria-label="论文引用">
        <button v-for="p in visiblePapers" :key="p.id" type="button" role="option" @mousedown.prevent="choosePaper(p)">
          <strong>{{ p.title }}</strong><span>已授权当前会话</span>
        </button>
        <p v-if="!visiblePapers.length" class="muted">当前会话没有匹配论文</p>
      </div>
      <div class="composer-tools">
        <button type="button" class="menu-toggle" @click="slashMenuOpen = !slashMenuOpen; mentionMenuOpen = false">/ 模板</button>
        <button type="button" class="menu-toggle" @click="mentionMenuOpen = !mentionMenuOpen; slashMenuOpen = false">@ 论文</button>
        <button type="button" class="image-picker" :disabled="!currentSession || currentSession.archived" @click="fileInput?.click()">＋ 图片</button><input ref="fileInput" class="sr-only" type="file" accept="image/png,image/jpeg" multiple aria-label="上传图片" :disabled="!currentSession || currentSession.archived" @change="onFiles" />
      </div>
      <textarea v-model="question" rows="3" maxlength="3000" placeholder="输入 / 选模板，@ 引用论文，也可拖入或粘贴图片…" :disabled="!currentSession || currentSession.archived" @input="updateMenus" @keydown.esc="closeMenus" @paste="onPaste"></textarea>
      <p v-if="uploadError" class="form-error upload-error" role="alert">{{ uploadError }}<button v-if="failedFiles.length" type="button" @click="retryUpload">重试</button></p>
      <div class="composer-footer"><span class="muted">上下文最多 3 条 · 图片最多 3 张 · 图片需 PNG/JPEG</span><button class="primary" type="submit" :disabled="!canSend || !question.trim()">发送 ↑</button></div>
    </form>
    <p v-if="toast" class="chat-toast" role="status">{{ toast }}</p>
  </div>
</template>

<style scoped>
.chat-heading { padding:16px 16px 12px; border-bottom:1px solid var(--border); }
.chat-heading > div { display:flex; gap:8px; align-items:center; }
.chat-heading strong { font-size:13px; }
.chat-heading small { margin-left:auto; font-size:10px; color:var(--text-muted); }
.chat-heading p { font-size:11px; margin:7px 0 12px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.agent-dot { width:7px; height:7px; background:var(--accent); border-radius:50%; }
.chat-empty { margin:auto 0; padding:32px 8px; text-align:center; color:var(--text-muted); font-size:12px; }
.chat-empty > span { display:block; color:var(--accent); font-size:32px; margin-bottom:12px; }
.chat-empty strong { font-size:14px; font-weight:500; color:var(--text); }
.chat-empty p { line-height:1.9; }
.composer-footer { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.composer-footer span { font-size:10px; }
.composer-footer button { padding:6px 14px; font-size:12px; }
.reader-composer textarea { width:100%; resize:vertical; min-height:88px; max-height:220px; font-size:13px; }
.chat-panel { position:relative; display: flex; flex-direction: column; height: 100%; min-height: 0; min-width:0; }
.agent-state { padding: var(--space-2) var(--space-3); font-size: 12px; border-bottom: 1px solid var(--border); }
.reader-chat { flex: 1; min-height:0; overflow-wrap:anywhere; overflow-y: auto; padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-3); }
.chat-turn { border: 1px solid var(--border); border-radius: var(--radius); padding: var(--space-3); background: var(--bg); display: flex; flex-direction: column; gap: var(--space-2); }
.turn-time { font-size: 11px; }
.question { font-weight: 600; }
.chat-image { max-width: 160px; border-radius: var(--radius); }
.original-context { border-left: 3px solid var(--accent); padding-left: var(--space-2); font-size: 12px; }
.original-context button { border: none; background: none; color: var(--accent); padding: 0; font-size: 12px; }
.answer :deep(p) { margin: var(--space-1) 0; }
.error { color: var(--danger); }
.usage { font-size: 11px; }
.context-bar { display:flex; flex-wrap:wrap; gap:var(--space-1); padding:var(--space-2) var(--space-3) 0; }
.context-chip { display:flex; align-items:center; gap:5px; max-width:100%; padding:4px 6px; border:1px solid var(--border); border-radius:999px; background:var(--bg); font-size:11px; }
.context-chip.current { border-color:var(--accent); background:var(--accent-soft); }
.context-chip span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.context-chip button { border:0; background:none; padding:0 2px; color:var(--text-muted); }
.reader-attachments { display: flex; gap: var(--space-2); padding: var(--space-2) var(--space-3) 0; }
.image-attachment { position: relative; }
.image-attachment img { width: 64px; height: 64px; object-fit: cover; border-radius: var(--radius); }
.image-attachment button { position: absolute; top: -6px; right: -6px; padding: 0 6px; border-radius: 50%; }
.reader-composer { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border-top: 1px solid var(--border); position:relative; }
.reader-composer.dragging::after { content:'松开以上传图片'; position:absolute; inset:4px; display:grid; place-items:center; border:1px dashed var(--accent); border-radius:var(--radius); background:rgb(255 255 255 / .82); color:var(--accent); font-size:12px; pointer-events:none; }
.composer-tools { display: flex; gap: var(--space-2); align-items: center; }
.composer-tools select { flex: 1; min-width:0; font-size:11px; padding:6px; }
.menu-toggle,.image-picker { font-size:11px; padding:6px 8px; }
.image-picker { flex-shrink:0; }
.command-menu { position:absolute; left:var(--space-3); right:var(--space-3); bottom:145px; z-index:8; max-height:230px; overflow-y:auto; padding:4px; border:1px solid var(--border); border-radius:var(--radius); background:var(--surface); box-shadow:0 8px 24px rgb(0 0 0 / .12); }
.command-menu button { display:grid; gap:2px; width:100%; padding:7px; border:0; background:none; text-align:left; }
.command-menu button:hover { background:var(--accent-soft); }
.command-menu strong { font-size:12px; }
.command-menu span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:10px; color:var(--text-muted); }
.upload-error { display:flex; align-items:center; gap:6px; margin:0; font-size:11px; }
.upload-error button { padding:2px 6px; font-size:10px; }
.chat-toast { color: var(--danger); padding: 0 var(--space-3); font-size: 12px; }
.agent-state { display:flex; align-items:center; gap:8px; }
.run-meta { margin-left:auto; }
.stop-run { padding:3px 8px; font-size:10px; flex-shrink:0; }
.load-older { align-self:center; font-size:11px; padding:5px 10px; }
.tool-group,.execution-details { border-top:1px dashed var(--border); padding-top:var(--space-2); font-size:11px; }
.tool-group summary,.execution-details summary { cursor:pointer; color:var(--text-muted); }
.tool-call { display:grid; gap:4px; padding:var(--space-2) 0; }
.tool-call pre { max-height:180px; overflow:auto; margin:0; padding:var(--space-2); border-radius:var(--radius); background:var(--surface); font-size:10px; }
.execution-details dl { display:grid; gap:4px; margin:var(--space-2) 0 0; }
.execution-details div { display:grid; grid-template-columns:90px 1fr; gap:var(--space-2); }
.execution-details dt { color:var(--text-muted); }
.execution-details dd { margin:0; min-width:0; overflow-wrap:anywhere; }
.copy-answer { align-self:flex-start; font-size:10px; padding:3px 7px; }
.new-content { position:absolute; right:var(--space-4); bottom:205px; z-index:7; padding:5px 10px; font-size:11px; border-color:var(--accent); color:var(--accent); background:var(--surface); box-shadow:0 5px 16px rgb(0 0 0 / .12); }
.answer :deep(table) { display:block; max-width:100%; overflow-x:auto; }
.answer :deep(img) { max-width:100%; height:auto; }
@media(max-width:700px) { .command-menu { bottom:150px; } }
</style>
