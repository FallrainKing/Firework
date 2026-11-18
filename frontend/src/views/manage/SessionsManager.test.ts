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
})
