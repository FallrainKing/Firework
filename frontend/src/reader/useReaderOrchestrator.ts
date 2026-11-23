import { ref } from 'vue'
import { papersApi } from '@/api/papers'
import { readerApi } from '@/api/reader'
import { sessionsApi } from '@/api/sessions'
import type { Annotation, Paper, Position, ReaderDoc, SelectionContext, Session } from '@/api/types'
import type { PdfDocInfo } from './pdf-engine'

export interface ChatBridge {
  ask(prompt: string, contexts?: SelectionContext[], purpose?: string): Promise<void>
  watch(runId: string): void
  flushDraft(): Promise<void>
  restoreDraft(): Promise<void>
  setContext(ctx: SelectionContext | null): void
  load(session: Session): Promise<void>
}

export interface EngineLike {
  load(info: ReaderDoc, position?: { page?: number; zoom?: string }): Promise<void>
  layout(): void
  jump(page: number, flash?: boolean): void
  locate?(context:SelectionContext):Promise<void>
  setAnnotations(items: Annotation[]): void
  currentPage: number
  zoom: string
  info: PdfDocInfo
  pdf?: unknown
}

interface Deps {
  documentVersion?:string
  paperId: number
  engine: EngineLike
  toast: (message: string) => void
  onOpenPaper?: (paperId: number, sessionId?: number) => void
  onOpenImport?: (paperId: number) => void
  onSessionBound?: (sessionId: number) => void
}

