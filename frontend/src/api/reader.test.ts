import { afterEach, describe, expect, it, vi } from 'vitest'
import { readerApi } from './reader'

afterEach(() => vi.unstubAllGlobals())

function mockFetch(body: unknown, status = 200) {
  const fn = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fn)
  return fn
}

const ctx = { paper_id: 1, page: 2, file_version: 'a'.repeat(64), quote: 'text', rects: [[0.1, 0.1, 0.3, 0.03]] }

describe('reader api', () => {
  it('createAnnotation posts body to annotations', async () => {
    const fn = mockFetch({ id: 'a1', validation: 'text_located' })
    await readerApi.createAnnotation({ ...ctx, kind: 'highlight', conversation_id: 5 })
    expect(fn.mock.calls[0][0]).toBe('/api/reader/annotations')
    const init = fn.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toMatchObject({ kind: 'highlight', conversation_id: 5, page: 2 })
  })

  it('getState passes conversation_id query', async () => {
    const fn = mockFetch({ page: 3, zoom: 'fit', tab: 'outline' })
    await readerApi.getState(1, 5)
    expect(fn.mock.calls[0][0]).toBe('/api/reader/papers/1/state?conversation_id=5')
  })

  it('translate returns cached flag', async () => {
    mockFetch({ id: 't1', run_id: 'r1', status: 'succeeded', cached: true })
    const result = await readerApi.translate({ ...ctx, conversation_id: 5 })
    expect(result.cached).toBe(true)
  })

  it('setTranslationVisible patches deleted', async () => {
    const fn = mockFetch({ id: 't1', deleted: true })
    await readerApi.setTranslationVisible('t1', true)
    expect(fn.mock.calls[0][0]).toBe('/api/reader/translations/t1')
    expect((fn.mock.calls[0][1] as RequestInit).method).toBe('PATCH')
  })

  it('saveState PUTs position', async () => {
    const fn = mockFetch({ conversation_id: 5, page: 3, zoom: 'fit', tab: 'outline' })
    await readerApi.saveState(1, { conversation_id: 5, page: 3, zoom: 'fit', tab: 'outline' })
    expect(fn.mock.calls[0][0]).toBe('/api/reader/papers/1/state')
    expect((fn.mock.calls[0][1] as RequestInit).method).toBe('PUT')
  })
})
