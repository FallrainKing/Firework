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
