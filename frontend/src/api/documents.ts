import { api } from './client'
import type { Annotation } from './types'
export interface DocumentVersion { id:string; document_id:string; file_hash:string; label:string; original_filename:string; source:string; description:string; size:number; page_count:number; available:boolean; is_default:boolean; annotation_count:number; created_at:string }
export interface PaperDocument { id:string; title:string; role:'main'|'supplement'; current_version_id:string|null; versions:DocumentVersion[] }
export interface DocumentList { paper_id:number; title:string; default_version_id:string|null; documents:PaperDocument[]; unresolved_annotations:Array<{file_hash:string;count:number}> }
const base=(pid:number)=>`/api/library/papers/${pid}`
export const documentsApi={
 list:(pid:number)=>api<DocumentList>(`${base(pid)}/documents`),
 upload:(pid:number,form:FormData)=>api<{version_id:string;deduplicated:boolean}>(`${base(pid)}/document-versions`,{form}),
 setDefault:(pid:number,vid:string,expected:string|null)=>api(`${base(pid)}/document-versions/${vid}/default`,{body:{expected_version_id:expected,confirmed:true}}),
 annotations:(pid:number,vid:string,origin='all')=>api<{annotations:Annotation[]}>(`${base(pid)}/document-versions/${vid}/annotations?origin=${origin}`),
 url:(pid:number,vid:string,mode='original',origin='all',inline=false)=>`${base(pid)}/document-versions/${vid}/file?mode=${mode}&origin=${origin}&inline=${inline}`,
}
