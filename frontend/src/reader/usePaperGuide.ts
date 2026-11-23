import {computed,onUnmounted,onActivated,onDeactivated,ref,watch,type Ref} from 'vue'
import {guidesApi,type GuideSkill,type GuideState} from '@/api/guides'
import {uid32} from '@/api/client'
import type {ReaderDoc} from '@/api/types'
export function usePaperGuide(doc:Ref<ReaderDoc|null>,onPublished:()=>Promise<void>,toast:(s:string)=>void){
 const state=ref<GuideState>({task:null,guide:null,older_versions:0}),busy=ref(false),error=ref(''),showAI=ref(true),focusItem=ref<string|null>(null)
 const skills=ref<GuideSkill[]>([])
 const running=computed(()=>!!state.value.task&&['dispatching','queued','running','staging'].includes(state.value.task.status))
 let timer:ReturnType<typeof setInterval>|null=null,epoch=0,stopped=false
 function stopPoll(){if(timer)clearInterval(timer);timer=null}
 async function refresh(){const d=doc.value;if(!d)return;const e=++epoch
  try{const next=await guidesApi.current(d.paper_id,d.file_version);if(stopped||e!==epoch||doc.value?.paper_id!==d.paper_id||doc.value?.file_version!==d.file_version)return
   if(next.guide&&next.guide.file_version!==d.file_version){next.guide=null;next.task=null;next.older_versions=Math.max(1,next.older_versions)}
   const old=state.value.guide?.id;state.value=next;error.value=''
   if(next.guide?.id!==old){await onPublished()}
   if(running.value&&!timer)timer=setInterval(()=>void refresh(),2500)
   if(!running.value)stopPoll()
  }catch(errorValue){if(!stopped&&e===epoch&&doc.value?.paper_id===d.paper_id&&doc.value?.file_version===d.file_version)error.value=errorValue instanceof Error?errorValue.message:'导读载入失败'}
 }
 watch(showAI,value=>{if(doc.value)localStorage.setItem('paper-ai-layer-'+doc.value.paper_id,String(value))})
 watch(()=>[doc.value?.paper_id,doc.value?.file_version],()=>{epoch++;error.value='';focusItem.value=null;if(doc.value)showAI.value=localStorage.getItem('paper-ai-layer-'+doc.value.paper_id)!=='false';stopPoll();state.value={task:null,guide:null,older_versions:0};if(doc.value)void refresh()},{immediate:true})
 async function loadSkills(){try{skills.value=(await guidesApi.skills()).skills}catch(e){error.value=e instanceof Error?e.message:'技能载入失败'}}
 async function start(options:{skill_id:string;skill_version_id:number;reading_goal:string;max_items:number;max_pages:number}){
  if(!doc.value||busy.value||running.value)return;busy.value=true;error.value=''
  try{if(!Number.isInteger(options.max_items)||options.max_items<1||options.max_items>10||!Number.isInteger(options.max_pages)||options.max_pages<1||options.max_pages>Math.min(6,doc.value.page_count))throw new Error('请填写有效的重点数量（1–10）和材料页数（最多 6 页）');const result=await guidesApi.create(doc.value.paper_id,{confirmed:true,file_version:doc.value.file_version,request_key:uid32(),...options});await refresh();toast(result.cached?'已复用现有导读或任务，没有重复生成':'已由你触发导读 Skill，后台生成批注。')}
  catch(e){error.value=e instanceof Error?e.message:'导读提交失败'}finally{busy.value=false}
 }
 async function cancel(){if(!state.value.task)return;busy.value=true;try{await guidesApi.cancel(state.value.task.id);await refresh()}catch(e){error.value=e instanceof Error?e.message:'停止失败'}finally{busy.value=false}}
 async function hide(){if(!state.value.task)return;busy.value=true;try{await guidesApi.hide(state.value.task.id);await refresh();await onPublished()}catch(e){error.value=e instanceof Error?e.message:'移除失败'}finally{busy.value=false}}
 onActivated(()=>{void refresh()})
 onDeactivated(()=>{epoch++;stopPoll()})
 onUnmounted(()=>{stopped=true;epoch++;stopPoll()})
 return {state,busy,error,running,showAI,focusItem,skills,refresh,loadSkills,start,cancel,hide}
}
export type PaperGuideController=ReturnType<typeof usePaperGuide>
