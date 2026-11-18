import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ChatPanel from './ChatPanel.vue'
import { agentApi } from '@/api/agent'
import { workbenchApi } from '@/api/workbench'
import { sessionsApi } from '@/api/sessions'
import type { Run, Session } from '@/api/types'

const session = { id: 5, title: '阅读', skill: 'paper_read', paper_ids: [1], native_ready: true, draft_prompt: '起始问题', archived: false } as Session

function run(overrides: Partial<Run> = {}): Run {
  return { id: 'r1', request_key: 'k', conversation_id: 5, skill: 'paper_read', skill_version: '', prompt: '问题', status: 'succeeded', answer: '答案', model: null, usage: {}, tool_calls: [], metadata: {}, contexts: [], attachment_ids: [], progress: {}, purpose: 'chat', cli_estimated_cost_usd: null, cost_verified: false, error: null, created_at: '', finished_at: null, ...overrides }
}

const orch = { jump: vi.fn(), refreshAnnotations: vi.fn(async () => {}), savePosition: vi.fn() }

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.useFakeTimers()
  vi.spyOn(sessionsApi, 'runs').mockResolvedValue({ runs: [], has_more: false, next_before: null })
  vi.spyOn(sessionsApi, 'templates').mockResolvedValue({ templates: [], kinds: {}, skills: [] })
  vi.spyOn(sessionsApi, 'get').mockResolvedValue({ session, papers: [] })
  vi.spyOn(workbenchApi, 'getDraft').mockResolvedValue({ prompt: '', context: null, attachment_ids: [], attachments: [] })
  vi.spyOn(workbenchApi, 'saveDraft').mockResolvedValue({ saved: true })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

async function mountPanel() {
  const wrapper = mount(ChatPanel, { props: { session, paperId: 1, orchestrator: orch as never } })
  await flushPromises()
  return wrapper
}

describe('ChatPanel', () => {
  it('ask reuses pending request_key from localStorage', async () => {
    const created: unknown[] = []
    vi.spyOn(agentApi, 'createRun').mockImplementation(async body => { created.push(body); return run({ status: 'queued' }) })
    vi.spyOn(agentApi, 'getRun').mockResolvedValueOnce(run({ status: 'queued' })).mockResolvedValue(run())
    const wrapper = await mountPanel()
    await wrapper.find('textarea').setValue('解释方法')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const key = (created[0] as { request_key: string }).request_key
    expect(localStorage.getItem('reader-pending-5')).toContain(key)
    // 终态后 pending 清除
    await vi.advanceTimersByTimeAsync(2100)
    expect(localStorage.getItem('reader-pending-5')).toBeNull()
  })

  it('watch stops at cancelled terminal', async () => {
    vi.spyOn(agentApi, 'getRun').mockResolvedValue(run({ status: 'cancelled' }))
    const wrapper = await mountPanel()
    const bridge = (wrapper.vm as unknown as { bridge: { watch: (id: string) => void } }).bridge
    bridge.watch('r9')
    await vi.advanceTimersByTimeAsync(2100)
    expect(agentApi.getRun).toHaveBeenCalledTimes(1)
  })

  it('draft saves debounce-merged after 400ms', async () => {
    const wrapper = await mountPanel()
    await wrapper.find('textarea').setValue('一')
    await wrapper.find('textarea').setValue('一二')
    expect(workbenchApi.saveDraft).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(400)
    expect(workbenchApi.saveDraft).toHaveBeenCalledTimes(1)
    expect(vi.mocked(workbenchApi.saveDraft).mock.calls[0][2]).toMatchObject({ prompt: '一二' })
  })

  it('rejects more than 3 images', async () => {
    const wrapper = await mountPanel()
    const vm = wrapper.vm as unknown as { attachments: unknown[]; uploadFiles: (files: File[]) => Promise<void> }
    vm.attachments = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]
    await expect(vm.uploadFiles([new File(['x'], 'x.png', { type: 'image/png' })])).rejects.toThrow('3 张')
  })

  it('re-edit restores prompt and context from failed run', async () => {
    vi.spyOn(sessionsApi, 'runs').mockResolvedValue({ runs: [run({ status: 'failed', prompt: '原问题', error: '失败', contexts: [{ paper_id: 1, page: 2, file_version: 'v', quote: 'q', rects: [] }] })], has_more: false, next_before: null })
    const wrapper = await mountPanel()
    await wrapper.find('button.reedit').trigger('click')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('原问题')
  })

  it('empty session shows draft_prompt as starting question', async () => {
    const wrapper = await mountPanel()
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('起始问题')
  })
})
