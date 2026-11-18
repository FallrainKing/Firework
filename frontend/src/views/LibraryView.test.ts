import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import LibraryView from './LibraryView.vue'
import { papersApi } from '@/api/papers'
import { sessionsApi } from '@/api/sessions'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(papersApi, 'list').mockResolvedValue({ papers: [], total: 0, offset: 0, has_more: false })
  vi.spyOn(papersApi, 'collections').mockResolvedValue({ collections: [] })
  vi.spyOn(sessionsApi, 'list').mockResolvedValue({ sessions: [] })
  vi.spyOn(sessionsApi, 'get').mockResolvedValue({ session: { id: 5, title: 'x', paper_ids: [], archived: false, pinned: false, kind: 'chat', draft_prompt: '', native_ready: false }, papers: [] } as never)
  vi.spyOn(sessionsApi, 'runs').mockResolvedValue({ runs: [], has_more: false, next_before: null })
  vi.spyOn(sessionsApi, 'templates').mockResolvedValue({ templates: [], kinds: {}, skills: [] })
  vi.spyOn(sessionsApi, 'categories').mockResolvedValue({ categories: [] })
})

describe('LibraryView manage container', () => {
  it('defaults to library grid without iframes', async () => {
    const wrapper = mount(LibraryView)
    await flushPromises()
    expect(wrapper.findComponent({ name: 'LibraryGrid' }).exists() || wrapper.text()).toBeTruthy()
    expect(wrapper.find('iframe').exists()).toBe(false)
    expect(wrapper.find('.paper-grid').exists()).toBe(true)
  })

  it('sessionId prop opens sessions page', async () => {
    const wrapper = mount(LibraryView, { props: { sessionId: 5 } })
    await flushPromises()
    expect(wrapper.find('.sessions-manager').exists()).toBe(true)
  })

  it('tab switch shows sessions manager', async () => {
    const wrapper = mount(LibraryView)
    await flushPromises()
    await wrapper.findAll('.manage-nav button')[1].trigger('click')
    expect(wrapper.find('.sessions-manager').exists()).toBe(true)
  })
})
