<script setup lang="ts">
import {onMounted,onUnmounted,ref,nextTick} from 'vue'
import {Terminal} from '@xterm/xterm'
import {FitAddon} from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import {api,uid32} from '@/api/client'
import type {Session} from '@/api/types'
const props=defineProps<{sessionId:number}>()
const emit=defineEmits<{close:[]}>()
const controllerId=uid32()
interface Frame {run_id?:string;session?:Session;conversation_id:number;state:string;generation:string|null;data:string;next_offset:number;reset:boolean;error?:string|null}
const surface=ref<HTMLElement|null>(null),ready=ref(false),reason=ref(''),busy=ref(false),error=ref(''),frame=ref<Frame|null>(null)
const files=ref<{path:string;size:number;sha256:string|null}[]>([]),filePaper=ref('')
async function loadFiles(){if(frame.value)try{files.value=(await api<{files:typeof files.value}>(`/api/sessions/${frame.value.conversation_id}/terminal/files`)).files}catch(e){error.value=String(e)}}
async function saveFile(f:typeof files.value[number]){if(!frame.value||!f.sha256)return;try{await api(`/api/sessions/${frame.value.conversation_id}/terminal/artifacts`,{body:{path:f.path,sha256:f.sha256,paper_id:Number(filePaper.value)}});error.value='文件已保存为待审核研究产物'}catch(e){error.value=String(e)}}
let terminal:Terminal|null=null,fit:FitAddon|null=null,observer:ResizeObserver|null=null,timer:ReturnType<typeof setTimeout>|null=null,stopped=false,queue=Promise.resolve(),buffer='',inputTimer:ReturnType<typeof setTimeout>|null=null
async function poll(){
 if(stopped||!frame.value)return
 try{
  const q=new URLSearchParams({offset:String(frame.value.next_offset)});if(frame.value.generation)q.set('generation',frame.value.generation);q.set('controller_id',controllerId)
  const next=await api<Frame>(`/api/sessions/${frame.value.conversation_id}/terminal?${q}`)
  if(stopped)return
  if(next.reset)terminal?.reset()
  if(next.data)terminal?.write(Uint8Array.from(atob(next.data),c=>c.charCodeAt(0)))
  frame.value=next;error.value=''
 }catch(e){error.value=String(e)}
 if(!stopped&&frame.value?.state==='running')timer=setTimeout(poll,250)
}
function send(){
 const data=buffer;buffer='';inputTimer=null
 if(!data||!frame.value?.generation)return
 const current=frame.value;const body={data,generation:current.generation,controller_id:controllerId,request_key:uid32()}
 queue=queue.then(async()=>{if(stopped)return;await api(`/api/sessions/${current.conversation_id}/terminal/input`,{body})}).catch(e=>{error.value=String(e)})
}
async function start(){
 busy.value=true;error.value=''
 try{
  const initial=await api<Frame>(`/api/sessions/${props.sessionId}/terminal`,{body:{confirmed_new_session:true,controller_id:controllerId}})
  if(stopped)return
  frame.value=initial;await nextTick()
  if(!terminal&&surface.value){
   terminal=new Terminal({cursorBlink:true,convertEol:false,scrollback:3000,fontSize:13,theme:{background:'#111827',foreground:'#e5e7eb'}})
   fit=new FitAddon();terminal.loadAddon(fit);terminal.open(surface.value)
   terminal.onData(data=>{if(frame.value?.state!=='running')return;buffer+=data;if(!inputTimer)inputTimer=setTimeout(send,40)})
   observer=new ResizeObserver(()=>{try{fit?.fit();if(frame.value?.generation&&terminal)void api(`/api/sessions/${frame.value.conversation_id}/terminal/resize`,{body:{generation:frame.value.generation,controller_id:controllerId,cols:Math.max(20,Math.min(240,terminal.cols)),rows:Math.max(10,Math.min(100,terminal.rows))}}).catch(()=>{})}catch{}});observer.observe(surface.value)
  }
  terminal?.reset();if(initial.data)terminal?.write(Uint8Array.from(atob(initial.data),c=>c.charCodeAt(0)));fit?.fit();terminal?.focus();if(timer)clearTimeout(timer);void poll()
 }catch(e){error.value=String(e)}finally{busy.value=false}
}
async function stop(){if(!frame.value?.generation)return;busy.value=true;try{frame.value=await api(`/api/sessions/${frame.value.conversation_id}/terminal/stop`,{body:{generation:frame.value.generation,controller_id:controllerId}})}catch(e){error.value=String(e)}finally{busy.value=false}}
onMounted(async()=>{try{const r=await api<{available:boolean;reason:string|null}>(`/api/sessions/${props.sessionId}/terminal-capabilities`);ready.value=r.available;reason.value=r.reason||''}catch(e){error.value=String(e)}})
onUnmounted(()=>{stopped=true;if(timer)clearTimeout(timer);if(inputTimer)clearTimeout(inputTimer);observer?.disconnect();terminal?.dispose()})
</script>
<template><div class="terminal-overlay" role="dialog" aria-modal="true" aria-label="隔离原生终端"><section class="terminal-dialog"><header><strong>Claude 隔离终端</strong><RouterLink v-if="frame?.run_id" :to="`/runs/${frame.run_id}`" @click="emit('close')">运行记录</RouterLink><span v-if="frame">会话 {{frame.conversation_id}} · {{frame.state}}</span><button @click="emit('close')">关闭窗口</button></header><p v-if="!frame">创建独立会话，不复制旧聊天。论文副本只读，生成文件位于工作目录；仅所选模型可联网。权限请求在终端中确认。</p><p v-if="!ready">{{reason}}</p><p v-if="error" role="alert">{{error}}</p><div class="terminal-actions"><button :disabled="!ready||busy||frame?.state==='running'" @click="start">{{frame?'恢复终端':'创建独立终端'}}</button><button v-if="frame?.state==='running'" :disabled="busy" @click="stop">停止终端</button><span>关闭窗口后进程继续运行；停止后可明确恢复。</span></div><div ref="surface" class="terminal-screen"></div><details v-if="frame"><summary @click="loadFiles">工作文件</summary><button @click="loadFiles">刷新文件</button><label>保存产物关联的论文 ID<input v-model="filePaper" inputmode="numeric"/></label><p v-for="f in files" :key="f.path">{{f.path}} · {{f.size}} bytes <a v-if="f.sha256" :href="`/api/sessions/${frame.conversation_id}/terminal/file?path=${encodeURIComponent(f.path)}&sha256=${f.sha256}`">下载</a><button v-if="f.sha256" :disabled="!filePaper" @click="saveFile(f)">保存为研究产物</button></p></details></section></div></template>
<style scoped>.terminal-overlay{position:fixed;inset:0;background:#0008;z-index:100;display:grid;place-items:center;padding:20px}.terminal-dialog{width:min(1100px,95vw);height:min(850px,90dvh);background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:10px;box-sizing:border-box}.terminal-dialog header,.terminal-actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.terminal-dialog header strong{margin-right:auto}.terminal-screen{flex:1;min-height:100px;background:#111827;padding:8px;overflow:hidden}.terminal-actions span{font-size:12px;color:var(--muted)}[role=alert]{color:var(--danger)}</style>
