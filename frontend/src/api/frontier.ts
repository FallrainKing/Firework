import {api} from './client'
export interface FrontierConfig {skill_id?:string;skill_version_id?:number|null;goal:string;domains:string[];keywords:string[];authors:string[];teams:string[];exclude:string[];sources:string[];collection_ids:number[];interval_hours:number;lookback_days:number;max_results:number;daily_run_limit:number}
export interface FrontierTopic {id:number;title:string;revision:number;config:FrontierConfig;conversation_id:number;pending_count:number;schedule:{id:number;enabled:boolean;next_at:string}|null}
export interface FrontierItem {id:string|number;entity_id?:number;topic_id?:number;kind?:string;metadata:Record<string,any>;decision:string;revision:number;in_library:boolean;paper_id:number|null;project_id:number|null;change_type?:string;reason?:string;similar_paper_ids?:number[]}
export interface FrontierRun {origin?:string;id:string;topic_id:number;topic_title?:string;status:string;report_id?:number;version?:number;is_read?:boolean;report_md:string;counts:Record<string,number>;items:FrontierItem[];coverage:Array<{source:string;status:string;truncated:boolean;error?:string;retrieved:number;total:number}>;error:string|null;created_at:string;finished_at:string|null;conversation_id:number;cost:number|null;usage:Record<string,number>}
export const frontierApi={
 topics:()=>api<{topics:FrontierTopic[]}>('/api/frontier/topics'),
 create:(body:{title:string;config:FrontierConfig})=>api<FrontierTopic>('/api/frontier/topics',{body}),
 update:(id:number,body:{title:string;config:FrontierConfig;revision:number})=>api<FrontierTopic>(`/api/frontier/topics/${id}`,{method:'PATCH',body}),
 trigger:(id:number,key:string)=>api<FrontierRun>(`/api/frontier/topics/${id}/runs`,{body:{request_key:key}}),
 runs:(id:number)=>api<{runs:FrontierRun[]}>(`/api/frontier/topics/${id}/runs`),
 cancel:(id:string)=>api(`/api/frontier/runs/${id}/cancel`,{method:'POST'}),
 items:(id?:number,before?:string)=>{const p=new URLSearchParams();if(id)p.set('topic_id',String(id));if(before)p.set('before',before);return api<{items:FrontierItem[];next_cursor?:string|null}>('/api/frontier/candidates?'+p)},
 reports:(id?:number,before?:number)=>{const p=new URLSearchParams();if(id)p.set('topic_id',String(id));if(before)p.set('before',String(before));return api<{reports:FrontierRun[];next_cursor:number|null}>('/api/frontier/reports?'+p)},
 discussion:(id:string)=>api<{session_id:number}>(`/api/frontier/runs/${id}/discussion`,{method:'POST'}),
 read:(id:string)=>api(`/api/frontier/reports/${id}/read-state`,{method:'PATCH'}),
 decision:(topic:number,entity:number,body:unknown)=>api<{saved:boolean;paper_id:number|null;project_id:number|null;import_error?:string}>(`/api/frontier/topics/${topic}/items/${entity}/decision`,{body}),
 batch:(items:unknown[])=>api<{results:Array<{saved:boolean;error?:string}>}>('/api/frontier/decisions/batch',{body:{items}}),
 projects:(collection?:number)=>api<{projects:Array<Record<string,any>>}>('/api/frontier/projects'+(collection?`?collection_id=${collection}`:'')),
}
