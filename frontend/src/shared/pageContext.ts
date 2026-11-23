import {reactive} from 'vue'
import {api} from '@/api/client'
export const pageContext=reactive({id:'',revision:0,shared:false,error:'',selectionId:''})
let resource:Record<string,unknown>={},view='home',page:number|undefined,panel:string|undefined,queue=Promise.resolve(),stopped=false,epoch=0
export function setPageContext(nextView:string,nextResource:Record<string,unknown>={},reading?:{page?:number;panel?:string}){const same=nextView===view&&nextResource.paper_id===resource.paper_id&&(!nextResource.document_version_id||nextResource.document_version_id===resource.document_version_id);view=nextView;resource=same?{...resource,...nextResource}:nextResource;page=reading?.page;panel=reading?.panel;void publish()}
export function enrichPageContext(detail:{paper_id:number;file_hash:string;document_version_id?:string;session_id?:number;page:number;panel:string}){if(resource.paper_id!==detail.paper_id)return;resource={...resource,file_hash:detail.file_hash,document_version_id:detail.document_version_id,session_id:detail.session_id};page=detail.page;panel=detail.panel;void publish()}
export function publish(closed=false){
 const generation=epoch
 const snapshot={workspace_id:localStorage.getItem('research-workspace-id')||'0'.repeat(32),view,resource:{...resource},page,panel,visibility:closed?'closed':document.visibilityState,has_focus:document.hasFocus(),shared:pageContext.shared}
 queue=queue.then(async()=>{if(generation!==epoch||(stopped&&!closed))return;if(!pageContext.id){const c=await api<{id:string}>('/api/workbench/contexts',{method:'POST'});if(generation!==epoch)return;pageContext.id=c.id}const revision=++pageContext.revision;await api(`/api/workbench/contexts/${pageContext.id}`,{method:'PUT',body:{...snapshot,revision}});if(generation===epoch)pageContext.error=''}).catch(e=>{if(generation===epoch)pageContext.error=String(e)})
 return queue
}
export function toggleContextSharing(){pageContext.shared=!pageContext.shared;void publish()}
export async function shareSelection(body:unknown){if(!pageContext.shared){pageContext.shared=true;await publish()}const result=await api<{id:string}>(`/api/workbench/contexts/${pageContext.id}/selections`,{body});pageContext.selectionId=result.id;return result}
export function startContext(){if(stopped){epoch++;Object.assign(pageContext,{id:'',revision:0,shared:false,error:'',selectionId:''});resource={};page=undefined;panel=undefined;view='home'}stopped=false}
export function stopContext(){pageContext.shared=false;if(pageContext.id)void publish(true);stopped=true}
