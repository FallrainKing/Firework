import { api, uid32 } from './client'
import type { ImportRequest } from './types'

export const importsApi = {
  source(body: { value: string; channel?: string; collection_id?: number | null; target_paper_id?: number | null; request_key?: string }): Promise<ImportRequest> {
    return api('/api/imports/source', { body: { channel: 'auto', ...body, request_key: body.request_key ?? uid32() } })
  },
  upload(form: FormData): Promise<ImportRequest> {
    return api('/api/imports/upload', { form })
  },
  list(): Promise<{ imports: ImportRequest[] }> {
    return api('/api/imports')
  },
  get(id: string): Promise<ImportRequest> {
    return api(`/api/imports/${id}`)
  },
  retry(id: string): Promise<ImportRequest> {
    return api(`/api/imports/${id}/retry`, { method: 'POST' })
  },
}
