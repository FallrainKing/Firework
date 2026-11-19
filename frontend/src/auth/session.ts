import {ref} from 'vue'
import {api,setCsrfToken} from '@/api/client'
export interface Account {id:string;username:string;role:'admin'|'user';enabled:number;login_allowed:boolean;created_at:number;last_login_at:number|null}
export interface AuthSession {authenticated:boolean;account:Account|null;csrf_token:string|null;registration_open:boolean;admin_only:boolean;initialized?:boolean}
export const authState=ref<AuthSession|null>(null)
let pending:Promise<void>|null=null
const PRIVATE_KEYS=['research-workspace','reader-pending-','research-pending-session-','paper-ai-layer-','frontier-view-','library-density','research-theme']
export function resetBrowserIdentity(id:string|null,preserveLegacy=false){
 const previous=localStorage.getItem('research-auth-account')
 if(previous===id)return
 if(!previous&&id&&preserveLegacy){const saved=localStorage.getItem('research-account-workspace:'+id);if(saved)localStorage.setItem('research-workspace-id',saved);localStorage.setItem('research-auth-account',id);return}
 const workspace=localStorage.getItem('research-workspace-id')
 if(previous&&workspace)localStorage.setItem('research-account-workspace:'+previous,workspace)
 for(const key of Object.keys(localStorage))if(PRIVATE_KEYS.some(prefix=>key.startsWith(prefix)))localStorage.removeItem(key)
 sessionStorage.clear()
 if(id){localStorage.setItem('research-auth-account',id);const saved=localStorage.getItem('research-account-workspace:'+id);if(saved)localStorage.setItem('research-workspace-id',saved)}else localStorage.removeItem('research-auth-account')
}
export async function refreshAuth(){
 if(pending)return pending
 pending=(async()=>{const data=await api<AuthSession>('/api/auth/session');setCsrfToken(data.csrf_token??'');resetBrowserIdentity(data.account?.id??null,data.account?.role==='admin');authState.value=data})().finally(()=>{pending=null})
 return pending
}
export async function login(username:string,password:string){const data=await api<AuthSession>('/api/auth/login',{body:{username,password}});setCsrfToken(data.csrf_token??'');resetBrowserIdentity(data.account!.id,data.account?.role==='admin');authState.value=data;return data}
export async function logout(){await api('/api/auth/logout',{method:'POST'});setCsrfToken('');resetBrowserIdentity(null);authState.value=null;window.location.replace('/login')}
