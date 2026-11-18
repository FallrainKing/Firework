import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import OpenPaperDialog from './OpenPaperDialog.vue'
import { papersApi } from '@/api/papers'
afterEach(() => vi.restoreAllMocks())
describe('OpenPaperDialog', () => {
  it('opens an existing paper, marks missing full text, and offers import separately', async () => {
    vi.spyOn(papersApi, 'list').mockResolvedValue({ papers: [{ id: 7, title: '已有论文', authors: ['作者'], has_pdf: true }, { id: 8, title: '仅书目', authors: [], has_pdf: false }], has_more: false } as never)
    const wrapper = mount(OpenPaperDialog)
    await flushPromises()
    const rows = wrapper.findAll('.open-paper-row')
    expect(rows[1].text()).toContain('补充全文')
    await rows[0].trigger('click')
    expect(wrapper.emitted('open')?.[0]).toEqual([7])
    await wrapper.find('.picker-search button').trigger('click')
    expect(wrapper.emitted('import')).toHaveLength(1)
    wrapper.unmount()
  })
})
