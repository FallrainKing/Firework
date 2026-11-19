import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ChatPanel from './ChatPanel.vue'
import { agentApi } from '@/api/agent'
import { workbenchApi } from '@/api/workbench'
import { sessionsApi } from '@/api/sessions'
import { readerApi } from '@/api/reader'
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

  it('enables sending when a session arrives after mounting', async () => {
    const wrapper = mount(ChatPanel, { props: { session: null, paperId: 1 } })
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeDefined()
    await wrapper.setProps({ session })
    await flushPromises()
    await wrapper.find('textarea').setValue('理解这段原文')
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('submits text, image attachment and quoted original in one run', async () => {
    vi.spyOn(agentApi, 'createRun').mockResolvedValue(run())
    vi.spyOn(agentApi, 'getRun').mockResolvedValue(run())
    const wrapper = await mountPanel()
    const vm = wrapper.vm as unknown as { attachments: unknown[]; bridge: { setContext: (c: unknown) => void } }
    vm.attachments = [{ id: 'image-1', url: '/image', filename: '图1.png' }]
    vm.bridge.setContext({ paper_id: 1, page: 3, file_version: 'v', quote: '原文', rects: [] })
    await wrapper.find('textarea').setValue('解释图中方法')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(agentApi.createRun).toHaveBeenCalledWith(expect.objectContaining({ conversation_id: 5, prompt: '解释图中方法', attachment_ids: ['image-1'], contexts: [expect.objectContaining({ page: 3, quote: '原文' })] }))
    wrapper.unmount()
  })

  it('rejects more than 3 images' , async () => {
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

  it('ask reuses the stored pending request_key for identical input', async () => {
    const pending = { conversation_id: 5, prompt: '重复提交', contexts: [], purpose: 'chat', attachment_ids: [], request_key: 'a'.repeat(32) }
    localStorage.setItem('reader-pending-5', JSON.stringify(pending))
    const created: Array<{ request_key: string }> = []
    vi.spyOn(agentApi, 'createRun').mockImplementation(async body => { created.push(body as never); return run({ status: 'queued' }) })
    vi.spyOn(agentApi, 'getRun').mockResolvedValue(run({ status: 'queued' }))
    const wrapper = await mountPanel()
    await wrapper.find('textarea').setValue('重复提交')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(created[0].request_key).toBe('a'.repeat(32))
  })
})

describe('ChatPanel research composer', () => {
  it('shows slash templates and inserts the selected prompt without calling the agent', async () => {
    vi.spyOn(agentApi, 'createRun').mockResolvedValue(run())
    const wrapper = await mountPanel()
    await wrapper.find('textarea').setValue('请/')
    await wrapper.find('textarea').trigger('input')
    expect(wrapper.find('[aria-label="提问模板"]').text()).toContain('快速概览')
    await wrapper.find('[aria-label="提问模板"] button').trigger('mousedown')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toContain('请\n\n请概述当前论文')
    expect(agentApi.createRun).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('adds an authorized paper with @ and sends it as a run context', async () => {
    vi.spyOn(sessionsApi, 'get').mockResolvedValue({ session, papers: [{ id: 2, title: '第二篇论文' }] })
    vi.spyOn(readerApi, 'document').mockResolvedValue({ paper_id: 2, title: '第二篇论文', file_version: 'b'.repeat(64), page_count: 3, width: 600, height: 800, outline: [], pdf_url: '/x' })
    vi.spyOn(agentApi, 'createRun').mockResolvedValue(run())
    const wrapper = await mountPanel()
    await wrapper.find('textarea').setValue('比较 @第二')
    await wrapper.find('textarea').trigger('input')
    await wrapper.find('[aria-label="论文引用"] button').trigger('mousedown')
    await flushPromises()
    expect(wrapper.find('[aria-label="本次提问上下文"]').text()).toContain('第二篇论文')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(agentApi.createRun).toHaveBeenCalledWith(expect.objectContaining({
      conversation_id: 5,
      prompt: '比较',
      contexts: [expect.objectContaining({ paper_id: 2, page: 1, file_version: 'b'.repeat(64) })],
    }))
    wrapper.unmount()
  })

  it('uses one image validation rule for file selection and pasted or dropped images', async () => {
    const wrapper = await mountPanel()
    const vm = wrapper.vm as unknown as { uploadFiles: (files: File[]) => Promise<void> }
    await expect(vm.uploadFiles([new File(['x'], 'x.webp', { type: 'image/webp' })])).rejects.toThrow('PNG 或 JPEG')
    await expect(vm.uploadFiles([new File([largeBody()], 'large.png', { type: 'image/png' })])).rejects.toThrow('5MB')
    expect(wrapper.find('.upload-error').text()).toContain('每张图片不超过 5MB')
    wrapper.unmount()
  })

  it('allows editing the next draft while a run is active', async () => {
    vi.spyOn(agentApi, 'createRun').mockResolvedValue(run({ status: 'running' }))
    vi.spyOn(agentApi, 'getRun').mockResolvedValue(run({ status: 'running' }))
    const wrapper = await mountPanel()
    await wrapper.find('textarea').setValue('第一条')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await wrapper.find('textarea').setValue('运行时下一条草稿')
    expect(wrapper.find('textarea').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeDefined()
    await vi.advanceTimersByTimeAsync(400)
    expect(workbenchApi.saveDraft).toHaveBeenLastCalledWith(5, 1, expect.objectContaining({ prompt: '运行时下一条草稿' }))
    wrapper.unmount()
  })
})

function largeBody() { return new Array(5 * 1024 * 1024 + 1).fill('x').join('') }
