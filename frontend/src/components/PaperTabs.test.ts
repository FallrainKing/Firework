import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PaperTabs from './PaperTabs.vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useLibraryStore } from '@/stores/library'
import { workbenchApi } from '@/api/workbench'

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.spyOn(workbenchApi, 'saveState').mockImplementation(async (_id, s) => s)
})

function seeded() {
  const wb = useWorkbenchStore()
  wb.tabs = [{ paper_id: 1, session_id: 10 }, { paper_id: 2, session_id: null }]
  wb.activePaperId = 1
  const lib = useLibraryStore()
  lib.papersById = { 1: { id: 1, title: 'Attention' } as never, 2: { id: 2, title: 'Diffusion' } as never }
  return wb
}

describe('PaperTabs', () => {
  it('renders tabs with titles and active state', () => {
    seeded()
    const wrapper = mount(PaperTabs)
    const tabs = wrapper.findAll('[role="tab"]')
    expect(tabs).toHaveLength(2)
    expect(tabs[0].text()).toContain('Attention')
    expect(tabs[0].attributes('aria-selected')).toBe('true')
    expect(tabs[1].text()).toContain('Diffusion')
  })

  it('click activates tab in store', async () => {
    const wb = seeded()
    const wrapper = mount(PaperTabs)
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    expect(wb.activePaperId).toBe(2)
  })

  it('close button removes tab', async () => {
    const wb = seeded()
    const wrapper = mount(PaperTabs)
    await wrapper.findAll('.tab-close')[0].trigger('click')
    expect(wb.tabs.map(t => t.paper_id)).toEqual([2])
  })

  it('add and home buttons emit', async () => {
    seeded()
    const wrapper = mount(PaperTabs)
    await wrapper.find('[aria-label="新增论文标签"]').trigger('click')
    await wrapper.find('[aria-label="回到阅读起始页"]').trigger('click')
    expect(wrapper.emitted('add')).toHaveLength(1)
    expect(wrapper.emitted('home')).toHaveLength(1)
  })
})
