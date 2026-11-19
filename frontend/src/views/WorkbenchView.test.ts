import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WorkbenchView from './WorkbenchView.vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useLibraryStore } from '@/stores/library'
import { papersApi } from '@/api/papers'
import { workbenchApi } from '@/api/workbench'
import { agentApi } from '@/api/agent'
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
  it('keeps run cancellation visible when the side navigation is hidden', async () => {
    vi.spyOn(papersApi, 'get').mockResolvedValue({ id: 1, title: '全文论文', has_pdf: true } as never)
    vi.spyOn(agentApi, 'listRuns').mockResolvedValue({ runs: [{ id: 'run-visible', skill: 'chat', status: 'queued', progress: {}, cancelling: false } as never] })
    const wrapper = shell()
    useWorkbenchStore().openPaper(1)
    await flushPromises()
    const panel = wrapper.findComponent({ name: 'ActivityPanel' })
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain('取消')
    wrapper.unmount()
  })

  it('shows domain saving failure and success states', async () => {
    const createCollection = vi.spyOn(useLibraryStore(), 'createCollection')
      .mockRejectedValueOnce(new Error('领域服务不可用'))
      .mockResolvedValue({ id: 1, name: '基础模型', count: 0 } as never)
    const wrapper = shell()
    wrapper.findComponent({ name: 'SideNav' }).vm.$emit('new-domain')
    await flushPromises()
    await wrapper.find('[aria-label="新增论文领域"] input').setValue('基础模型')
    await wrapper.find('[aria-label="新增论文领域"] .primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('保存失败：领域服务不可用')
    expect(wrapper.text()).not.toContain('已保存')
    await wrapper.find('[aria-label="新增论文领域"] .primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已保存')
    expect(createCollection).toHaveBeenCalledTimes(2)
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
