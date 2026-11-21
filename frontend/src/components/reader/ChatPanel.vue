<script setup lang="ts">
import { renderMarkdown } from '@/shared/markdown'
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { agentApi } from '@/api/agent'
import { sessionsApi } from '@/api/sessions'
import { readerApi } from '@/api/reader'
import { workbenchApi } from '@/api/workbench'
import { uid32 } from '@/api/client'
import { useWorkbenchStore } from '@/stores/workbench'
import type { Attachment, Run, SelectionContext, Session, SessionUsage, Template } from '@/api/types'
import RunConnectionControl from './RunConnectionControl.vue'
import type {ConnectionRef} from '@/api/runnerConnections'
import RunBudgetControl from './RunBudgetControl.vue'
import type {BudgetRef} from '@/api/runnerBudgets'
import StateFeedback from '@/components/StateFeedback.vue'

const props = defineProps<{ session: Session | null; paperId: number; paperTitle?: string; orchestrator?: { jump: (ctx: SelectionContext) => void; refreshAnnotations: () => Promise<void> } }>()
const wb = useWorkbenchStore()

const QUICK: Template[] = [
  { id: 'quick_overview', name: '快速概览', description: '', kind: 'reading', skill: 'chat', prompt: '请概述当前论文的研究问题、方法、主要结论与材料覆盖范围。', builtin: 0 },
  { id: 'explain_method', name: '解释方法', description: '', kind: 'reading', skill: 'chat', prompt: '请结合当前论文的原文，逐步解释核心方法与关键公式。', builtin: 0 },
  { id: 'inspect_experiment', name: '检查实验', description: '', kind: 'reading', skill: 'chat', prompt: '请核对当前论文的实验设置、对照方法和结论支持程度，列出证据与疑问。', builtin: 0 },
]

const runs = ref<Run[]>([])
const question = ref('')
const selectedBudget=ref<BudgetRef|null>(null)
const selectedConnection=ref<ConnectionRef|null>(null)
watch(()=>props.session?.id,()=>{selectedBudget.value=null;selectedConnection.value=null})
const contexts = ref<SelectionContext[]>([])
const attachments = ref<Attachment[]>([])
const templates = ref<Template[]>([])
const associatedPapers = ref<Array<{ id: number; title: string }>>([])
const sessionUsage = ref<SessionUsage | null>(null)
const detailsOpen = ref(false)
const resultsOnly = ref(false)
const busy = ref(false)
const uploading = ref(false)
const loading = ref(true)
const loadError = ref<string | null>(null)
const loadingOlder = ref(false)
const hasMoreRuns = ref(false)
const nextBefore = ref<number | null>(null)
const atBottom = ref(true)
const newContent = ref(false)
const cancellingRun = ref(false)
const toast = ref('')
const exportError = ref<string | null>(null)
const exporting = ref(false)
const draftSaving = ref(false)
const draftSaved = ref(false)
const draftSaveError = ref<string | null>(null)
const uploadError = ref('')
const failedFiles = ref<File[]>([])
const slashMenuOpen = ref(false)
const mentionMenuOpen = ref(false)
const slashQuery = ref('')
const mentionQuery = ref('')
const dragging = ref(false)
const chatBox = ref<HTMLElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const questionInput = ref<HTMLTextAreaElement | null>(null)
const composing = ref(false)
const menuIndex = ref(0)

function resizeInput() {
  const input = questionInput.value
  if (!input) return
  input.style.height = 'auto'
  input.style.height = `${Math.min(220, Math.max(88, input.scrollHeight))}px`
}
watch(question, () => { void nextTick(resizeInput) })
watch([slashMenuOpen, mentionMenuOpen, slashQuery, mentionQuery], () => { menuIndex.value = 0 })
watch(slashMenuOpen, open => {
  if (open) void nextTick(() => {
    const extras = questionInput.value?.closest('.chat-panel')?.querySelector('.composer-extras')
    if (extras) extras.scrollTop = 0
  })
})

function focusInput() { void nextTick(() => questionInput.value?.focus()) }

function onComposerKeydown(event: KeyboardEvent) {
  // Enter confirms a Chinese/Japanese IME candidate without sending a message.
  if (event.isComposing || composing.value || event.keyCode === 229) return
  if (event.key === 'Escape') { closeMenus(); event.preventDefault(); return }
  const menuOpen = slashMenuOpen.value || mentionMenuOpen.value
  const count = slashMenuOpen.value ? visibleTemplates.value.length : visiblePapers.value.length
  if (menuOpen && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
    event.preventDefault()
    if (count) menuIndex.value = (menuIndex.value + (event.key === 'ArrowDown' ? 1 : -1) + count) % count
    void nextTick(() => questionInput.value?.closest('.chat-panel')?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: 'nearest' }))
    return
  }
  if (event.key !== 'Enter' || event.shiftKey || event.altKey || event.repeat) return
  event.preventDefault()
  if (menuOpen && !event.ctrlKey && !event.metaKey) {
    if (slashMenuOpen.value) {
      const template = visibleTemplates.value[menuIndex.value]
      if (template) chooseTemplate(template)
    } else {
      const paper = visiblePapers.value[menuIndex.value]
      if (paper) void choosePaper(paper)
    }
    return
  }
  submit()
}

let epoch = 0
let saveTimer: ReturnType<typeof setTimeout> | null = null
let saveQueue: Promise<unknown> = Promise.resolve()
const watching = new Set<string>()
let stopped = false
onUnmounted(() => { stopped = true })
const currentSession = ref<Session | null>(props.session)

