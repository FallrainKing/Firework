import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SideNav from './SideNav.vue'
import ActivityPanel from './ActivityPanel.vue'
import { useLibraryStore } from '@/stores/library'
import { sessionsApi } from '@/api/sessions'
import type { Session } from '@/api/types'

vi.mock('./ActivityPanel.vue', () => ({ default: { name: 'ActivityPanel', template: '<div />' } }))

function session(overrides: Partial<Session> = {}): Session {
  return {
    id: 1,
    title: '方法精读',
    kind: 'reading',
    skill: 'chat',
    skill_version_id: null,
    category_id: null,
    template_id: null,
    native_session_id: null,
    native_ready: false,
    archived: false,
    pinned: false,
    draft_prompt: '',
    created_at: '',
    updated_at: '',
    paper_ids: [1],
    run_count: 2,
    last_status: 'succeeded',
    preview: '',
    ...overrides,
  }
}

const sessions = [
  session(),
  session({ id: 2, title: '实验审查', last_status: 'running', run_count: 3 }),
  session({ id: 3, title: '无论文任务', paper_ids: [] }),
]

async function mountNav() {
  const wrapper = mount(SideNav, {
    global: {
      stubs: { teleport: true },
    },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  const lib = useLibraryStore()
  lib.papersById = {
    1: { id: 1, title: '第一篇论文', has_pdf: true } as never,
  }
  lib.recent = [{ paper_id: 1, conversation_id: 1, updated_at: '' }]
  lib.collections = []
  vi.spyOn(useLibraryStore(), 'refresh').mockResolvedValue()
  vi.spyOn(sessionsApi, 'list').mockResolvedValue({ sessions })
  vi.spyOn(sessionsApi, 'update').mockImplementation(async (_id, patch) => ({ ...sessions[0], ...patch }))
})

afterEach(() => vi.restoreAllMocks())

describe('SideNav', () => {
  it('switches between papers and sessions without creating a run', async () => {
    const wrapper = await mountNav()
    expect(wrapper.text()).toContain('最近阅读')
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('方法精读')
    expect(wrapper.text()).toContain('第一篇论文')
    expect(sessionsApi.list).toHaveBeenCalledTimes(2)
  })

  it('opens a paper without a session and a task with the exact session', async () => {
    const wrapper = await mountNav()
    const emitted = () => wrapper.emitted<{ 'open-paper': Array<[number, number | undefined]> }>('open-paper')
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    await flushPromises()
    await wrapper.find('.paper-head').trigger('click')
    await wrapper.find('.session-open').trigger('click')
    expect(emitted()?.at(-2)).toEqual([1, undefined])
    expect(emitted()?.at(-1)).toEqual([1, 1])
  })

  it('searches and filters tasks locally', async () => {
    const wrapper = await mountNav()
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    await flushPromises()
    await wrapper.find('[aria-label="搜索任务或运行内容"]').setValue('实验')
    expect(wrapper.text()).toContain('实验审查')
    expect(wrapper.text()).not.toContain('方法精读')
    await wrapper.find('[aria-label="会话筛选"]').findAll('button')[2].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('实验审查')
    expect(wrapper.text()).not.toContain('无论文任务')
  })

  it('renames, pins and archives through the session API', async () => {
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('新任务名')
    const wrapper = await mountNav()
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    await flushPromises()
    const [first] = wrapper.findAll('.session-item')
    await first.findAll('.session-actions button')[0].trigger('click')
    await flushPromises()
    expect(sessionsApi.update).toHaveBeenCalledWith(1, { title: '新任务名' })
    await first.findAll('.session-actions button')[1].trigger('click')
    await flushPromises()
    expect(sessionsApi.update).toHaveBeenCalledWith(1, { pinned: true })
    await first.findAll('.session-actions button')[2].trigger('click')
    await flushPromises()
    expect(sessionsApi.update).toHaveBeenCalledWith(1, { archived: true })
    prompt.mockRestore()
  })
})
