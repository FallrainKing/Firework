import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ReadingView from './ReadingView.vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { workbenchApi } from '@/api/workbench'

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.useFakeTimers()
  vi.spyOn(workbenchApi, 'saveState').mockImplementation(async (_id, s) => s)
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

async function mountReader(paperId: number | null, sessionId: number | null = null) {
  const wrapper = mount(ReadingView, { props: { paperId, sessionId } })
  await flushPromises()
  return wrapper
}

async function switchTo(wrapper: ReturnType<typeof mount>, paperId: number, sessionId: number | null = null) {
  await wrapper.setProps({ paperId, sessionId })
  // 驱逐时的 requestSave 走 2s 超时兜底
  await vi.advanceTimersByTimeAsync(2100)
  await flushPromises()
}

describe('ReadingView iframe pool', () => {
  it('loads one frame per paper and caps at 3', async () => {
    const wrapper = await mountReader(1)
    expect(wrapper.findAll('iframe')).toHaveLength(1)
    await switchTo(wrapper, 2)
    await switchTo(wrapper, 3)
    expect(wrapper.findAll('iframe')).toHaveLength(3)
    await switchTo(wrapper, 4)
    expect(wrapper.findAll('iframe')).toHaveLength(3)
    // 活动帧始终在池中
    expect(wrapper.findAll('iframe').some(f => f.attributes('src')?.includes('paper_id=4'))).toBe(true)
  })

  it('never evicts the active paper under rapid switching', async () => {
    const wrapper = await mountReader(1)
    await switchTo(wrapper, 2)
    await switchTo(wrapper, 3)
    // 快速 1→2→1：1 曾被加载，切换不应把活动帧驱逐
    await wrapper.setProps({ paperId: 1 })
    await vi.advanceTimersByTimeAsync(2100)
    await flushPromises()
    const srcs = wrapper.findAll('iframe').map(f => f.attributes('src') ?? '')
    expect(srcs.some(s => s.includes('paper_id=1'))).toBe(true)
    expect(wrapper.findAll('iframe').length).toBeLessThanOrEqual(3)
  })

  it('rebinds session by reloading the frame with new session_id', async () => {
    const wrapper = await mountReader(1, 10)
    expect(wrapper.find('iframe').attributes('src')).toContain('session_id=10')
    await wrapper.setProps({ sessionId: 20 })
    await vi.advanceTimersByTimeAsync(2100)
    await flushPromises()
    const srcs = wrapper.findAll('iframe').map(f => f.attributes('src') ?? '')
    expect(srcs.some(s => s.includes('paper_id=1') && s.includes('session_id=20'))).toBe(true)
    expect(srcs.some(s => s.includes('session_id=10'))).toBe(false)
  })

  it('emits save-timeout when eviction save does not answer', async () => {
    const wrapper = await mountReader(1)
    await switchTo(wrapper, 2)
    await switchTo(wrapper, 3)
    await switchTo(wrapper, 4)
    expect(wrapper.emitted('save-timeout')).toBeTruthy()
  })

  it('keeps pool mounted when paperId becomes null (home)', async () => {
    const wrapper = await mountReader(1)
    await wrapper.setProps({ paperId: null })
    await flushPromises()
    expect(wrapper.findAll('iframe')).toHaveLength(1)
    expect(wrapper.find('.reading-frames').isVisible()).toBe(false)
  })
})
