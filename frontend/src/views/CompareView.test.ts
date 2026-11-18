import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import CompareView from './CompareView.vue'
import { sessionsApi } from '@/api/sessions'
import { papersApi } from '@/api/papers'
import { useWorkbenchStore } from '@/stores/workbench'
import { workbenchApi } from '@/api/workbench'

const comparisons = [
  { id: 7, title: '方法对比', kind: 'comparison', skill: 'paper_compare', paper_ids: [1, 2], last_status: 'succeeded', preview: '比较结果', archived: false },
]

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.spyOn(sessionsApi, 'list').mockResolvedValue({ sessions: comparisons } as never)
  vi.spyOn(sessionsApi, 'templates').mockResolvedValue({ templates: [], kinds: {}, skills: [] })
  vi.spyOn(sessionsApi, 'categories').mockResolvedValue({ categories: [] })
  vi.spyOn(papersApi, 'list').mockResolvedValue({ papers: [], total: 0, offset: 0, has_more: false })
  vi.spyOn(workbenchApi, 'saveState').mockImplementation(async (_id, s) => s)
})

describe('CompareView', () => {
  it('renders comparison sessions', async () => {
    const wrapper = mount(CompareView)
    await flushPromises()
    expect(wrapper.text()).toContain('方法对比')
    expect(sessionsApi.list).toHaveBeenCalledWith(expect.objectContaining({ kind: 'comparison' }))
  })

  it('new comparison opens task dialog in compare mode', async () => {
    const wrapper = mount(CompareView)
    await flushPromises()
    await wrapper.find('button[data-action="new"]').trigger('click')
    expect(wrapper.findComponent({ name: 'TaskDialog' }).exists() || wrapper.find('[role="dialog"]').exists()).toBe(true)
  })

  it('clicking session opens its paper tabs', async () => {
    const wb = useWorkbenchStore()
    const wrapper = mount(CompareView)
    await flushPromises()
    await wrapper.find('[data-action="open"]').trigger('click')
    expect(wb.tabs.map(t => t.paper_id)).toEqual([1, 2])
    expect(wb.tabs.every(t => t.session_id === 7)).toBe(true)
    expect(wb.view).toBe('read')
  })

  it('rebinds already-open papers to the comparison session', async () => {
    const wb = useWorkbenchStore()
    wb.tabs = [{ paper_id: 1, session_id: 10 }]
    wb.activePaperId = 1
    const wrapper = mount(CompareView)
    await flushPromises()
    await wrapper.find('[data-action="open"]').trigger('click')
    expect(wb.tabs.find(t => t.paper_id === 1)?.session_id).toBe(7)
    expect(wb.tabs.find(t => t.paper_id === 2)?.session_id).toBe(7)
  })
})
