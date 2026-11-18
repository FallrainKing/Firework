import { api } from './client'
import type { Annotation, AnnotationCreate, Position, ReaderDoc, SelectionContext, TranslationRecord } from './types'

export const readerApi = {
  document(paperId: number): Promise<ReaderDoc> {
    return api(`/api/reader/papers/${paperId}`)
  },
  pageText(paperId: number, page: number): Promise<{ page: number; text: string; file_version: string }> {
    return api(`/api/reader/papers/${paperId}/pages/${page}`)
  },
  annotations(paperId: number): Promise<{ annotations: Annotation[] }> {
    return api(`/api/reader/papers/${paperId}/annotations`)
  },
  createAnnotation(body: AnnotationCreate): Promise<Annotation & { validation: string }> {
    return api('/api/reader/annotations', { body })
  },
  patchAnnotation(id: string, body: { content?: string; color?: string; deleted?: boolean }): Promise<Annotation> {
    return api(`/api/reader/annotations/${id}`, { method: 'PATCH', body })
  },
  getState(paperId: number, conversationId: number): Promise<Position> {
    return api(`/api/reader/papers/${paperId}/state?conversation_id=${conversationId}`)
  },
  saveState(paperId: number, body: Position): Promise<Position> {
    return api(`/api/reader/papers/${paperId}/state`, { method: 'PUT', body })
  },
  translations(paperId: number): Promise<{ translations: TranslationRecord[] }> {
    return api(`/api/reader/papers/${paperId}/translations`)
  },
  translate(body: SelectionContext & { conversation_id: number }): Promise<{ id: string; run_id: string; status: string; cached: boolean }> {
    return api('/api/reader/translations', { body })
  },
  setTranslationVisible(id: string, deleted: boolean): Promise<{ id: string; deleted: boolean }> {
    return api(`/api/reader/translations/${id}`, { method: 'PATCH', body: { deleted } })
  },
}
