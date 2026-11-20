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

it('creates a child in the explicitly chosen parent and renders a collapsible tree',async()=>{
 const groups=[{id:1,name:'Root',parent_id:null,path:'Root'},{id:2,name:'Other',parent_id:null,path:'Other'},{id:3,name:'Child',parent_id:1,path:'Root / Child'}]
 vi.mocked(papersApi.collections).mockResolvedValue({collections:groups})
 const create=vi.spyOn(papersApi,'createCollection').mockResolvedValue({id:4,name:'New',parent_id:3,path:'Root / Child / New'})
 const w=mount(LibraryView);await flushPromises()
 expect(w.findAll('[role="treeitem"]').map(n=>n.attributes('aria-level'))).toEqual(['1','2','1'])
 await w.find('[aria-label="收起Root"]').trigger('click');expect(w.findAll('[role="treeitem"]')).toHaveLength(2)
 await w.find('[aria-label="展开Root"]').trigger('click')
 await w.find('[aria-label="在Root / Child下新建子分类"]').trigger('click')
 expect((w.find('[aria-label="新分类的父分类"]').element as HTMLSelectElement).value).toBe('3')
 await w.find('[aria-label="新增资料分类"]').setValue('New')
 await w.find('.category-create').trigger('submit');await flushPromises()
 expect(create).toHaveBeenCalledWith('New',3)
 expect(w.emitted('library-updated')).toBeTruthy()
})
