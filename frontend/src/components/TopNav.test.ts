import { beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import TopNav from './TopNav.vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { meApi } from '@/api/me'
import { workbenchApi } from '@/api/workbench'

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.spyOn(meApi, 'profile').mockResolvedValue({ display_name: '研究用户' } as never)
  vi.spyOn(workbenchApi, 'saveState').mockImplementation(async (_, state) => state)
})
it('the brand returns from a paper deep link to the explicit home and retains open papers', async () => {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/reader/:paperId', component: { template: '<div />' } },
  ] })
  await router.push('/reader/19')
  const wb = useWorkbenchStore()
  wb.openPaper(19, 5)
  wb.setView('library')
  const wrapper = mount(TopNav, { global: { plugins: [router] } })
  await flushPromises()
  await wrapper.find('.work-brand').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.fullPath).toBe('/?home=1')
  expect(wb.view).toBe('read')
  expect(wb.activePaperId).toBeNull()
  expect(wb.tabs).toEqual([{ paper_id: 19, session_id: 5 }])
  wrapper.unmount()
  vi.restoreAllMocks()
})
