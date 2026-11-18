import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './client'

afterEach(() => vi.unstubAllGlobals())

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('api client', () => {
  it('returns parsed json on success', async () => {
    mockFetch(200, { ok: true })
    expect(await api<{ ok: boolean }>('/api/x')).toEqual({ ok: true })
  })

  it('throws ApiError with backend detail', async () => {
    mockFetch(409, { detail: '冲突文案' })
    await expect(api('/api/x', { method: 'POST', body: {} })).rejects.toThrowError(new ApiError(409, '冲突文案'))
  })

  it('falls back to generic message when detail missing', async () => {
    mockFetch(500, {})
    await expect(api('/api/x')).rejects.toThrow('请求失败')
  })

  it('sends json body with content-type', async () => {
    const fn = mockFetch(200, {})
    await api('/api/x', { method: 'PUT', body: { a: 1 } })
    const init = fn.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('PUT')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(init.body).toBe('{"a":1}')
  })

  it('form upload does not set content-type', async () => {
    const fn = mockFetch(201, {})
    const form = new FormData()
    form.append('file', new Blob(['x']), 'x.pdf')
    await api('/api/x', { form })
    const init = fn.mock.calls[0][1] as RequestInit
    expect(init.body).toBe(form)
    expect(init.headers).toBeUndefined()
  })
})
