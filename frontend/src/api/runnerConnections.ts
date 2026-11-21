import {api} from './client'
export interface ConnectionRef{id:string;revision:number}
export interface ConnectionConfig{base_url:string;model:string;auth_type:'api_key'|'bearer';vision:'unknown'|'declared_yes'|'declared_no';context_window:number;role_prompt:string}
export interface Connection extends ConnectionRef{name:string;enabled:boolean;has_credential:boolean;verification:string;config:ConnectionConfig}
export interface ConnectionList{connections:Connection[];default_connection_id:string|null;settings_revision:number;legacy_available:boolean}
export const runnerConnections={
 list:()=>api<ConnectionList>('/api/me/runner/connections'),
 save:(body:{name:string;config:ConnectionConfig;api_key?:string;enabled:boolean;expected_revision?:number},id?:string)=>api<Connection>('/api/me/runner/connections'+(id?'/'+id:''),{method:id?'PATCH':'POST',body}),
 setDefault:(connection_id:string|null,expected_revision:number)=>api<ConnectionList>('/api/me/runner/connections/default',{method:'PUT',body:{connection_id,expected_revision}}),
 preview:(connection:ConnectionRef|null,has_images=false)=>api<{snapshot:Record<string,unknown>;warning:string;model_called:boolean}>('/api/me/runner/connections/preflight',{body:{connection,has_images}}),
}
