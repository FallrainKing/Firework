import { api } from './client'
import type { Collection, Paper, PaperPatch } from './types'

export const papersApi = {
  list(params: { q?: string; collection_id?: number; limit?: number; offset?: number } = {}): Promise<{ papers: Paper[]; total: number; offset: number; has_more: boolean }> {
    const search = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') search.set(k, String(v))
    const q = search.toString()
    return api(`/api/library/papers${q ? '?' + q : ''}`)
  },
  get(id: number): Promise<Paper> {
    return api(`/api/library/papers/${id}`)
  },
  patch(id: number, body: PaperPatch): Promise<Paper> {
    return api(`/api/library/papers/${id}`, { method: 'PATCH', body })
  },
  collections(): Promise<{ collections: Collection[] }> {
    return api('/api/library/collections')
  },
  createCollection(name: string): Promise<Collection> {
    return api('/api/library/collections', { body: { name } })
  },
  refreshCard(id: number): Promise<Paper> {
    return api(`/api/library/papers/${id}/refresh-card`, { method: 'POST', body: {} })
  },
}
