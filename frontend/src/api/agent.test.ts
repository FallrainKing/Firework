import { afterEach, describe, expect, it, vi } from 'vitest'
import { agentApi } from './agent'

afterEach(() => vi.unstubAllGlobals())

function mockFetch(body: unknown) {
  const fn = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(body), { status: 202, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('agent api', () => {
  it('createRun generates a 32-hex request_key', async () => {
    const fn = mockFetch({ id: 'r1', status: 'queued' })
    await agentApi.createRun({ prompt: 'hi', conversation_id: 1 })
    const sent = JSON.parse((fn.mock.calls[0][1] as RequestInit).body as string)
    expect(sent.request_key).toMatch(/^[a-f0-9]{32}$/)
    expect(sent.prompt).toBe('hi')
  })

  it('createRun keeps caller request_key', async () => {
    const fn = mockFetch({ id: 'r1' })
    await agentApi.createRun({ prompt: 'hi', request_key: 'k' })
    const sent = JSON.parse((fn.mock.calls[0][1] as RequestInit).body as string)
    expect(sent.request_key).toBe('k')
  })

  it('cancelRun posts to the cancel path', async () => {
    const fn = mockFetch({ id: 'r1', status: 'cancelled' })
    await agentApi.cancelRun('r1')
    expect(fn.mock.calls[0][0]).toBe('/api/agent/runs/r1/cancel')
    expect((fn.mock.calls[0][1] as RequestInit).method).toBe('POST')
  })

  it('runEventsUrl points at the SSE endpoint', () => {
    expect(agentApi.runEventsUrl('r1')).toBe('/api/agent/runs/r1/events')
  })
})
