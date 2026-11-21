<script setup lang="ts">
import {ref} from 'vue'
import {runnerConnections,type ConnectionList,type ConnectionRef} from '@/api/runnerConnections'
const props=defineProps<{modelValue:ConnectionRef|null;disabled?:boolean;bound?:boolean}>()
const emit=defineEmits<{'update:modelValue':[ConnectionRef|null]}>()
const open=ref(false),data=ref<ConnectionList|null>(null),error=ref('')
async function toggle(){open.value=!open.value;if(open.value)try{data.value=await runnerConnections.list();error.value=''}catch(e){error.value=e instanceof Error?e.message:'读取失败'}}
function change(e:Event){const c=data.value?.connections.find(c=>c.id===(e.target as HTMLSelectElement).value);emit('update:modelValue',c?{id:c.id,revision:c.revision}:null)}
</script>
<template><div class="run-connection"><button type="button" :disabled="disabled" @click="toggle" :aria-expanded="open">模型连接{{ bound?' · 会话已绑定':modelValue?' · 本次自选':'' }}</button><div v-if="open"><p v-if="bound">继续使用此会话绑定的连接。切换连接请新建会话。</p><label v-else>新会话使用 <select :value="modelValue?.id||''" @change="change"><option value="">账号默认连接</option><option v-for="c in data?.connections||[]" :key="c.id" :value="c.id" :disabled="!c.enabled">{{ c.name }} · {{ c.config.model }}</option></select></label><a href="/#/settings/runner/connections">管理模型连接</a><p v-if="error" role="alert">{{ error }}</p></div></div></template>
<style scoped>.run-connection{padding:6px 12px;font-size:12px}.run-connection select{max-width:100%;margin:6px}.run-connection a{margin:6px}</style>
