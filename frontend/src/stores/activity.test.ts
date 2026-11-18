import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useActivityStore } from './activity'
import { agentApi } from '@/api/agent'
import type { Run } from '@/api/types'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  constructor(public url: string) { FakeEventSource.instances.push(this) }
  close() { this.closed = true }
  emit(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }) }
}

function run(overrides: Partial<Run> = {}): Run {
  return {
    id: 'r1', request_key: 'k', conversation_id: 1, skill: 'chat', skill_version: '0.4.0',
    prompt: 'p', status: 'running', answer: '', model: null, usage: {}, tool_calls: [],
    metadata: {}, contexts: [], attachment_ids: [], progress: {}, purpose: 'chat',
    cli_estimated_cost_usd: null, cost_verified: false, error: null,
    created_at: '', finished_at: null, ...overrides,
  }
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.useFakeTimers()
  setActivePinia(createPinia())
  vi.spyOn(agentApi, 'listRuns').mockResolvedValue({ runs: [run()] })
})

afterEach(() => {
  const store = useActivityStore()
  store.stop()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('activity store', () => {
  it('refresh subscribes SSE for running runs and applies progress', async () => {
    const store = useActivityStore()
    await store.refresh()
    expect(store.active).toHaveLength(1)
    expect(FakeEventSource.instances).toHaveLength(1)
    expect(FakeEventSource.instances[0].url).toBe('/api/agent/runs/r1/events')
    FakeEventSource.instances[0].emit({ status: 'running', progress: { type: 'assistant', tools: ['paper_read'], text: 'reading' } })
    expect(store.active[0].progress).toMatchObject({ tools: ['paper_read'] })
  })

  it('terminal frame removes run and closes stream', async () => {
    const store = useActivityStore()
    await store.refresh()
    FakeEventSource.instances[0].emit({ status: 'succeeded', progress: {} })
    expect(store.active).toHaveLength(0)
    expect(FakeEventSource.instances[0].closed).toBe(true)
    expect(store.lastTerminal).toMatchObject({ id: 'r1', status: 'succeeded' })
  })

  it('SSE error falls back to polling until terminal', async () => {
    vi.spyOn(agentApi, 'getRun').mockResolvedValue(run({ status: 'failed', error: 'stream broke' }))
    const store = useActivityStore()
    await store.refresh()
    FakeEventSource.instances[0].onerror?.()
    expect(FakeEventSource.instances[0].closed).toBe(true)
    expect(store.active).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(2000)
    expect(agentApi.getRun).toHaveBeenCalledWith('r1')
    expect(store.active).toHaveLength(0)
    expect(store.lastTerminal).toMatchObject({ status: 'failed' })
  })

  it('queued runs do not open SSE', async () => {
    vi.spyOn(agentApi, 'listRuns').mockResolvedValue({ runs: [run({ status: 'queued' })] })
    const store = useActivityStore()
    await store.refresh()
    expect(store.active).toHaveLength(1)
    expect(FakeEventSource.instances).toHaveLength(0)
  })

  it('cancel calls api and marks cancelling', async () => {
    vi.spyOn(agentApi, 'cancelRun').mockResolvedValue(run({ status: 'cancelled' }))
    const store = useActivityStore()
    await store.refresh()
    await store.cancel('r1')
    expect(agentApi.cancelRun).toHaveBeenCalledWith('r1')
  })
})
