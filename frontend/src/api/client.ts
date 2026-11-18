export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

interface Options {
  method?: string
  body?: unknown
  form?: FormData
}

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const init: RequestInit = { method: opts.method ?? (opts.body !== undefined || opts.form ? 'POST' : 'GET') }
  if (opts.form) {
    init.body = opts.form
  } else if (opts.body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(opts.body)
  }
  const res = await fetch(path, init)
  let data: unknown = null
  try {
    data = await res.json()
  } catch {
    /* empty body */
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail
    throw new ApiError(res.status, typeof detail === 'string' ? detail : '请求失败，请稍后重试')
  }
  return data as T
}

export function uid32(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID().replaceAll('-', '')
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('')
}
