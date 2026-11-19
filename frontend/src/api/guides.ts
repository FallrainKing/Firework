import {api} from './client'
export interface GuideAnchor {page:number;quote:string;rects:number[][];status:string;block_id:string}
export interface GuideItem {id:string;item:{key:string;category:string;priority:string;title:string;why_important_md:string;explanation_md:string;claim_type:string;follow_up_questions:string[];uncertainties:string[]};anchors:GuideAnchor[];location_status:string;annotations:Array<{id:string;page:number;deleted:number;kind:string}>}
export interface PaperGuide {id:string;paper_id:number;file_version:string;skill_id:string;skill_version_id:number;conversation_id:number;agent_run_id:string|null;status:string;active:number;hidden:number;error:string|null;cached:boolean;coverage:{provided_pages?:number[];truncated?:boolean};warnings:Array<{item_key:string;status:string;page:number}>;result:{summary:{problem_md:string;approach_md:string;contributions_md:string;limitations_md:string};reading_route:Array<{key:string;title:string;goal_md:string;item_keys:string[];block_ids:string[]}>;unknown_fields:Array<{path:string;reason:string}>}|null;items:GuideItem[];usage:Record<string,number>;cost:number|null}
export interface GuideState {task:PaperGuide|null;guide:PaperGuide|null;older_versions:number}
export interface GuideSkill {id:string;name:string;version_id:number;max_budget_usd:number;max_output_tokens:number}
export const guidesApi={
 current:(pid:number)=>api<GuideState>(`/api/reader/papers/${pid}/guide`),
 skills:()=>api<{skills:GuideSkill[];contract:string}>('/api/reader/guide-skills'),
 create:(pid:number,body:{confirmed:true;file_version:string;request_key:string;skill_id:string;skill_version_id:number;reading_goal:string;max_items:number;max_pages:number})=>api<PaperGuide>(`/api/reader/papers/${pid}/guide-runs`,{body}),
 cancel:(id:string)=>api<PaperGuide>(`/api/reader/guide-runs/${id}/cancel`,{method:'POST'}),
 hide:(id:string)=>api(`/api/reader/guide-runs/${id}`,{method:'PATCH',body:{hidden:true}}),
 adopt:(id:string,key:string)=>api(`/api/reader/guide-items/${id}/adopt`,{body:{request_key:key}}),
}
