<script setup lang="ts">
import {onMounted,onUnmounted,ref,watch} from 'vue'
import {api} from '@/api/client'
import {renderMarkdown} from '@/shared/markdown'
const provider=ref<{name:string;version:string|null;status:string}|null>(null)
const emit=defineEmits<{continue:[]}>()
const props=defineProps<{sessionId:number}>()
interface Event {id:string;role:string;text:string;tools:string[];images:number;timestamp:string;truncated?:boolean}
interface Snapshot {session_id:string;state:string;events:Event[];next_offset:number;source:string|null;has_more:boolean;reset:boolean;connection_name:string}
const data=ref<Snapshot|null>(null),events=ref<Event[]>([]),error=ref(''),busy=ref(false)
let epoch=0
async function load(reset=false){
 const ticket=++epoch;busy.value=true;error.value=''
 try{
  const q=new URLSearchParams({offset:String(reset?0:data.value?.next_offset??0),limit:'50'})
  if(!reset&&data.value?.source)q.set('source',data.value.source)
  const result=await api<Snapshot>(`/api/sessions/${props.sessionId}/native?${q}`)
  if(ticket!==epoch)return
  events.value=reset||result.reset?result.events:[...events.value,...result.events]
  data.value=result
 }catch(e){if(ticket===epoch)error.value=e instanceof Error?e.message:'原生会话读取失败'}
 finally{if(ticket===epoch)busy.value=false}
}
watch(()=>props.sessionId,()=>{events.value=[];data.value=null;void load(true)})
onMounted(()=>{void load(true);void api<{providers:{name:string;version:string|null;status:string}[]}>('/api/agent/providers').then(r=>{provider.value=r.providers[0]??null}).catch(()=>{})});onUnmounted(()=>{epoch++})
</script>
<template><section class="native-panel" aria-label="原生 Claude 会话记录"><header><strong>Claude 原生记录</strong><button :disabled="busy" @click="load(true)">重新载入</button></header><p v-if="provider" class="native-meta">{{provider.name}} {{provider.version||'版本未识别'}} · {{provider.status==='installed'?'已安装':'检测未通过'}}</p><p v-if="data" class="native-meta">{{data.connection_name}} · {{data.session_id}}</p><p v-if="error" role="alert">{{error}}</p><p v-if="data?.state==='not_found'">尚未找到该会话的原生记录，可继续使用完整会话。</p><p v-if="data?.reset" role="status">记录来源已变化，已从头载入。</p><article v-for="(e,i) in events" :key="`${i}-${e.id}`"><small>{{e.role==='user'?'你':'Claude'}} · {{e.timestamp}}</small><div class="markdown-content" v-html="renderMarkdown(e.text)"></div><p v-if="e.truncated">该条记录过长，已显示前48000字符。</p><p v-if="e.tools.length">工具：{{e.tools.join('、')}}</p><p v-if="e.images">图片 {{e.images}} 张</p></article><footer><button :disabled="busy||!data" @click="load(false)">{{busy?'读取中…':data?.has_more?'读取后续记录':'检查新记录'}}</button><button @click="emit('continue')">继续此会话</button></footer></section></template>
<style scoped>.native-panel{padding:12px;min-width:0}.native-panel header,.native-panel footer{display:flex;gap:8px;align-items:center;justify-content:space-between;flex-wrap:wrap}.native-panel article{padding:12px 0;border-bottom:1px solid var(--border);overflow-wrap:anywhere}.native-meta{font-size:12px;overflow-wrap:anywhere}.native-panel small,.native-panel footer span{font-size:12px;color:var(--muted)}.native-panel [role=alert]{color:var(--danger)}</style>
