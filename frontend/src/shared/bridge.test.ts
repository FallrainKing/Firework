import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { attachBridge, requestSave, sendLayout } from './bridge'
import type { Layout } from '@/api/types'

function fakeFrame() {
  const posted: Array<{ message: unknown; origin: string }> = []
  const win = { postMessage: (message: unknown, origin: string) => posted.push({ message, origin }) }
  return { frame: { contentWindow: win } as unknown as HTMLIFrameElement, win, posted }
}

function dispatch(data: unknown, source: unknown, origin = location.origin) {
  window.dispatchEvent(new MessageEvent('message', { data, source: source as Window, origin }))
}

const layout: Layout = { left_width: 235, right_width: 340, left_hidden: false, right_hidden: false }

let detach: (() => void) | null = null
beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { detach?.(); detach = null; vi.useRealTimers() })

describe('bridge', () => {
  it('ignores wrong origin and unregistered source', () => {
    const { frame, win } = fakeFrame()
    const onSession = vi.fn()
    detach = attachBridge(() => [frame], { onSession })
    dispatch({ type: 'reader-session', paper_id: 1, session_id: 9 }, win, 'http://evil.example')
    dispatch({ type: 'reader-session', paper_id: 1, session_id: 9 }, {})
    expect(onSession).not.toHaveBeenCalled()
  })

  it('dispatches reader-session from registered frame', () => {
    const { frame, win } = fakeFrame()
    const onSession = vi.fn()
    detach = attachBridge(() => [frame], { onSession })
    dispatch({ type: 'reader-session', paper_id: 1, session_id: 9 }, win)
    expect(onSession).toHaveBeenCalledWith(1, 9)
  })

  it('requestSave resolves on matching reader-saved', async () => {
    const { frame, win, posted } = fakeFrame()
    detach = attachBridge(() => [frame], {})
    const promise = requestSave(frame)
    expect(posted[0].message).toMatchObject({ type: 'save-reader' })
    expect(posted[0].origin).toBe(location.origin)
    const requestId = (posted[0].message as { request_id: string }).request_id
    dispatch({ type: 'reader-saved', request_id: requestId }, win)
    await expect(promise).resolves.toBe(true)
  })

  it('requestSave falls back false on timeout', async () => {
    const { frame } = fakeFrame()
    detach = attachBridge(() => [frame], {})
    const promise = requestSave(frame, 2000)
    await vi.advanceTimersByTimeAsync(2000)
    await expect(promise).resolves.toBe(false)
  })

  it('reader-saved from another window does not resolve', async () => {
    const { frame } = fakeFrame()
    const other = fakeFrame()
    detach = attachBridge(() => [frame, other.frame], {})
    const promise = requestSave(frame, 2000)
    const requestId = (other.posted.length ? other.posted : [{ message: { request_id: 'x' } }])[0]
    dispatch({ type: 'reader-saved', request_id: 'wrong-id' }, other.win)
    await vi.advanceTimersByTimeAsync(2000)
    await expect(promise).resolves.toBe(false)
  })

  it('sendLayout posts to frame with origin', () => {
    const { frame, posted } = fakeFrame()
    sendLayout(frame, layout)
    expect(posted[0]).toEqual({ message: { type: 'reader-layout', layout }, origin: location.origin })
  })
})