const STATES: Record<string, string> = { queued: '排队', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const canSend = computed(() => !loading.value && !loadError.value && !busy.value && !uploading.value && !!currentSession.value && !currentSession.value.archived)
const agentState = computed(() => uploading.value ? '上传图片中…' : busy.value ? '智能体正在执行…' : currentSession.value?.native_ready ? '继续当前原生会话' : '发送后才调用智能体')
const activeRun = computed(() => [...runs.value].reverse().find(run => run.status === 'queued' || run.status === 'running') ?? null)
const latestRun = computed(() => runs.value.at(-1) ?? null)
const runStatus = computed(() => activeRun.value ? STATES[activeRun.value.status] : latestRun.value ? STATES[latestRun.value.status] : '暂无运行')
const sessionModel = computed(() => latestRun.value?.model || null)
watch([() => props.paperId, question, contexts, attachments, activeRun], () => {
  wb.setTabStatus(props.paperId, {
    draft: Boolean(question.value.trim() || contexts.value.length || attachments.value.length),
    failed: runs.value.some(run => run.status === 'failed'),
    running: activeRun.value !== null,
  })
}, { deep: true })
const visibleTemplates = computed(() => {
  const q = slashQuery.value.trim().toLowerCase()
  return templates.value.filter(t => !q || t.name.toLowerCase().includes(q) || t.prompt.toLowerCase().includes(q)).slice(0, 8)
})
const visiblePapers = computed(() => {
  const q = mentionQuery.value.trim().toLowerCase()
  return associatedPapers.value.filter(p => !q || p.title.toLowerCase().includes(q)).slice(0, 8)
})

function showToast(m: string) { toast.value = m; setTimeout(() => { toast.value = '' }, 5000) }
// Track intent before DOM growth: a long answer must not disable following.
function followLatest(markNew = false) {
  const sid = currentSession.value?.id
  void nextTick(() => {
    if (stopped || sid !== currentSession.value?.id || !chatBox.value) return
    if (atBottom.value) jumpToBottom()
    else if (markNew) newContent.value = true
  })
}
function scroll() { followLatest(true) }
let viewportObserver: ResizeObserver | null = null
watch(chatBox, el => {
  viewportObserver?.disconnect()
  if (el && typeof ResizeObserver !== 'undefined') {
    viewportObserver = new ResizeObserver(() => followLatest())
    viewportObserver.observe(el)
  }
})
onUnmounted(() => viewportObserver?.disconnect())
watch(
  () => JSON.stringify(runs.value.map(({ id, status, answer, progress }) => ({ id, status, answer, progress }))),
  () => { if (!loadingOlder.value) scroll() },
  { flush: 'post' },
)
watch(detailsOpen, open => {
  if (open) void nextTick(() => {
    if (chatBox.value) { chatBox.value.scrollTop = 0; handleScroll() }
  })
})

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
function numberOrMissing(value: number | null | undefined): string {
  return value === null || value === undefined ? '未提供' : String(value)
}

function usageText(usage: Record<string, number> | null | undefined): string {
  const input = usage && 'input_tokens' in usage ? usage.input_tokens : null
  const output = usage && 'output_tokens' in usage ? usage.output_tokens : null
  return `输入 ${numberOrMissing(input)} / 输出 ${numberOrMissing(output)}`
}

function sessionUsageText(usage: SessionUsage | null): string {
  if (!usage || !usage.runs_with_usage) return '未提供'
  const input = usage.runs_with_input_tokens ? usage.input_tokens : null
  const output = usage.runs_with_output_tokens ? usage.output_tokens : null
  return `输入 ${numberOrMissing(input)} / 输出 ${numberOrMissing(output)}`
}

function costText(cost: number | null | undefined): string {
  return cost === null || cost === undefined ? '未提供' : `$${cost.toFixed(4)}（CLI 估算，非实际账单）`
}

function resolvePaperTitle(id: number): string {
  return associatedPapers.value.find(p => p.id === id)?.title ?? (id === props.paperId ? (props.paperTitle || `论文 ${id}`) : `论文 ${id}`)
}

async function loadTemplates() {
  const data = await sessionsApi.templates()
  templates.value = [...data.templates.filter(t => t.skill === currentSession.value?.skill || t.skill === 'chat'), ...QUICK]
}

async function load(session: Session) {
  const requestEpoch = ++epoch
  currentSession.value = session
  loading.value = true
  loadError.value = null
  busy.value = false
  contexts.value = []
  attachments.value = []
  runs.value = []
  hasMoreRuns.value = false
  nextBefore.value = null
  atBottom.value = true
  newContent.value = false
  closeMenus()
  try {
    const [data, draft, detail] = await Promise.all([
      sessionsApi.runs(session.id, undefined, 100),
      workbenchApi.getDraft(session.id, props.paperId),
      sessionsApi.get(session.id),
    ])
    if (requestEpoch !== epoch) return
    question.value = draft.prompt || (!data.runs.length ? session.draft_prompt : '') || ''
    contexts.value = draft.contexts?.length ? draft.contexts : draft.context ? [draft.context] : []
    attachments.value = draft.attachments ?? []
    associatedPapers.value = detail.papers.map(p => ({ id: p.id, title: p.title }))
    sessionUsage.value = detail.usage ?? null
    runs.value = data.runs
    hasMoreRuns.value = data.has_more
    nextBefore.value = data.next_before
    for (const r of data.runs) if (['queued', 'running'].includes(r.status)) { busy.value = true; void watchRun(r.id, session.id) }
    await loadTemplates()
    scroll()
  } catch (err) {
    if (requestEpoch === epoch) loadError.value = err instanceof Error ? err.message : '会话载入失败'
  } finally {
    if (requestEpoch === epoch) loading.value = false
  }
}

function retryLoad() {
  if (currentSession.value) void load(currentSession.value)
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
  draftSaved.value = false
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => { void flushDraft().catch(e => showToast('草稿尚未保存：' + (e instanceof Error ? e.message : ''))) }, 400)
}

