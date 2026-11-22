<script setup lang="ts">
import {ref} from 'vue'
import {runnerProfiles,type RunnerProfile,type ProfileRef} from '@/api/runnerProfiles'
const props=defineProps<{modelValue:ProfileRef|null;skill?:string;disabled?:boolean;bound?:boolean}>()
const emit=defineEmits<{'update:modelValue':[ProfileRef|null]}>()
const open=ref(false),profiles=ref<RunnerProfile[]>([]),error=ref('')
async function toggle(){open.value=!open.value;if(open.value)try{profiles.value=(await runnerProfiles.list()).profiles;error.value=''}catch(e){error.value=String(e)}}
function change(e:Event){const p=profiles.value.find(p=>p.id===(e.target as HTMLSelectElement).value);emit('update:modelValue',p?{id:p.id,revision:p.revision}:null)}
</script>
<template><div class="run-profile"><button type="button" :disabled="disabled" @click="toggle" :aria-expanded="open">执行方案{{ bound?' · 会话已绑定':modelValue?' · 已选择':'' }}</button><div v-if="open"><p v-if="bound">继续使用会话已有配置。变更方案请新建会话。</p><label v-else>新会话方案 <select :value="modelValue?.id||''" :disabled="disabled" @change="change"><option value="">手动选择连接与额度</option><option v-for="p in profiles.filter(p=>p.enabled&&p.config.skill_id===(props.skill||'chat'))" :key="p.id" :value="p.id">{{ p.name }} · v{{ p.revision }}</option></select></label><a href="/#/settings/runner/profiles">管理执行方案与 MCP</a><p v-if="error" role="alert">{{ error }}</p></div></div></template>
<style scoped>.run-profile{padding:6px 12px;font-size:12px}select{max-width:100%;margin:6px}a{margin:6px}</style>
