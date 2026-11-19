import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, setCsrfToken } from './client'

afterEach(() => {vi.unstubAllGlobals();setCsrfToken('')})

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('api client', () => {
  it('includes session credentials and CSRF on mutation but not query', async()=>{
    setCsrfToken('per-session-csrf')
    const fn=mockFetch(200,{})
    await api('/api/x',{body:{}})
    expect(fn.mock.calls[0][1]).toMatchObject({credentials:'same-origin',headers:{'X-CSRF-Token':'per-session-csrf'}})
    await api('/api/x')
    expect(fn.mock.calls[1][1]?.headers).toBeUndefined()
  })
  it('announces expired protected sessions',async()=>{
    mockFetch(401,{detail:'请先登录'})
    const seen=vi.fn();window.addEventListener('research-auth-expired',seen)
    await expect(api('/api/library/papers')).rejects.toThrow('请先登录')
    expect(seen).toHaveBeenCalledOnce()
    window.removeEventListener('research-auth-expired',seen)
  })

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
    expect((init.headers as Record<string,string>)['Content-Type']).toBeUndefined()
  })
})
