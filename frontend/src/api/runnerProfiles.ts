import {api} from './client'
import type {ConnectionRef} from './runnerConnections'
import type {BudgetRef} from './runnerBudgets'
export interface ProfileRef{id:string;revision:number}
export interface ProfileConfig{skill_id:string;skill_version_id:number;connection:ConnectionRef|null;budget:BudgetRef;role_prompt:string;tools:string[]}
export interface RunnerProfile extends ProfileRef{name:string;enabled:boolean;config:ProfileConfig}
export interface ToolCatalog{servers:{id:string;transport:string;tools:{name:string;effect:string;grant:string}[]}[];external_servers_enabled:boolean}
export interface ModelEntry{connection_id:string;revision:number;connection_name:string;enabled:boolean;model:string;vision:string;context_window:number;verification:string}
const base='/api/me/runner'
export const runnerProfiles={
 list:()=>api<{profiles:RunnerProfile[]}>(base+'/profiles'),
 save:(body:{name:string;enabled:boolean;config:ProfileConfig;expected_revision?:number},id?:string)=>api<RunnerProfile>(base+'/profiles'+(id?'/'+id:''),{method:id?'PATCH':'POST',body}),
 preview:(body:ProfileConfig)=>api<Record<string,unknown>>(base+'/profiles/preflight',{method:'POST',body}),
 tools:()=>api<ToolCatalog>(base+'/mcp'),
 models:()=>api<{models:ModelEntry[]}>(base+'/models'),
}
