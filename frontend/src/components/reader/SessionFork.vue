<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {api} from '@/api/client'
import {runnerConnections,type Connection} from '@/api/runnerConnections'
import type {Session} from '@/api/types'
const props=defineProps<{sessionId:number}>(),emit=defineEmits<{close:[]}>()
const connections=ref<Connection[]>([]),connection=ref(''),include=ref(false),turns=ref(10),plan=ref<Record<string,unknown>|null>(null),error=ref(''),busy=ref(false),created=ref<Session|null>(null)
const body=()=>{const c=connections.value.find(x=>x.id===connection.value);return {connection:c?{id:c.id,revision:c.revision}:null,include_history:include.value,max_turns:turns.value}}
onMounted(async()=>{try{connections.value=(await runnerConnections.list()).connections}catch(e){error.value=String(e)}})
async function preview(){busy.value=true;try{plan.value=await api(`/api/sessions/${props.sessionId}/fork-preview`,{body:body()});error.value=''}catch(e){error.value=String(e)}finally{busy.value=false}}
async function confirm(){if(!plan.value)return;busy.value=true;try{const r=await api<{session:Session}>(`/api/sessions/${props.sessionId}/forks`,{body:{...body(),confirmation_hash:plan.value.confirmation_hash}});created.value=r.session;error.value=''}catch(e){error.value=String(e);plan.value=null}finally{busy.value=false}}
</script>
<template><div class="fork-overlay"><section role="dialog" aria-modal="true" aria-label="创建会话分支"><header><h2>创建会话分支</h2><button @click="emit('close')">关闭</button></header><p v-if="error" role="alert">{{error}}</p><template v-if="!created"><label>目标连接<select v-model="connection" @change="plan=null"><option value="">账号当前默认连接</option><option v-for="c in connections.filter(c=>c.enabled)" :key="c.id" :value="c.id">{{c.name}} · {{c.config.model}}</option></select></label><label><input type="checkbox" v-model="include" @change="plan=null"/>向目标服务商转移选定历史</label><label v-if="include">最近成功轮次<input v-model.number="turns" type="number" min="1" max="20" @change="plan=null"/></label><button :disabled="busy" @click="preview">预览将转移的内容</button><template v-if="plan"><pre>{{JSON.stringify(plan,null,2)}}</pre><button :disabled="busy" @click="confirm">确认目标与内容，创建分支</button></template></template><p v-else>已创建会话 {{created.id}}，尚未调用模型。<RouterLink :to="`/sessions/${created.id}`">返回工作台</RouterLink></p></section></div></template>
<style scoped>.fork-overlay{position:fixed;inset:0;background:#0008;z-index:110;display:grid;place-items:center;padding:20px}.fork-overlay section{background:var(--bg);padding:20px;border-radius:12px;width:min(760px,90vw);max-height:85dvh;overflow:auto}.fork-overlay header{display:flex;justify-content:space-between;align-items:center}.fork-overlay label{display:block;margin:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}</style>
