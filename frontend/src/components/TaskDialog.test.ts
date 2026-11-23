import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import {skillAuthoring} from '@/api/skillAuthoring'
import TaskDialog from './TaskDialog.vue'
import { sessionsApi } from '@/api/sessions'
import { papersApi } from '@/api/papers'

const templates = [
  { id: 'read', name: '阅读论文', description: '', kind: 'reading', skill: 'paper_read', prompt: '请阅读关联论文', builtin: 1 },
  { id: 'chat', name: '自由讨论', description: '', kind: 'chat', skill: 'chat', prompt: '', builtin: 1 },
]

beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(skillAuthoring,'available').mockResolvedValue({skills:[]})
  vi.spyOn(sessionsApi, 'templates').mockResolvedValue({ templates, kinds: {}, skills: [] })
  vi.spyOn(sessionsApi, 'categories').mockResolvedValue({ categories: [{ id: 1, name: '方法精读' }] })
  vi.spyOn(sessionsApi, 'list').mockResolvedValue({ sessions: [] })
  vi.spyOn(papersApi, 'list').mockResolvedValue({ papers: [{ id: 1, title: 'Attention', has_pdf: true }, { id: 2, title: 'Diffusion', has_pdf: true }] } as never)
})

async function mountDialog(props: { mode: 'read' | 'compare' | 'chat' | 'review'; templateId?: string; paperIds?: number[]; question?: string } = { mode: 'read' }) {
  const wrapper = mount(TaskDialog, { props })
  await flushPromises()
  return wrapper
}

describe('TaskDialog', () => {
  it('selecting template fills starting prompt', async () => {
    const wrapper = await mountDialog()
    await wrapper.find('select[data-field="template"]').setValue('read')
    expect((wrapper.find('textarea[data-field="prompt"]').element as HTMLTextAreaElement).value).toBe('请阅读关联论文')
  })

  it('inline category creation keeps inputs and selects new item', async () => {
    const created = { id: 9, name: '新分类' }
    vi.spyOn(sessionsApi, 'createCategory').mockResolvedValue(created)
    const wrapper = await mountDialog()
    await wrapper.find('input[data-field="title"]').setValue('我的任务')
    await wrapper.find('button[data-action="new-category"]').trigger('click')
    await wrapper.find('input[data-field="new-category-name"]').setValue('新分类')
    await wrapper.find('button[data-action="confirm-category"]').trigger('click')
    await flushPromises()
    expect(sessionsApi.createCategory).toHaveBeenCalledWith('新分类')
    expect((wrapper.find('input[data-field="title"]').element as HTMLInputElement).value).toBe('我的任务')
    expect((wrapper.find('select[data-field="category"]').element as HTMLSelectElement).value).toBe('9')
  })

  it('compare mode requires at least two papers', async () => {
    const wrapper = await mountDialog({ mode: 'compare' })
    const create = wrapper.find('button[data-action="create"]')
    expect(create.attributes('disabled')).toBeDefined()
    await wrapper.findAll('input[type="checkbox"]')[0].setValue(true)
    expect(create.attributes('disabled')).toBeDefined()
    await wrapper.findAll('input[type="checkbox"]')[1].setValue(true)
    expect(create.attributes('disabled')).toBeUndefined()
  })

  it('created emits session and starting prompt', async () => {
    const session = { id: 5, title: 't', draft_prompt: '' }
    vi.spyOn(sessionsApi, 'create').mockResolvedValue({ session: session as never, starting_prompt: '请阅读关联论文' })
    const wrapper = await mountDialog()
    await wrapper.find('select[data-field="template"]').setValue('read')
    await wrapper.findAll('input[type="checkbox"]')[0].setValue(true)
    await wrapper.find('button[data-action="create"]').trigger('click')
    await flushPromises()
    const emitted = wrapper.emitted('created')
    expect(emitted).toHaveLength(1)
    expect(emitted![0][0]).toMatchObject({ id: 5 })
    expect(emitted![0][1]).toBe('请阅读关联论文')
  })

  it('create button disabled while request pending', async () => {
    let resolve!: (v: { session: import('@/api/types').Session; starting_prompt: string }) => void
    vi.spyOn(sessionsApi, 'create').mockImplementation(() => new Promise(r => { resolve = r }))
    const wrapper = await mountDialog({ mode: 'chat' })
    await wrapper.find('button[data-action="create"]').trigger('click')
    expect(wrapper.find('button[data-action="create"]').attributes('disabled')).toBeDefined()
    resolve({ session: { id: 6 } as import('@/api/types').Session, starting_prompt: '' })
    await flushPromises()
  })
})
