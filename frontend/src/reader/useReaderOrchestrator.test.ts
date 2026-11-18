import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReaderOrchestrator } from './useReaderOrchestrator'
import { readerApi } from '@/api/reader'
import { sessionsApi } from '@/api/sessions'
import { papersApi } from '@/api/papers'
import { workbenchApi } from '@/api/workbench'

const doc = { paper_id: 1, title: 'Paper', file_version: 'v1', page_count: 3, width: 600, height: 800, outline: [], pdf_url: '/x' }
const session = { id: 5, title: '阅读', skill: 'paper_read', paper_ids: [1], native_ready: true, draft_prompt: '' }
const position = { conversation_id: 5, page: 2, zoom: 'fit', tab: 'outline' }

function fakeEngine() {
  return {
    load: vi.fn(async () => {}),
    layout: vi.fn(),
    jump: vi.fn(),
    setAnnotations: vi.fn(),
    currentPage: 2,
    zoom: 'fit',
    info: doc,
    addEventListener: vi.fn(),
    destroy: vi.fn(),
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(papersApi, 'get').mockResolvedValue({ id: 1, title: 'Paper' } as never)
  vi.spyOn(readerApi, 'document').mockResolvedValue(doc as never)
  vi.spyOn(readerApi, 'getState').mockResolvedValue(position as never)
  vi.spyOn(readerApi, 'saveState').mockResolvedValue(position as never)
  vi.spyOn(readerApi, 'annotations').mockResolvedValue({ annotations: [] })
  vi.spyOn(readerApi, 'createAnnotation').mockResolvedValue({ id: 'a1' } as never)
  vi.spyOn(readerApi, 'translate').mockResolvedValue({ id: 't1', run_id: 'r1', status: 'succeeded', cached: true })
  vi.spyOn(sessionsApi, 'list').mockResolvedValue({ sessions: [session] } as never)
  vi.spyOn(sessionsApi, 'get').mockResolvedValue({ session, papers: [] } as never)
  vi.spyOn(sessionsApi, 'create').mockResolvedValue({ session, starting_prompt: '' } as never)
  vi.spyOn(workbenchApi, 'saveState').mockImplementation(async (_id, s) => s)
})

function setup() {
  const engine = fakeEngine()
  const toasts: string[] = []
  const orch = useReaderOrchestrator({ paperId: 1, engine: engine as never, toast: m => toasts.push(m) })
  return { engine, orch, toasts }
}

describe('reader orchestrator', () => {
  it('boot with missing PDF shows supplement entry and skips engine', async () => {
    vi.spyOn(readerApi, 'document').mockRejectedValue(new Error('这篇论文尚无 PDF 全文'))
    const { engine, orch } = setup()
    await orch.boot()
    expect(orch.missingPdf.value).toBe(true)
    expect(engine.load).not.toHaveBeenCalled()
  })

  it('boot auto-creates read session when none exists', async () => {
    vi.spyOn(sessionsApi, 'list').mockResolvedValue({ sessions: [] })
    const { orch } = setup()
    await orch.boot()
    expect(sessionsApi.create).toHaveBeenCalledWith(expect.objectContaining({ template_id: 'read', paper_ids: [1] }))
    expect(orch.session.value?.id).toBe(5)
  })

  it('activate epoch guard keeps only the last session', async () => {
    const { orch } = setup()
    await orch.boot()
    let resolveFirst!: (v: { session: import('@/api/types').Session; papers: Array<{ id: number; title: string }> }) => void
    vi.spyOn(sessionsApi, 'get')
      .mockImplementationOnce(() => new Promise(r => { resolveFirst = r }))
      .mockResolvedValue({ session: { ...session, id: 9, paper_ids: [1] }, papers: [] } as never)
    const first = orch.activate(5)
    const second = orch.activate(9)
    resolveFirst({ session: session as import('@/api/types').Session, papers: [] })
    await Promise.all([first, second])
    expect(orch.session.value?.id).toBe(9)
  })

  it('activate rejects session not linked to paper', async () => {
    vi.spyOn(sessionsApi, 'get').mockResolvedValue({ session: { ...session, paper_ids: [2] }, papers: [] } as never)
    const { orch, toasts } = setup()
    await orch.boot()
    await orch.activate(5)
    expect(toasts.some(t => t.includes('未关联'))).toBe(true)
  })

  it('translate cache hit toasts and does not watch a run', async () => {
    const { orch, toasts } = setup()
    await orch.boot()
    const watched: string[] = []
    orch.registerChat({ ask: vi.fn(), watch: id => watched.push(id), flushDraft: vi.fn(async () => {}), restoreDraft: vi.fn(async () => {}), setContext: vi.fn(), load: vi.fn(async () => {}) })
    await orch.selectionAction('translate', { paper_id: 1, page: 2, file_version: 'v1', quote: 'q', rects: [] })
    expect(toasts.some(t => t.includes('复用'))).toBe(true)
    expect(watched).toHaveLength(0)
  })

  it('jump refuses stale file version', async () => {
    const { engine, orch, toasts } = setup()
    await orch.boot()
    orch.jump({ paper_id: 1, page: 2, file_version: 'old', quote: '', rects: [] })
    expect(engine.jump).not.toHaveBeenCalled()
    expect(toasts.some(t => t.includes('旧 PDF 版本'))).toBe(true)
  })

  it('highlight creates annotation and refreshes', async () => {
    const { orch } = setup()
    await orch.boot()
    await orch.selectionAction('highlight', { paper_id: 1, page: 2, file_version: 'v1', quote: 'q', rects: [[0.1, 0.1, 0.2, 0.02]] }, '#f5d76e')
    expect(readerApi.createAnnotation).toHaveBeenCalledWith(expect.objectContaining({ kind: 'highlight', color: '#f5d76e', conversation_id: 5 }))
  })

  it('concurrent activates share one engine load and keep the last session', async () => {
    const engine = fakeEngine()
    let resolveLoad!: () => void
    engine.load = vi.fn(() => new Promise<void>(r => { resolveLoad = r }))
    vi.spyOn(sessionsApi, 'get').mockImplementation(async (id: number) => ({ session: { ...session, id }, papers: [] }) as never)
    const toasts: string[] = []
    const orch = useReaderOrchestrator({ paperId: 1, engine: engine as never, toast: m => toasts.push(m) })
    const bootP = orch.boot() // boot 的 activate 停在 pending 的 engine.load
    await vi.waitFor(() => expect(engine.load).toHaveBeenCalled())
    const second = orch.activate(9)
    resolveLoad()
    await Promise.all([bootP, second])
    expect(orch.session.value?.id).toBe(9)
    expect(engine.load).toHaveBeenCalledTimes(1)
  })
})
