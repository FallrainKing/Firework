import {api} from './client'
import type {Skill} from './skills'
export interface SkillDraft{name:string;description:string;version:string;instructions:string;resources:Record<string,string>;tools:string[];surfaces:string[]}
export interface DraftRecord{skill_id:string;revision:number;body:SkillDraft;published_revision?:number|null}
export const skillAuthoring={
 surfaces:()=>api<{surfaces:{id:string;label:string}[]}>('/api/skills/surfaces'),
 available:(surface:string)=>api<{skills:(Skill&{selectable:boolean;blocked_reason:string|null})[]}>('/api/skills/available?surface='+encodeURIComponent(surface)),
 draft:(id:string)=>api<DraftRecord>('/api/skills/'+encodeURIComponent(id)+'/draft'),
 save:(body:SkillDraft,id?:string,revision?:number)=>api<DraftRecord>(id?'/api/skills/'+encodeURIComponent(id)+'/draft':'/api/skills/drafts',{method:id?'PATCH':'POST',body:{...body,...(id?{expected_revision:revision}:{})}}),
 publish:(id:string,revision:number)=>api<Skill>('/api/skills/'+encodeURIComponent(id)+'/publish',{method:'POST',body:{expected_revision:revision}}),
 placements:(id:string)=>api<{surfaces:string[];revision:number}>('/api/skills/'+encodeURIComponent(id)+'/placements'),
 setPlacements:(id:string,surfaces:string[],revision:number)=>api('/api/skills/'+encodeURIComponent(id)+'/placements',{method:'PUT',body:{surfaces,expected_revision:revision}}),
}
