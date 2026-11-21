import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SessionsManager from './SessionsManager.vue'
import { sessionsApi } from '@/api/sessions'
import { agentApi } from '@/api/agent'

const session = { id: 5, title: '阅读会话', kind: 'reading', skill: 'paper_read', paper_ids: [1], run_count: 2, last_status: 'succeeded', preview: 'p', archived: false, pinned: false, native_ready: true, native_session_id: 'n', draft_prompt: '', category_id: null, template_id: 'read', created_at: '', updated_at: '' }
const run = { id: 'r1', request_key: 'k', conversation_id: 5, skill: 'paper_read', skill_version: '', prompt: '问题', status: 'succeeded', answer: '答案', model: null, usage: {}, tool_calls: [], metadata: {}, contexts: [], attachment_ids: [], progress: {}, purpose: 'chat', cli_estimated_cost_usd: null, cost_verified: false, error: null, created_at: '', finished_at: null }

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.spyOn(sessionsApi, 'list').mockResolvedValue({ sessions: [session] } as never)
  vi.spyOn(sessionsApi, 'get').mockResolvedValue({ session, papers: [{ id: 1, title: 'Attention' }] } as never)
  vi.spyOn(sessionsApi, 'runs').mockResolvedValue({ runs: [run], has_more: true, next_before: 42 } as never)
  vi.spyOn(sessionsApi, 'update').mockResolvedValue(session as never)
  vi.spyOn(sessionsApi, 'templates').mockResolvedValue({ templates: [], kinds: { reading: '阅读' }, skills: [] })
  vi.spyOn(sessionsApi, 'categories').mockResolvedValue({ categories: [] })
  vi.spyOn(agentApi, 'getRun').mockResolvedValue(run as never)
})

async function mountManager() {
  const wrapper = mount(SessionsManager)
  await flushPromises()
  return wrapper
}

describe('SessionsManager', () => {
  it('prioritizes active and failed sessions and filters locally without starting tasks', async () => {
    vi.spyOn(sessionsApi, 'list').mockResolvedValue({ sessions: [
      session, { ...session, id: 6, title: '失败会话', last_status: 'failed', preview: '需要调整额度' },
      { ...session, id: 7, title: '执行会话', last_status: 'running', draft_prompt: '继续检查' },
    ] } as never)
    const create = vi.spyOn(agentApi, 'createRun')
    const wrapper = await mountManager()
    expect(wrapper.findAll('.session-item').map(x => x.text())).toEqual([
      expect.stringContaining('执行会话'), expect.stringContaining('失败会话'), expect.stringContaining('阅读会话'),
    ])
    await wrapper.findAll('.status-filters button')[2].trigger('click')
    expect(wrapper.findAll('.session-item')).toHaveLength(1)
    expect(wrapper.find('.session-preview').text()).toBe('需要调整额度')
    expect(sessionsApi.list).toHaveBeenCalledTimes(1)
    expect(create).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('lists sessions and opens conversation', async () => {
    const wrapper = await mountManager()
    expect(wrapper.text()).toContain('阅读会话')
    await wrapper.find('button.session-item').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('问题')
    expect(wrapper.text()).toContain('答案')
  })

  it('paper chip emits open-paper with session', async () => {
    const wrapper = await mountManager()
    await wrapper.find('button.session-item').trigger('click')
    await flushPromises()
    await wrapper.find('button.paper-chip').trigger('click')
    expect(wrapper.emitted('open-paper')?.[0]).toEqual([1, 5])
  })

  it('archive toggle calls update', async () => {
    const wrapper = await mountManager()
    await wrapper.find('button.session-item').trigger('click')
    await flushPromises()
    await wrapper.find('button.archive-session').trigger('click')
    await flushPromises()
    expect(sessionsApi.update).toHaveBeenCalledWith(5, { archived: true })
  })

  it('load older runs uses next_before cursor', async () => {
    const wrapper = await mountManager()
    await wrapper.find('button.session-item').trigger('click')
    await flushPromises()
    await wrapper.find('button.load-older').trigger('click')
    await flushPromises()
    expect(sessionsApi.runs).toHaveBeenLastCalledWith(5, 42)
  })

  it('busy is per-session: idle session composer stays enabled while another runs', async () => {
    const sessionB = { ...session, id: 6, title: '空闲会话', paper_ids: [] }
    vi.spyOn(sessionsApi, 'list').mockResolvedValue({ sessions: [session, sessionB] } as never)
    vi.spyOn(sessionsApi, 'runs').mockImplementation(async (id: number) =>
      id === 5 ? { runs: [{ ...run, status: 'running' }], has_more: false, next_before: null } as never : { runs: [], has_more: false, next_before: null } as never)
    vi.spyOn(sessionsApi, 'get').mockImplementation(async (id: number) =>
      ({ session: id === 5 ? session : sessionB, papers: [] }) as never)
    vi.spyOn(agentApi, 'getRun').mockResolvedValue({ ...run, status: 'running' } as never)
    const wrapper = await mountManager()
    const items = wrapper.findAll('button.session-item')
    await items[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.composer textarea').attributes('disabled')).toBeDefined()
    await items[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('.composer textarea').attributes('disabled')).toBeUndefined()
  })
})
