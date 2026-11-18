import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { workbenchApi } from '@/api/workbench'
import { readerApi } from '@/api/reader'
import { sessionsApi } from '@/api/sessions'
import { papersApi } from '@/api/papers'

// 真实 ReaderPane + 假 PDF 引擎：验证 KeepAlive 驱逐时草稿/位置落库。
vi.mock('@/reader/pdf-engine', () => ({
  PDFReader: class {
    currentPage = 1
    zoom = 'fit'
    info = {}
    pdf = {}
    addEventListener() {}
    load() { return Promise.resolve() }
    layout() {}
    jump() {}
    setAnnotations() {}
    setMode() {}
    destroy() {}
  },
}))

import ReadingView from './ReadingView.vue'

const session = { id: 5, title: '阅读', skill: 'paper_read', paper_ids: [1, 2], native_ready: true, draft_prompt: '', archived: false }
const doc = { paper_id: 1, title: 'P', file_version: 'v', page_count: 2, width: 600, height: 800, outline: [], pdf_url: '/x' }

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.spyOn(workbenchApi, 'saveState').mockImplementation(async (_id, s) => s)
  vi.spyOn(workbenchApi, 'getDraft').mockResolvedValue({ prompt: '', context: null, attachment_ids: [], attachments: [] })
  vi.spyOn(workbenchApi, 'saveDraft').mockResolvedValue({ saved: true })
  vi.spyOn(papersApi, 'get').mockResolvedValue({ id: 1, title: 'P' } as never)
  vi.spyOn(readerApi, 'document').mockResolvedValue(doc as never)
  vi.spyOn(readerApi, 'getState').mockResolvedValue({ conversation_id: 5, page: 1, zoom: 'fit', tab: 'outline' })
  vi.spyOn(readerApi, 'saveState').mockResolvedValue({ conversation_id: 5, page: 1, zoom: 'fit', tab: 'outline' })
  vi.spyOn(readerApi, 'annotations').mockResolvedValue({ annotations: [] })
  vi.spyOn(readerApi, 'translations').mockResolvedValue({ translations: [] })
  vi.spyOn(sessionsApi, 'list').mockResolvedValue({ sessions: [session] } as never)
  vi.spyOn(sessionsApi, 'get').mockResolvedValue({ session, papers: [] } as never)
  vi.spyOn(sessionsApi, 'runs').mockResolvedValue({ runs: [], has_more: false, next_before: null })
  vi.spyOn(sessionsApi, 'templates').mockResolvedValue({ templates: [], kinds: {}, skills: [] })
})

describe('ReadingView flush on eviction', () => {
  it('deactivated pane persists reading position', async () => {
    const wrapper = mount(ReadingView, { props: { paperId: 1, sessionId: 5 } })
    await flushPromises()
    vi.mocked(readerApi.saveState).mockClear()
    await wrapper.setProps({ paperId: 2 })
    await flushPromises()
    // 面板 1 被 KeepAlive deactivate → flush → saveState
    expect(readerApi.saveState).toHaveBeenCalled()
    expect(vi.mocked(readerApi.saveState).mock.calls[0][0]).toBe(1)
  })
})