// 对照旧 reader/main.js 的编排：boot/activate(epoch 守卫)/位置防抖/选区五动作/版本守卫。
export function useReaderOrchestrator(deps: Deps) {
  const { paperId, engine, toast } = deps
  const profile = ref<Paper | null>(null)
  const doc = ref<ReaderDoc | null>(null)
  const session = ref<Session | null>(null)
  const missingPdf = ref(false)
  const loading = ref(true)
  const loadError = ref('')
  const noteContext = ref<SelectionContext | null>(null)
  const sidebarTab = ref<Position['tab']>('outline')
  const annotationsVersion = ref(0)

  let chat: ChatBridge | null = null
  let activation = 0
  let restoring = false
  let loadedOnce = false
  let loadPromise: Promise<void> | null = null
  let stateTimer: ReturnType<typeof setTimeout> | null = null

  function registerChat(bridge: ChatBridge) { chat = bridge }
  function setTab(tab: Position['tab']) { sidebarTab.value = tab }

  function positionSnapshot(): Position | null {
    return session.value && doc.value
      ? { file_version:doc.value.file_version, conversation_id: session.value.id, page: engine.currentPage, zoom: engine.zoom as Position['zoom'], tab: sidebarTab.value }
      : null
  }

  async function writePosition() {
    const body = positionSnapshot()
    if (body && !restoring) await readerApi.saveState(paperId, body)
  }

  function savePosition() {
    if (stateTimer) clearTimeout(stateTimer)
    if (restoring) return
    const body = positionSnapshot()
    if (body) stateTimer = setTimeout(() => readerApi.saveState(paperId, body).catch(e => toast(e.message)), 400)
  }

  async function flush() {
    await chat?.flushDraft()
    if (stateTimer) clearTimeout(stateTimer)
    await writePosition().catch(e => toast(e.message))
  }

  async function refreshAnnotations() {
    const { annotations } = await readerApi.annotations(paperId)
    engine.setAnnotations(annotations)
    annotationsVersion.value++
  }

  async function activate(id: number, skipFlush = false) {
    const epoch = ++activation
    if (chat && !skipFlush) {
      await chat.flushDraft()
      await writePosition()
    }
    if (epoch !== activation) return
    restoring = true
    try {
      const next = (await sessionsApi.get(id)).session
      if (epoch !== activation) return
      if (!next.paper_ids.includes(paperId)) throw new Error('所选会话未关联当前论文')
      session.value = next
      const position = await readerApi.getState(paperId, id,deps.documentVersion?doc.value?.file_version:undefined)
      if (epoch !== activation) return
      sidebarTab.value = position.tab
      engine.zoom = position.zoom
      engine.currentPage = position.page
      if (loadedOnce) engine.layout()
      else {
        // 并发 activate 共享同一个 load promise，避免双重 getDocument。
        if (!loadPromise) loadPromise = engine.load(doc.value!, position).then(() => { loadedOnce = true })
        await loadPromise
        if (epoch !== activation) return
        engine.currentPage = position.page
        engine.zoom = position.zoom
        engine.layout()
      }
      if (epoch !== activation) return
      await chat?.load(next)
      if (epoch !== activation) return
      deps.onSessionBound?.(next.id)
    } catch (e) {
      toast(e instanceof Error ? e.message : '会话切换失败')
    } finally {
      if (epoch === activation) {
        restoring = false
        await writePosition().catch(() => {})
      }
    }
  }

  async function boot(sessionId?: number | null) {
    loading.value = true
    loadError.value = ''
    missingPdf.value = false
    try {
      profile.value = await papersApi.get(paperId)
      try {
        doc.value = deps.documentVersion?await readerApi.document(paperId,deps.documentVersion):await readerApi.document(paperId)
      } catch (e) {
        missingPdf.value = true
        loadError.value = e instanceof Error ? e.message : '无法读取论文'
        return
      }
      const { sessions } = await sessionsApi.list({ paper_id: paperId, limit: 100 })
      const usable = sessions.filter(s => !s.stale_paper_ids?.includes(paperId))
      const existing = usable.filter(s => ['paper_read', 'paper_review'].includes(s.skill))
      let sid = (sessionId && usable.some(s=>s.id===sessionId) ? sessionId : null) || existing[0]?.id || null
      if (!sid) {
        const created = await sessionsApi.create({ template_id: 'read', title: (profile.value?.title ?? '论文') + ' · 阅读', paper_ids: [paperId] })
        sid = created.session.id
      }
      await activate(sid, true)
      await refreshAnnotations()
    } catch (e) {
      loadError.value = e instanceof Error ? e.message : '载入失败'
    } finally {
      loading.value = false
    }
  }

  async function jump(context: SelectionContext) {
    try {
      const source=await readerApi.locate(context)
      if(source.file_version!==doc.value?.file_version){
        if(source.original_url)window.open(source.original_url,'_blank','noopener')
        else toast('原文版本不可用')
        return
      }
      if(source.paper_id!==paperId){deps.onOpenPaper?.(source.paper_id,session.value?.id);return}
      if(source.status!=='located'&&source.quote)toast(source.status==='ambiguous'?'原文有多处匹配，已跳至来源页':'未找到精确位置，已跳至来源页')
      if(engine.locate)await engine.locate(source)
      else engine.jump(source.page,true)
    } catch(e){toast(e instanceof Error?e.message:'原文定位失败')}
  }

  async function selectionAction(action: string, ctx: SelectionContext, color?: string) {
    const sid = session.value?.id
    try {
      if (action === 'highlight') {
        await readerApi.createAnnotation({ ...ctx, kind: 'highlight', color, conversation_id: sid })
        await refreshAnnotations()
        sidebarTab.value = 'highlights'
        toast('高亮已保存')
      } else if (action === 'note') {
        noteContext.value = ctx
      } else if (action === 'chat') {
        chat?.setContext(ctx)
      } else if (action === 'explain') {
        await chat?.ask('请解释本次选中的原文，结合上下文说明术语或公式含义。', [ctx], 'explain')
      } else if (action === 'translate') {
        const result = await readerApi.translate({ ...ctx, conversation_id: sid! })
        sidebarTab.value = 'translations'
        if (result.cached && result.status === 'succeeded') toast('已复用保存的译文，没有新增模型调用')
        else { chat?.watch(result.run_id); toast('已交给当前智能体会话翻译') }
        // 缓存命中也刷新侧栏列表（无 run → 无 annotationsVersion 触发）。
        await refreshAnnotations()
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : '操作失败')
    }
  }

  async function saveInk(detail: Record<string, unknown>) {
    try {
      await readerApi.createAnnotation({ ...(detail as unknown as SelectionContext), kind: 'ink', conversation_id: session.value?.id })
      await refreshAnnotations()
    } catch (e) {
      toast(e instanceof Error ? e.message : '笔迹保存失败')
    }
  }

  async function eraseAnnotation(id: string) {
    try {
      await readerApi.patchAnnotation(id, { deleted: true })
      await refreshAnnotations()
    } catch (e) {
      toast(e instanceof Error ? e.message : '擦除失败')
    }
  }

  function watchRun(runId: string) { chat?.watch(runId) }

  return {
    profile, doc, session, missingPdf, loading, loadError, noteContext, sidebarTab, annotationsVersion,
    registerChat, setTab, boot, activate, jump, selectionAction, saveInk, eraseAnnotation,
    refreshAnnotations, savePosition, writePosition, flush, positionSnapshot, watchRun,
  }
}
