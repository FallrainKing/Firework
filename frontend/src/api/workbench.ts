import { api } from './client'
import type { Attachment, Draft, RecentRead, WorkspaceState } from './types'

export const workbenchApi = {
  getState(id: string): Promise<WorkspaceState> {
    return api(`/api/workbench/states/${id}`)
  },
  saveState(id: string, state: WorkspaceState): Promise<WorkspaceState> {
    return api(`/api/workbench/states/${id}`, { method: 'PUT', body: state })
  },
  recent(): Promise<{ recent: RecentRead[] }> {
    return api('/api/workbench/recent')
  },
  getDraft(sessionId: number, paperId: number): Promise<Draft> {
    return api(`/api/workbench/drafts/${sessionId}/${paperId}`)
  },
  saveDraft(sessionId: number, paperId: number, draft: Draft): Promise<{ saved: boolean }> {
    return api(`/api/workbench/drafts/${sessionId}/${paperId}`, { method: 'PUT', body: draft })
  },
  uploadImage(form: FormData): Promise<Attachment> {
    return api('/api/workbench/images', { form })
  },
}
