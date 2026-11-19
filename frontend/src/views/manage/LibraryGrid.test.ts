import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import LibraryGrid from './LibraryGrid.vue'
import { papersApi } from '@/api/papers'
import { sessionsApi } from '@/api/sessions'

const paper = { id: 1, title: 'Attention', authors: ['A'], affiliations: [], abstract: 'abs', brief_summary: null, summary: 'abs', doi: null, arxiv_id: null, status: 'ready', reading_status: 'unread', collections: [{ id: 2, name: '基础模型' }], thumbnail_url: '/api/library/papers/1/thumbnail', image_caption: '原始 PDF 首页预览', has_pdf: true, metadata_version: 1 }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(papersApi, 'list').mockResolvedValue({ papers: [paper], total: 1, offset: 0, has_more: false } as never)
  vi.spyOn(papersApi, 'collections').mockResolvedValue({ collections: [{ id: 2, name: '基础模型', count: 1 }] })
  vi.spyOn(sessionsApi, 'templates').mockResolvedValue({ templates: [], kinds: {}, skills: [] })
  vi.spyOn(sessionsApi, 'categories').mockResolvedValue({ categories: [] })
})

async function mountGrid() {
  const wrapper = mount(LibraryGrid)
  await flushPromises()
  return wrapper
}

describe('LibraryGrid', () => {
  it('renders paper cards with collection badges', async () => {
    const wrapper = await mountGrid()
    expect(wrapper.text()).toContain('Attention')
    expect(wrapper.text()).toContain('基础模型')
    expect(wrapper.find('img').attributes('src')).toBe('/api/library/papers/1/thumbnail')
  })

  it('switches between card and compact density', async () => {
    const wrapper = await mountGrid()
    expect(wrapper.find('.paper-grid').classes()).not.toContain('compact')
    await wrapper.find('[aria-label="列表密度"] button[aria-pressed="false"]').trigger('click')
    expect(wrapper.find('.paper-grid').classes()).toContain('compact')
    wrapper.unmount()
  })

  it('read button emits open-paper', async () => {
    const wrapper = await mountGrid()
    await wrapper.find('button.read-paper').trigger('click')
    expect(wrapper.emitted('open-paper')?.[0]).toEqual([1])
  })

  it('missing-pdf paper offers supplement entry', async () => {
    vi.spyOn(papersApi, 'list').mockResolvedValue({ papers: [{ ...paper, has_pdf: false, thumbnail_url: null }], total: 1, offset: 0, has_more: false } as never)
    const wrapper = await mountGrid()
    await wrapper.find('button.supplement-pdf').trigger('click')
    expect(wrapper.emitted('open-import')?.[0]).toEqual([1])
  })

  it('reading status filter uses recorded reading task status', async () => {
    const wrapper = await mountGrid()
    await wrapper.find('select.reading-filter').setValue('read')
    await flushPromises()
    expect(papersApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ reading_status: 'read', offset: 0 }))
    wrapper.unmount()
  })

  it('collection filter passes collection_id', async () => {
    const wrapper = await mountGrid()
    await wrapper.find('select.collection-filter').setValue('2')
    await flushPromises()
    expect(papersApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ collection_id: 2, offset: 0 }))
  })

  it('shows the batch bar only after selection', async () => {
    const wrapper = await mountGrid()
    expect(wrapper.find('.batch-bar').exists()).toBe(false)
    await wrapper.find('input.paper-select').setValue(true)
    expect(wrapper.find('.batch-bar').exists()).toBe(true)
    expect(wrapper.find('.batch-bar').text()).toContain('已选择 1 篇')
    wrapper.unmount()
  })

  it('compare selected requires two papers', async () => {
    const wrapper = await mountGrid()
    await wrapper.find('input.paper-select').setValue(true)
    expect(wrapper.find('button.compare-selected').attributes('disabled')).toBeDefined()
    await wrapper.find('input.paper-select').setValue(true)
    expect(wrapper.find('button.compare-selected').attributes('disabled')).toBeDefined()
  })

  it('opens management and full information from the more menu', async () => {
    vi.spyOn(papersApi, 'get').mockResolvedValue(paper as never)
    vi.spyOn(papersApi, 'patch').mockRejectedValue(Object.assign(new Error('论文信息已更新，请刷新后重试'), { status: 409 }))
    const wrapper = await mountGrid()
    await wrapper.find('button.more-actions').trigger('click')
    expect(wrapper.find('.card-menu').text()).toContain('完整信息 / 管理信息')
    await wrapper.find('button.edit-paper').trigger('click')
    await flushPromises()
    await wrapper.find('button.save-paper').trigger('click')
    await flushPromises()
    expect(papersApi.patch).toHaveBeenCalledWith(1, expect.objectContaining({ metadata_version: 1 }))
    expect(wrapper.text()).toContain('已更新')
  })
})
