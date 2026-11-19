import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import ReaderSidebar from './ReaderSidebar.vue'
import { readerApi } from '@/api/reader'

const doc = { paper_id: 1, title: 'Paper', file_version: 'v1', page_count: 3, width: 600, height: 800, outline: [{ level: 1, title: 'Intro', page: 1 }], pdf_url: '/x' }
const profile = { id: 1, title: 'Paper', authors: ['A'], affiliations: [], abstract: 'abs', summary: 'abs', doi: null }
const session = { id: 5, title: '阅读' }

function makeOrch() {
  return {
    setTab: vi.fn(), savePosition: vi.fn(), jump: vi.fn(), selectionAction: vi.fn(),
    watchRun: vi.fn(), refreshAnnotations: vi.fn(async () => {}),
    sidebarTab: ref('outline'), noteContext: ref(null), profile: ref(profile), annotationsVersion: ref(0),
    positionSnapshot: () => ({ page: 2 }),
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(readerApi, 'annotations').mockResolvedValue({ annotations: [] })
  vi.spyOn(readerApi, 'translations').mockResolvedValue({ translations: [] })
  vi.spyOn(readerApi, 'patchAnnotation').mockResolvedValue({} as never)
  vi.spyOn(readerApi, 'setTranslationVisible').mockResolvedValue({ id: 't1', deleted: true })
  vi.spyOn(readerApi, 'createAnnotation').mockResolvedValue({ id: 'n1' } as never)
  vi.spyOn(readerApi, 'translate').mockResolvedValue({ id: 't2', run_id: 'r2', status: 'queued', cached: false })
})

async function mountSidebar(orch = makeOrch()) {
  const wrapper = mount(ReaderSidebar, { props: { doc: doc as never, session: session as never, orchestrator: orch as never } })
  await flushPromises()
  return { wrapper, orch }
}

describe('ReaderSidebar', () => {
  it('restores an already loaded guide tab without overwriting saved position', async () => {
    const orch=makeOrch();orch.sidebarTab.value='guide'
    const {wrapper}=await mountSidebar(orch)
    expect(wrapper.find('[data-tab="guide"]').attributes('aria-selected')).toBe('true')
    expect(orch.savePosition).not.toHaveBeenCalled()
  })

  it('tab switch notifies orchestrator and saves position', async () => {
    const { wrapper, orch } = await mountSidebar()
    await wrapper.find('[data-tab="translations"]').trigger('click')
    expect(orch.setTab).toHaveBeenCalledWith('translations')
    expect(orch.savePosition).toHaveBeenCalled()
  })

  it('failed translation offers retry that calls translate and watches run', async () => {
    vi.spyOn(readerApi, 'translations').mockResolvedValue({ translations: [{ id: 't1', paper_id: 1, page: 2, file_version: 'v1', quote: 'q', status: 'failed', answer: '', error: 'x', run_id: 'r1', conversation_id: 5, quote_hash: 'h', language: 'zh-CN', deleted: 0, created_at: '' }] } as never)
    const { wrapper, orch } = await mountSidebar()
    await wrapper.find('[data-tab="translations"]').trigger('click')
    await wrapper.find('button.retry-translation').trigger('click')
    await flushPromises()
    expect(readerApi.translate).toHaveBeenCalledWith(expect.objectContaining({ paper_id: 1, page: 2, conversation_id: 5 }))
    expect(orch.watchRun).toHaveBeenCalledWith('r2')
  })

  it('translation delete is undoable', async () => {
    vi.spyOn(readerApi, 'translations').mockResolvedValue({ translations: [{ id: 't1', paper_id: 1, page: 2, file_version: 'v1', quote: 'q', status: 'succeeded', answer: '译', error: null, run_id: 'r1', conversation_id: 5, quote_hash: 'h', language: 'zh-CN', deleted: 0, created_at: '' }] } as never)
    const { wrapper } = await mountSidebar()
    await wrapper.find('[data-tab="translations"]').trigger('click')
    await wrapper.find('button.delete-translation').trigger('click')
    await flushPromises()
    expect(readerApi.setTranslationVisible).toHaveBeenCalledWith('t1', true)
    await wrapper.find('button.undo').trigger('click')
    await flushPromises()
    expect(readerApi.setTranslationVisible).toHaveBeenCalledWith('t1', false)
  })

  it('annotation delete calls soft delete', async () => {
    vi.spyOn(readerApi, 'annotations').mockResolvedValue({ annotations: [{ id: 'a1', paper_id: 1, page: 2, file_version: 'v1', kind: 'note', quote: '', content: '注', color: '#f5d76e', rects: [], points: [], conversation_id: 5, deleted: 0, created_at: '', updated_at: '' }] } as never)
    const { wrapper } = await mountSidebar()
    await wrapper.find('[data-tab="notes"]').trigger('click')
    await wrapper.find('button.delete-annotation').trigger('click')
    await flushPromises()
    expect(readerApi.patchAnnotation).toHaveBeenCalledWith('a1', { deleted: true })
  })

  it('shows a retryable load error instead of an empty record list', async () => {
    vi.spyOn(readerApi, 'annotations').mockRejectedValueOnce(new Error('阅读记录服务不可用'))
    const { wrapper } = await mountSidebar()
    expect(wrapper.text()).toContain('阅读记录服务不可用')
    expect(wrapper.text()).toContain('重试')
    expect(wrapper.text()).not.toContain('这里会保存你的阅读记录。')
    await wrapper.find('[data-tab="notes"]').trigger('click')
    await wrapper.find('.state-feedback .error button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('这里会保存你的阅读记录。')
  })

  it('shows note save failure without success', async () => {
    vi.spyOn(readerApi, 'createAnnotation').mockRejectedValueOnce(new Error('批注服务不可用'))
    const { wrapper } = await mountSidebar()
    await wrapper.find('[data-tab="notes"]').trigger('click')
    await wrapper.find('textarea.note-text').setValue('我的批注')
    await wrapper.find('button.save-note').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('保存失败：批注服务不可用')
    expect(wrapper.text()).not.toContain('已保存')
  })

  it('saveNote requires content and posts note annotation', async () => {
    const { wrapper } = await mountSidebar()
    await wrapper.find('[data-tab="notes"]').trigger('click')
    await wrapper.find('button.save-note').trigger('click')
    await flushPromises()
    expect(readerApi.createAnnotation).not.toHaveBeenCalled()
    await wrapper.find('textarea.note-text').setValue('我的批注')
    await wrapper.find('button.save-note').trigger('click')
    await flushPromises()
    expect(readerApi.createAnnotation).toHaveBeenCalledWith(expect.objectContaining({ kind: 'note', content: '我的批注', conversation_id: 5 }))
  })
})
