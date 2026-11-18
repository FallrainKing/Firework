import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WorkbenchView from './WorkbenchView.vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useLibraryStore } from '@/stores/library'
import { papersApi } from '@/api/papers'
import { workbenchApi } from '@/api/workbench'
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {}, params: {} }) }))

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.spyOn(useWorkbenchStore(), 'load').mockResolvedValue()
  vi.spyOn(useLibraryStore(), 'refresh').mockResolvedValue()
  vi.spyOn(workbenchApi, 'saveState').mockImplementation(async (_, s) => s)
})
afterEach(() => vi.restoreAllMocks())
function shell() {
  return mount(WorkbenchView, { global: { stubs: {
    TopNav: true, SideNav: true, PaperTabs: true, ImportOverlay: true, TaskDialog: true,
    WelcomeView: true, ReadingView: true, LibraryView: true, CompareView: true, SchedulesView: true, OpenPaperDialog: true,
  } } })
}
describe('reading full-text boundary', () => {
  it('metadata-only paper shows PDF import and never mounts its agent reader', async () => {
    vi.spyOn(papersApi, 'get').mockResolvedValue({ id: 8, title: '书目论文', has_pdf: false } as never)
    const wrapper = shell()
    useWorkbenchStore().openPaper(8)
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ReadingView' }).props('paperId')).toBeNull()
    expect(wrapper.text()).toContain('为这篇论文补充 PDF')
    await wrapper.find('.fulltext-gate button.primary').trigger('click')
    expect(wrapper.findComponent({ name: 'ImportOverlay' }).props('targetPaperId')).toBe(8)
    wrapper.unmount()
  })
  it('switching quickly discards a stale full-text result', async () => {
    let resolveFirst!: (p: never) => void
    vi.spyOn(papersApi, 'get').mockImplementation(id => id === 1
      ? new Promise(resolve => { resolveFirst = resolve })
      : Promise.resolve({ id: 2, title: '第二篇', has_pdf: true } as never))
    const wrapper = shell()
    const wb = useWorkbenchStore()
    wb.openPaper(1)
    await flushPromises()
    wb.openPaper(2)
    await flushPromises()
    resolveFirst({ id: 1, title: '旧结果', has_pdf: false } as never)
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ReadingView' }).props('paperId')).toBe(2)
    expect(wrapper.find('.fulltext-gate').exists()).toBe(false)
    wrapper.unmount()
  })
  it('plus opens a paper picker instead of creating a conversation', async () => {
    const wrapper = shell()
    wrapper.findComponent({ name: 'PaperTabs' }).vm.$emit('add')
    await flushPromises()
    expect(wrapper.findComponent({ name: 'OpenPaperDialog' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'TaskDialog' }).exists()).toBe(false)
    wrapper.unmount()
  })
})
