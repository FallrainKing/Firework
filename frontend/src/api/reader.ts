import { api } from './client'
import type { Annotation, AnnotationCreate, Position, ReaderDoc, SelectionContext, TranslationRecord } from './types'

export interface ReadingArtifact {id:string;title:string;kind:string;markdown:string;current_revision:number;created_at?:string;version_status:'matched'|'unverified'}
export interface ReadingResults {artifacts:ReadingArtifact[];unverified_artifacts:ReadingArtifact[];older_versions:number;has_more:boolean}
export const readerApi = {
  readingResults:(pid:number,version:string)=>api<ReadingResults>(`/api/research/artifacts?paper_id=${pid}&reader_file_version=${encodeURIComponent(version)}&limit=100`),
  locate:(body:SelectionContext)=>api<SelectionContext&{status:string;original_url?:string}>('/api/reader/anchors/locate',{body}),
  document(paperId: number,versionId?:string): Promise<ReaderDoc> {
    return api(`/api/reader/papers/${paperId}${versionId?'?version_id='+encodeURIComponent(versionId):''}`)
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
  getState(paperId: number, conversationId: number,fileVersion?:string): Promise<Position> {
    return api(`/api/reader/papers/${paperId}/state?conversation_id=${conversationId}${fileVersion?'&file_version='+fileVersion:''}`)
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
