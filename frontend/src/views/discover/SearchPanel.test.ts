import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SearchPanel from './SearchPanel.vue'
import { agentApi } from '@/api/agent'
import { sessionsApi } from '@/api/sessions'
import { importsApi } from '@/api/imports'

beforeEach(() => {
  sessionStorage.clear()
  setActivePinia(createPinia())
  vi.useFakeTimers()
  vi.spyOn(sessionsApi, 'create').mockResolvedValue({ session: { id: 9 }, starting_prompt: '' } as never)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('SearchPanel', () => {
  it('search creates discover session and renders tool results', async () => {
    vi.spyOn(agentApi, 'createRun').mockResolvedValue({ id: 'r1' } as never)
    vi.spyOn(agentApi, 'getRun').mockResolvedValue({ id: 'r1', status: 'succeeded', error: null, tool_calls: [{ ok: true, tool: 'paper_search', result: { papers: [{ title: 'Found Paper', arxiv_id: '2401.00001', authors: ['A'] }] } }] } as never)
    const wrapper = mount(SearchPanel)
    await wrapper.find('input').setValue('diffusion policy')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(sessionsApi.create).toHaveBeenCalledWith(expect.objectContaining({ template_id: 'discover' }))
    expect(wrapper.text()).toContain('Found Paper')
  })

  it('shows a retryable search error instead of an empty list', async () => {
    const create = vi.spyOn(sessionsApi, 'create')
      .mockRejectedValueOnce(new Error('网络断开'))
      .mockResolvedValue({ session: { id: 9 }, starting_prompt: '' } as never)
    vi.spyOn(agentApi, 'createRun').mockResolvedValue({ id: 'r2' } as never)
    vi.spyOn(agentApi, 'getRun').mockResolvedValue({ id: 'r2', status: 'succeeded', error: null, tool_calls: [{ ok: true, tool: 'paper_search', result: { papers: [{ title: 'Retry Paper', arxiv_id: '2401.00002' }] } }] } as never)
    const wrapper = mount(SearchPanel)
    await wrapper.find('input').setValue('retry query')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('网络断开')
    expect(wrapper.text()).toContain('重试')
    expect(wrapper.text()).not.toContain('输入关键词开始搜索。')
    await wrapper.find('.state-feedback .error button').trigger('click')
    await flushPromises()
    expect(create).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('Retry Paper')
  })

  it('shows save failure without a success message', async () => {
    vi.spyOn(agentApi, 'createRun').mockResolvedValue({ id: 'r3' } as never)
    vi.spyOn(agentApi, 'getRun').mockResolvedValue({ id: 'r3', status: 'succeeded', error: null, tool_calls: [{ ok: true, tool: 'paper_search', result: { papers: [{ title: 'Found', arxiv_id: '2401.00003' }] } }] } as never)
    vi.spyOn(importsApi, 'source').mockRejectedValueOnce(new Error('入库服务不可用'))
    const wrapper = mount(SearchPanel)
    await wrapper.find('input').setValue('q')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await wrapper.find('.result-actions button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('保存失败：入库服务不可用')
    expect(wrapper.text()).not.toContain('已提交入库')
  })

  it('add to library submits import source', async () => {
    vi.spyOn(agentApi, 'createRun').mockResolvedValue({ id: 'r1' } as never)
    vi.spyOn(agentApi, 'getRun').mockResolvedValue({ id: 'r1', status: 'succeeded', error: null, tool_calls: [{ ok: true, tool: 'paper_search', result: { papers: [{ title: 'Found', arxiv_id: '2401.00001' }] } }] } as never)
    vi.spyOn(importsApi, 'source').mockResolvedValue({ id: 'i1' } as never)
    const wrapper = mount(SearchPanel)
    await wrapper.find('input').setValue('q')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await wrapper.find('.result-actions button').trigger('click')
    await flushPromises()
    expect(importsApi.source).toHaveBeenCalledWith(expect.objectContaining({ value: '2401.00001' }))
    expect(wrapper.emitted('library-updated')).toBeTruthy()
  })
})
