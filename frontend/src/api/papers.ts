import { api } from './client'
import type { Collection, Paper, PaperPatch } from './types'

export const papersApi = {
  list(params: { q?: string; collection_id?: number; reading_status?: 'unread' | 'reading' | 'read'; limit?: number; offset?: number; trashed?: boolean } = {}): Promise<{ papers: Paper[]; total: number; offset: number; has_more: boolean }> {
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
  trash(id: number): Promise<Paper> {
    return api(`/api/library/papers/${id}`, { method: 'DELETE' })
  },
  restore(id: number): Promise<Paper> {
    return api(`/api/library/papers/${id}/restore`, { method: 'POST', body: {} })
  },
  collections(trashed = false): Promise<{ collections: Collection[] }> {
    return api('/api/library/collections' + (trashed ? '?trashed=true' : ''))
  },
  createCollection(name: string, parentId: number | null = null): Promise<Collection> {
    return api('/api/library/collections', { body: { name, parent_id: parentId } })
  },
  editCollection(id: number, name: string, parentId: number | null, expectedRevision: number): Promise<{ collections: Collection[] }> {
    return api(`/api/library/collections/${id}`, { method: 'PATCH', body: { name, parent_id: parentId, expected_revision: expectedRevision } })
  },
  trashCollection(id: number, expectedRevision: number): Promise<{ collections: Collection[] }> {
    return api(`/api/library/collections/${id}`, { method: 'DELETE', body: { expected_revision: expectedRevision } })
  },
  restoreCollection(id: number, expectedRevision: number): Promise<{ collections: Collection[] }> {
    return api(`/api/library/collections/${id}/restore`, { method: 'POST', body: { expected_revision: expectedRevision } })
  },
  refreshCard(id: number): Promise<Paper> {
    return api(`/api/library/papers/${id}/refresh-card`, { method: 'POST', body: {} })
  },
}