function flushDraft(): Promise<unknown> {
  if (saveTimer) clearTimeout(saveTimer)
  if (loading.value || !currentSession.value) return saveQueue
  const snapshot = { prompt: question.value, contexts: contexts.value, attachment_ids: attachments.value.map(a => a.id) }
  const sid = currentSession.value.id
  draftSaving.value = true
  draftSaved.value = false
  draftSaveError.value = null
  saveQueue = saveQueue.catch(() => {}).then(() => workbenchApi.saveDraft(sid, props.paperId, snapshot))
    .then(() => {
      if (currentSession.value?.id === sid) draftSaved.value = true
      return null
    })
    .catch(e => {
      if (currentSession.value?.id === sid) draftSaveError.value = e instanceof Error ? e.message : '草稿保存失败'
      throw e
    })
    .finally(() => {
      if (currentSession.value?.id === sid) draftSaving.value = false
    })
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
  loadError.value = null
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
    loadError.value = e instanceof Error ? e.message : '历史载入失败'
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
  focusInput()
  scheduleDraft()
}

function closeTaskPicker() {
  removeMenuToken('/')
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
  const sentDraft = JSON.stringify({ prompt: question.value, contexts: contexts.value, attachments: attachment_ids })
  let body: Record<string, unknown> | null = null
  try {
    const old = JSON.parse(localStorage.getItem(storage) || 'null')
    body = old && JSON.stringify(old.connection??null)===JSON.stringify(selectedConnection.value) && JSON.stringify(old.budget??null)===JSON.stringify(selectedBudget.value) && old.prompt === prompt && JSON.stringify(old.contexts) === JSON.stringify(selectedContexts) && JSON.stringify(old.attachment_ids || []) === JSON.stringify(attachment_ids) ? old : null
  } catch { /* ignore */ }
  body = body ?? { conversation_id: sid, prompt, contexts: selectedContexts, purpose, attachment_ids, ...(selectedConnection.value?{connection:selectedConnection.value}:{}), ...(selectedBudget.value?{budget:selectedBudget.value}:{}), request_key: uid32() }
  localStorage.setItem(storage, JSON.stringify(body))
  busy.value = true
  try {
    const run = await agentApi.createRun(body as never)
    if (currentSession.value?.id === sid) {
      upsertRun(run)
      // Only clear the snapshot submitted; edits made during the request stay in the draft.
      if (sentDraft === JSON.stringify({ prompt: question.value, contexts: contexts.value, attachments: attachments.value.map(a => a.id) })) {
        question.value = ''
        attachments.value = []
        contexts.value = []
      }
      closeMenus()
      focusInput()
      void flushDraft().catch(e => showToast('消息已发送，草稿保存失败：' + (e instanceof Error ? e.message : '')))
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
          const detail = await sessionsApi.get(sid!)
          if (currentSession.value?.id === sid) {
            currentSession.value = detail.session
            sessionUsage.value = detail.usage
          }
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
  if (!canSend.value || !question.value.trim()) return
  closeMenus()
  void ask(question.value, contexts.value).catch(e => showToast(e instanceof Error ? e.message : '发送失败'))
}

function progressText(run: Run): string {
  const p = run.progress ?? {}
  return (p.tools?.length ? '正在调用 ' + p.tools.join('、') : '') + (p.text ? ' · ' + p.text : '')
}

function renderMd(text: string): string { return renderMarkdown(text) }

async function allRunsForExport(): Promise<Run[]> {
  const sid = currentSession.value?.id
  if (sid === undefined) return []
  let all = [...runs.value]
  let before = nextBefore.value
  let more = hasMoreRuns.value
  const seen = new Set(all.map(run => run.id))
  while (more && before !== null) {
    const data = await sessionsApi.runs(sid, before, 50)
    const older = data.runs.filter(run => !seen.has(run.id))
    older.forEach(run => seen.add(run.id))
    all = [...older, ...all]
    before = data.next_before
    more = data.has_more
  }
  return all
}

function buildMarkdown(exportRuns: Run[]): string {
  const sessionValue = currentSession.value
  const papers = associatedPapers.value.length ? associatedPapers.value : (sessionValue?.paper_ids.length ? sessionValue.paper_ids.map(id => ({ id, title: resolvePaperTitle(id) })) : [{ id: props.paperId, title: props.paperTitle || `论文 ${props.paperId}` }])
  const lines: string[] = [
    '# 研究会话导出',
    '',
    `- 会话名：${sessionValue?.title ?? '未提供'}`,
    `- 平台会话 ID：${sessionValue?.id ?? '未提供'}`,
    `- 原生会话 ID：${sessionValue?.native_session_id || '未提供'}`,
    `- 任务类型 / 技能：${sessionValue?.kind ?? '未提供'} / ${sessionValue?.skill ?? '未提供'}`,
    `- 导出时间：${new Date().toISOString()}`,
    '',
    '> 本文件是聊天成果快照，导出动作不会写入长期记忆。',
    '',
    '## 论文',
  ]
  for (const paper of papers) lines.push(`- [P${paper.id}] ${paper.title}（paper_id=${paper.id}）`)
  lines.push('', '## 运行记录')
  if (!exportRuns.length) lines.push('未提供。')
  for (const run of exportRuns) {
    lines.push(
      '',
      '### 用户提问',
      run.prompt,
      '',
      `- 运行编号：${run.id}`,
      `- 状态：${STATES[run.status] ?? run.status}`,
      `- 创建时间：${run.created_at || '未提供'}`,
      `- 模型：${run.model || '未提供'}`,
      `- 附件 ID：${run.attachment_ids.length ? run.attachment_ids.join('、') : '未提供'}`,
    )
    lines.push('', '#### 上下文')
    if (!run.contexts.length) lines.push('- 未提供')
    for (const context of run.contexts) {
      lines.push(
        `- 论文：[P${context.paper_id}] ${resolvePaperTitle(context.paper_id)}（paper_id=${context.paper_id}）`,
        `  - 物理页：${context.page}`,
        `  - 文件版本锚点：\`${context.file_version || '未提供'}\``,
      )
    }
    lines.push('', '#### 回答')
    if (run.answer) lines.push(run.answer)
    if (run.error) lines.push(`错误：${run.error}`)
    if (!run.answer && !run.error) lines.push('未提供。')
  }
  return lines.join('\n') + '\n'
}

function downloadMarkdown(markdown: string) {
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  const name = (currentSession.value?.title || `session-${currentSession.value?.id ?? 'export'}`).replace(/[\\/:*?"<>|]/g, '_').slice(0, 80)
  link.href = url
  link.download = `${name || 'session'}.md`
  link.rel = 'noopener'
  link.click()
  URL.revokeObjectURL(url)
}

async function exportMarkdown() {
  if (!currentSession.value || exporting.value) return
  exporting.value = true
  exportError.value = null
  try {
    downloadMarkdown(buildMarkdown(await allRunsForExport()))
  } catch (e) {
    exportError.value = e instanceof Error ? e.message : '导出失败'
  } finally {
    exporting.value = false
  }
}

const bridge = { ask, watch: watchRun, flushDraft, restoreDraft, setContext, load }
defineExpose({ bridge, attachments, uploadFiles, exportMarkdown, buildMarkdown, allRunsForExport })
watch(() => props.session, s => { if (s) void load(s) }, { immediate: true })
</script>

<template>
  <div class="chat-panel">
    <header class="chat-heading">
      <div class="session-summary">
        <div class="session-title">
          <span class="agent-dot" :class="{ running: activeRun, failed: latestRun?.status === 'failed' }"></span>
          <div class="session-text">
            <strong :title="props.paperTitle || ('论文 ' + paperId)">{{ props.paperTitle || ('论文 ' + paperId) }}</strong>
            <small><span :title="currentSession?.title">{{ currentSession?.title || '未选择会话' }}</span> · {{ currentSession?.skill || '未提供' }} · {{ runStatus }}</small>
          </div>
        </div>
        <slot name="session-controls" />
        <button class="export-chat" type="button" :disabled="loading || exporting" title="导出 Markdown 快照；不会写入长期记忆" @click="exportMarkdown">{{ exporting ? '导出中…' : '导出 MD' }}</button>
        <button class="detail-toggle" type="button" :aria-expanded="detailsOpen" @click="detailsOpen = !detailsOpen">详情</button>
      </div>
      <div class="usage-summary" aria-label="会话用量">
        <span>本轮 tokens：{{ usageText(latestRun?.usage) }}</span>
        <span>会话累计 tokens：{{ sessionUsageText(sessionUsage) }}</span>
        <span>费用估算：{{ costText(sessionUsage?.cli_estimated_cost_usd ?? latestRun?.cli_estimated_cost_usd) }}</span>
      </div>
    </header>
    <div class="agent-state muted">
      <span>{{ agentState }}</span>
      <template v-if="activeRun">
        <span class="run-meta">{{ STATES[activeRun.status] }} · 已用时 {{ elapsedText(activeRun) }}</span>
        <button class="danger stop-run" type="button" :disabled="cancellingRun" @click="cancelActiveRun">{{ cancellingRun ? '取消中…' : '停止' }}</button>
      </template>
    </div>
    <nav class="conversation-modes" aria-label="会话显示方式">
      <button type="button" :aria-pressed="!resultsOnly" @click="resultsOnly = false">完整会话</button>
      <button type="button" :aria-pressed="resultsOnly" @click="resultsOnly = true">阅读结果</button>
      <button type="button" class="latest-message" @click="jumpToBottom">↓ 最新</button>
    </nav>
    <div class="conversation-view">
    <div ref="chatBox" class="reader-chat" role="region" aria-label="智能体回答与会话记录" tabindex="0" @scroll.passive="handleScroll" @load.capture="followLatest()">
    <section v-if="detailsOpen" class="session-details" aria-label="会话详情">
      <dl>
        <div><dt>平台会话 ID</dt><dd>{{ currentSession?.id ?? '未提供' }}</dd></div>
        <div><dt>原生会话 ID</dt><dd>{{ currentSession?.native_session_id || '未提供' }}</dd></div>
        <div v-if="latestRun?.diagnostics?.connection_snapshot"><dt>连接 / 版本</dt><dd>{{ latestRun?.diagnostics.connection_snapshot.name || '管理员原有连接' }} · {{ latestRun?.diagnostics.connection_snapshot.revision || '原配置' }}</dd></div>
            <div><dt>模型</dt><dd>{{ sessionModel || '未提供' }}</dd></div>
        <div><dt>运行状态</dt><dd>{{ runStatus }}</dd></div>
      </dl>
      <h4>运行记录</h4>
      <StateFeedback v-if="!runs.length" empty empty-text="未提供。" />
      <div v-for="run in [...runs].reverse()" :key="'record-' + run.id" class="run-record">
        <strong>{{ run.id }}</strong>
        <span>{{ STATES[run.status] }} · {{ run.created_at || '未提供' }}</span>
        <span>{{ run.model || '未提供' }} · {{ usageText(run.usage) }}</span>
        <span>{{ costText(run.cli_estimated_cost_usd) }}</span>
      </div>
      <h4>附件详情</h4>
      <StateFeedback v-if="!attachments.length && !runs.some(run => run.attachment_ids.length)" empty empty-text="未提供。" />
      <div v-for="a in attachments" :key="'attachment-' + a.id" class="run-record">
        <strong>{{ a.filename || '未命名附件' }}</strong>
        <span>{{ a.mime || '未提供' }} · {{ a.size || 0 }} bytes</span>
        <span>当前草稿</span>
      </div>
      <div v-for="run in runs.filter(r => r.attachment_ids.length)" :key="'run-attachments-' + run.id" class="run-record">
        <strong>运行 {{ run.id }}</strong>
        <span>附件：{{ run.attachment_ids.join('、') }}</span>
      </div>
    </section>

      <button v-if="hasMoreRuns" class="load-older" type="button" :disabled="loadingOlder" @click="loadOlder">{{ loadingOlder ? '正在载入历史…' : '载入更早消息' }}</button>
      <StateFeedback
        class="chat-state"
        :loading="loading"
        :error="loadError"
        :empty="!loading && !loadError && !runs.length"
        empty-text="输入 / 使用模板，输入 @ 引用论文，选中原文或添加图片。"
        @retry="retryLoad"
      />
      <article v-for="run in runs" :key="run.id" class="chat-turn">
        <div class="turn-time muted">{{ STATES[run.status] }} · {{ run.created_at }}<template v-if="run.status === 'running' || run.status === 'queued'"> · 已用时 {{ elapsedText(run) }}</template></div>
        <div class="turn-role">你</div>
        <div class="question">{{ run.prompt }}</div>
        <p v-if="run.status === 'running' && progressText(run)" class="muted">{{ progressText(run) }}</p>
        <img v-for="id in run.attachment_ids" :key="id" class="chat-image" :src="'/api/workbench/images/' + id" alt="本轮提问的图片" />
        <div v-for="(c, i) in run.contexts" :key="i" class="original-context">
          <button @click="orchestrator?.jump(c)">{{ c.quote ? '原文' : '论文引用' }} · {{ resolvePaperTitle(c.paper_id) }} 第 {{ c.page }} 页</button>
          <div v-if="c.quote">{{ c.quote }}</div>
        </div>
        <div v-if="run.answer" class="turn-role assistant-role">智能体 <span v-if="run.model">· {{ run.model }}</span></div>
        <div v-if="run.answer" class="answer markdown-content" v-html="renderMd(run.answer)"></div>
        <button v-if="run.answer" class="copy-answer" type="button" @click="copyAnswer(run)">复制回答</button>
        <p v-if="run.error" class="error">{{ run.diagnostics?.message || run.error }}</p>
        <p v-if="run.diagnostics?.partial_available" class="muted">以下为中断前的部分输出，尚未完成。调整额度后可重新编辑并手动发送。</p>
        <button v-if="run.status === 'failed' || run.status === 'cancelled'" class="reedit" @click="reedit(run)">重新编辑</button>
        <details v-if="!resultsOnly && run.tool_calls.length" class="tool-group">
          <summary>执行过程 · {{ run.tool_calls.length }} 次工具调用 · {{ elapsedText(run) }}</summary>
          <div v-for="(t, i) in run.tool_calls" :key="'t' + i" class="tool-call">
            <button v-if="(t.result as any)?.text_source === 'original_pdf_page'" type="button" @click="orchestrator?.jump({ paper_id: (t.result as any).paper_id, page: (t.result as any).page, file_version: '', quote: '', rects: [] })">
              核对原文：第 {{ (t.result as any).page }} 页
            </button>
            <strong>{{ toolCallName(t) }}</strong>
            <pre>{{ JSON.stringify(t, null, 2) }}</pre>
          </div>
        </details>
        <details v-if="!resultsOnly" class="execution-details">
          <summary>执行详情</summary>
          <dl>
            <div v-if="run.diagnostics"><dt>结束原因</dt><dd>{{ run.diagnostics.finish_reason }} · {{ run.diagnostics.subtype || '无原始子类型' }}</dd></div>
            <div v-if="run.diagnostics"><dt>任务额度快照</dt><dd>{{ run.diagnostics.budget_snapshot?.name || 'Skill 原有额度' }} · {{ JSON.stringify(run.diagnostics.effective_budget) }} <a href="/#/settings/runner/budgets">管理</a></dd></div>
            <div><dt>运行编号</dt><dd>{{ run.id }}</dd></div>
            <div><dt>技能 / 版本</dt><dd>{{ run.skill }} / {{ run.skill_version || '未提供' }}</dd></div>
            <div v-if="run.diagnostics?.connection_snapshot"><dt>连接 / 版本</dt><dd>{{ run.diagnostics.connection_snapshot.name || '管理员原有连接' }} · {{ run.diagnostics.connection_snapshot.revision || '原配置' }}</dd></div>
            <div><dt>模型</dt><dd>{{ run.model || '未提供' }}</dd></div>
            <div><dt>开始 / 结束</dt><dd>{{ run.created_at || '未提供' }} → {{ run.finished_at || '未提供' }}</dd></div>
            <div><dt>费用估算</dt><dd>{{ run.cli_estimated_cost_usd === null ? '未提供' : `$${run.cli_estimated_cost_usd.toFixed(4)}（CLI 估算，非实际账单）` }}</dd></div>
          </dl>
        </details>
        <p v-if="!resultsOnly && run.usage && 'input_tokens' in run.usage" class="usage muted">本轮输入 {{ run.usage.input_tokens }} / 输出 {{ run.usage.output_tokens }} tokens{{ (run.metadata as any)?.session_mode === 'native_resume' ? ' · 原生续聊' : '' }}</p>
      </article>
    </div>
    <button v-if="newContent" class="new-content" type="button" @click="jumpToBottom">新内容，回到底部</button>
    </div>
    <div class="composer-extras" aria-label="阅读辅助与本轮设置">
      <div class="task-template-panel" :class="{ open: slashMenuOpen }">
        <slot name="paper-actions" :menu-open="slashMenuOpen" :close-menu="closeTaskPicker" />
      <div v-if="slashMenuOpen" class="template-options" role="listbox" aria-label="提问模板">
        <h3>提问模板 <small>填入后发送</small></h3>
        <button v-for="(t, i) in visibleTemplates" :key="t.id" type="button" role="option" :aria-selected="menuIndex === i" @click="chooseTemplate(t)" @mousedown.prevent>
          <strong>{{ t.name }}</strong><span>{{ t.description || t.prompt }}</span>
        </button>
        <StateFeedback v-if="!visibleTemplates.length" empty empty-text="暂无匹配模板。" />
      </div>
      </div>
      <details class="run-settings"><summary>模型与任务额度</summary>
    <RunConnectionControl v-model="selectedConnection" :disabled="busy || uploading" :bound="!!(runs.length || currentSession?.native_ready)" />
    <RunBudgetControl v-model="selectedBudget" :skill="currentSession?.skill" :disabled="busy || uploading" />
      </details>
    <div v-if="contexts.length" class="context-bar" aria-label="本次提问上下文">
      <div v-for="(c, i) in contexts" :key="'ctx-' + c.paper_id + '-' + c.page + '-' + i" class="context-chip" :class="{ current: c.paper_id === paperId }">
        <strong>{{ c.paper_id === paperId ? '当前论文' : '引用论文' }}</strong>
        <span>{{ resolvePaperTitle(c.paper_id) }}<template v-if="c.quote"> · 第 {{ c.page }} 页原文</template></span>
        <button :aria-label="'移除上下文 ' + resolvePaperTitle(c.paper_id)" type="button" @click="removeContext(i)">×</button>
      </div>
    </div>
    <div v-if="attachments.length" class="reader-attachments">
      <div v-for="a in attachments" :key="a.id" class="image-attachment">
        <img :src="a.url" :alt="a.filename || '提问图片'" />
        <button aria-label="移除图片" type="button" @click="removeAttachment(a.id)">×</button>
      </div>
    </div>
    <StateFeedback
      v-if="draftSaving || draftSaved || draftSaveError || exportError"
      class="draft-state"
      :saving="draftSaving"
      :saved="draftSaved"
      :save-error="draftSaveError || exportError"
    />
    </div>
    <form class="reader-composer" :class="{ dragging }" @submit.prevent="submit" @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop">
      <div v-if="mentionMenuOpen" class="command-menu" role="listbox" aria-label="论文引用">
        <button v-for="(p, i) in visiblePapers" :key="p.id" type="button" role="option" :aria-selected="menuIndex === i" @click="choosePaper(p)" @mousedown.prevent>
          <strong>{{ p.title }}</strong><span>已授权当前会话</span>
        </button>
        <StateFeedback v-if="!visiblePapers.length" empty empty-text="当前会话没有匹配论文。" />
      </div>
      <div class="composer-fields">
      <div class="composer-tools">
        <button type="button" class="menu-toggle" :aria-expanded="slashMenuOpen" @click="slashMenuOpen = !slashMenuOpen; slashQuery = ''; mentionMenuOpen = false">/ 任务与模板</button>
        <button type="button" class="menu-toggle" @click="mentionMenuOpen = !mentionMenuOpen; slashMenuOpen = false">@ 论文</button>
        <button type="button" class="image-picker" :disabled="!currentSession || currentSession.archived" @click="fileInput?.click()">＋ 图片</button><input ref="fileInput" class="sr-only" type="file" accept="image/png,image/jpeg" multiple aria-label="上传图片" :disabled="!currentSession || currentSession.archived" @change="onFiles" />
      </div>
      <textarea ref="questionInput" v-model="question" aria-label="向智能体提问" aria-describedby="composer-help" rows="3" maxlength="3000" placeholder="输入 / 选任务与模板，@ 引用论文，也可拖入或粘贴图片…" :disabled="!currentSession || currentSession.archived" @input="updateMenus" @keydown="onComposerKeydown" @compositionstart="composing = true" @compositionend="composing = false" @paste="onPaste"></textarea>
      <StateFeedback
        v-if="uploadError"
        class="upload-error"
        :error="uploadError"
        retry-text="重试上传"
        @retry="retryUpload"
      />
      <div id="composer-help" class="composer-help muted">Enter 发送 · Shift+Enter 换行 · / 任务与模板 · @ 论文</div>
      </div>
      <div class="composer-footer"><span class="muted">{{ question.length }}/3000 · 图片 {{ attachments.length }}/3 · 引用 {{ contexts.length }}/3</span><button class="primary" type="submit" :disabled="!canSend || !question.trim()">{{ uploading ? '上传中…' : busy ? '处理中…' : '发送 ↑' }}</button></div>
    </form>
    <p v-if="toast" class="chat-toast" role="status">{{ toast }}</p>
  </div>
</template>

<style scoped>
.conversation-modes { display:flex; gap:4px; padding:6px 12px; border-bottom:1px solid var(--border); flex-shrink:0; }
.conversation-modes button { font-size:12px; padding:4px 8px; background:transparent; border-color:transparent; }
.conversation-modes [aria-pressed="true"] { color:var(--accent); background:var(--accent-soft); border-color:var(--border); }
.conversation-modes .latest-message { margin-left:auto; }
.turn-role { font-size:12px; color:var(--text-muted); font-weight:600; letter-spacing:.04em; }
.assistant-role { margin-top:12px; color:var(--accent); }
.assistant-role span { font-weight:400; overflow-wrap:anywhere; }
.chat-heading { padding:12px 16px; border-bottom:1px solid var(--border); }
.session-summary { display:flex; align-items:center; gap:8px; min-width:0; }
.session-title { display:flex; align-items:center; gap:8px; min-width:0; flex:1; }
.session-text { display:grid; min-width:0; }
.session-text strong,.session-text small span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.session-text small { color:var(--text-muted); }
.detail-toggle { flex-shrink:0; font-size:12px; padding:5px 8px; }
.usage-summary { display:flex; flex-wrap:wrap; gap:6px 12px; margin-top:8px; font-size:12px; color:var(--text-muted); }
.session-details { padding:12px 16px; border-bottom:1px solid var(--border); background:var(--surface); }
.session-details dl { display:grid; gap:6px; margin:0; }
.session-details dl div { display:grid; grid-template-columns:100px minmax(0,1fr); gap:8px; font-size:12px; }
.session-details dt { color:var(--text-muted); }
.session-details dd { margin:0; overflow-wrap:anywhere; }
.session-details h4 { margin:12px 0 6px; font-size:12px; }
.run-record { display:flex; flex-wrap:wrap; gap:4px 10px; padding:6px 0; border-top:1px dashed var(--border); font-size:12px; }
.run-record strong,.run-record span { min-width:0; overflow-wrap:anywhere; }
.chat-heading > div { display:flex; gap:8px; align-items:center; }
.chat-heading strong { font-size:13px; }
.chat-heading small { margin-left:auto; font-size:12px; color:var(--text-muted); }
.chat-heading p { font-size:12px; margin:7px 0 12px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.agent-dot.running { background:var(--accent); animation:tab-pulse 1.2s infinite; }
.agent-dot.failed { background:var(--danger); }
.agent-dot { width:7px; height:7px; background:var(--accent); border-radius:50%; }
.chat-state { margin:auto 0; }
.draft-state { margin:0 var(--space-3); }
.export-chat { white-space:nowrap; }
.chat-empty { margin:auto 0; padding:32px 8px; text-align:center; color:var(--text-muted); font-size:12px; }
.chat-empty > span { display:block; color:var(--accent); font-size:32px; margin-bottom:12px; }
.chat-empty strong { font-size:14px; font-weight:500; color:var(--text); }
.chat-empty p { line-height:1.9; }
.composer-footer { position:sticky; bottom:0; background:var(--surface); flex-shrink:0; display:flex; align-items:center; justify-content:space-between; gap:8px; }
.composer-footer span { font-size:12px; }
.composer-footer button { padding:6px 14px; font-size:12px; }
.reader-composer textarea { width:100%; resize:vertical; min-height:88px; max-height:min(180px,20dvh); flex-shrink:0; font-size:13px; }
.chat-panel { position:relative; display:flex; flex-direction:column; flex:1 1 0; height:0; min-height:0; min-width:0; overflow:hidden; container-type:size; }
.chat-heading,.agent-state { flex-shrink:0; }
.conversation-view { position:relative; display:flex; flex-direction:column; flex:1 1 0; min-height:80px; min-width:0; overflow:hidden; }
.composer-extras { flex:0 1 auto; min-height:0; max-height:25%; overflow:auto; padding:6px 12px; border-top:1px solid var(--border); scrollbar-gutter:stable; }
.run-settings { font-size:12px; margin-top:6px; }
.run-settings summary { cursor:pointer; color:var(--text-muted); padding:4px 0; }
.reader-chat,.composer-extras { overscroll-behavior:contain; scrollbar-width:thin; scrollbar-color:var(--border-strong) var(--surface); }
.reader-chat::-webkit-scrollbar,.composer-extras::-webkit-scrollbar { width:9px; }
.reader-chat::-webkit-scrollbar-thumb,.composer-extras::-webkit-scrollbar-thumb { background:var(--border-strong); border:2px solid var(--surface); border-radius:8px; }
.reader-chat:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }
.session-summary { flex-wrap:wrap; }
.session-title { flex:1 1 100%; }
.session-summary :deep(.session-controls) { flex:1 1 180px; }

.agent-state { padding: var(--space-2) var(--space-3); font-size: 12px; border-bottom: 1px solid var(--border); }
.reader-chat { flex:1 1 0; min-height:0; min-width:0; overflow-wrap:anywhere; overflow-y:scroll; scrollbar-gutter:stable; padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-3); }
.chat-turn { flex:0 0 auto; min-width:0; border:0; border-bottom:1px solid var(--border); padding:12px 4px 24px; background:var(--bg); display:flex; flex-direction:column; gap:var(--space-2); }
.turn-time { font-size: 12px; }
.question { font-size:14px; line-height:1.7; font-weight:500; padding:10px 12px; border-radius:var(--radius); background:var(--surface); white-space:pre-wrap; }
.chat-image { max-width: 160px; border-radius: var(--radius); }
.original-context { border-left: 3px solid var(--accent); padding-left: var(--space-2); font-size: 12px; }
.original-context button { border: none; background: none; color: var(--accent); padding: 0; font-size: 12px; }
.answer :deep(p) { margin: var(--space-1) 0; }
.error { color: var(--danger); }
.usage { font-size: 12px; }
.context-bar { display:flex; flex-wrap:wrap; gap:var(--space-1); padding:var(--space-2) var(--space-3) 0; }
.context-chip { display:flex; align-items:center; gap:5px; max-width:100%; padding:4px 6px; border:1px solid var(--border); border-radius:999px; background:var(--bg); font-size:12px; }
.context-chip.current { border-color:var(--accent); background:var(--accent-soft); }
.context-chip span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.context-chip button { border:0; background:none; padding:0 2px; color:var(--text-muted); }
.reader-attachments { display: flex; gap: var(--space-2); padding: var(--space-2) var(--space-3) 0; }
.image-attachment { position: relative; }
.image-attachment img { width: 64px; height: 64px; object-fit: cover; border-radius: var(--radius); }
.image-attachment button { position: absolute; top: -6px; right: -6px; padding: 0 6px; border-radius: 50%; }
.reader-composer { flex:0 1 auto; min-height:190px; max-height:45%; display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border-top: 1px solid var(--border); position:relative; }
.reader-composer.dragging::after { content:'松开以上传图片'; position:absolute; inset:4px; display:grid; place-items:center; border:1px dashed var(--accent); border-radius:var(--radius); background:var(--bg); color:var(--accent); font-size:12px; pointer-events:none; }
.composer-fields { min-height:0; overflow:auto; display:flex; flex-direction:column; gap:var(--space-2); }
.composer-help { font-size:12px; line-height:1.6; }
.composer-tools { flex-wrap:wrap; display: flex; gap: var(--space-2); align-items: center; }
.composer-tools select { flex: 1; min-width:0; font-size:12px; padding:6px; }
.menu-toggle,.image-picker { font-size:12px; padding:6px 8px; }
.image-picker { flex-shrink:0; }
.task-template-panel.open { border:1px solid var(--border); border-radius:var(--radius); background:var(--surface); }
.template-options { padding:8px; }
.template-options h3 { font-size:12px; margin:0 0 8px; }
.template-options small { font-weight:400; color:var(--text-muted); margin-left:6px; }
.template-options button { display:grid; gap:2px; width:100%; padding:7px; border:0; background:none; text-align:left; }
.template-options button:hover,.template-options button[aria-selected="true"] { background:var(--accent-soft); }
.template-options strong { font-size:12px; }
.template-options span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; color:var(--text-muted); }
.command-menu { position:absolute; left:var(--space-3); right:var(--space-3); bottom:calc(100% - 8px); z-index:8; max-height:min(230px,30dvh); overflow-y:auto; padding:4px; border:1px solid var(--border); border-radius:var(--radius); background:var(--surface); box-shadow:0 8px 24px rgb(0 0 0 / .12); }
.command-menu button { display:grid; gap:2px; width:100%; padding:7px; border:0; background:none; text-align:left; }
.command-menu button:hover,.command-menu button[aria-selected="true"] { background:var(--accent-soft); }
.command-menu strong { font-size:12px; }
.command-menu span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; color:var(--text-muted); }
.upload-error { display:flex; align-items:center; gap:6px; margin:0; font-size:12px; }
.upload-error button { padding:2px 6px; font-size:12px; }
.chat-toast { position:absolute; bottom:0; left:12px; right:12px; z-index:10; background:var(--surface); color: var(--danger); padding: 0 var(--space-3); font-size: 12px; }
.agent-state { display:flex; align-items:center; gap:8px; }
.run-meta { margin-left:auto; }
.stop-run { padding:3px 8px; font-size:12px; flex-shrink:0; }
.load-older { align-self:center; font-size:12px; padding:5px 10px; }
.tool-group,.execution-details { border-top:1px dashed var(--border); padding-top:var(--space-2); font-size:12px; }
.tool-group summary,.execution-details summary { cursor:pointer; color:var(--text-muted); }
.tool-call { display:grid; gap:4px; padding:var(--space-2) 0; }
.tool-call pre { max-height:180px; overflow:auto; margin:0; padding:var(--space-2); border-radius:var(--radius); background:var(--surface); font-size:12px; }
.execution-details dl { display:grid; gap:4px; margin:var(--space-2) 0 0; }
.execution-details div { display:grid; grid-template-columns:90px 1fr; gap:var(--space-2); }
.execution-details dt { color:var(--text-muted); }
.execution-details dd { margin:0; min-width:0; overflow-wrap:anywhere; }
.copy-answer { align-self:flex-start; font-size:12px; padding:3px 7px; }
.new-content { position:absolute; right:var(--space-4); bottom:12px; z-index:7; padding:5px 10px; font-size:12px; border-color:var(--accent); color:var(--accent); background:var(--surface); box-shadow:0 5px 16px rgb(0 0 0 / .12); }
.answer :deep(table) { display:block; max-width:100%; overflow-x:auto; }
.answer :deep(img) { max-width:100%; height:auto; }

@container (max-height:520px) {
  .chat-heading { padding:6px 10px; }
  .chat-heading .usage-summary { display:none; }
  .agent-state { padding:5px 10px; }
  .reader-composer { min-height:148px; padding:8px; gap:4px; }
  .reader-composer textarea { min-height:60px; }
  .composer-fields { gap:4px; }
  .composer-help { display:none; }
  .composer-tools button { padding:3px 6px; }
  .composer-footer button { padding:4px 10px; }
  .composer-extras { max-height:18%; padding:4px 8px; }
}
</style>
