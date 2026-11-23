<script setup lang="ts">
import {ref} from 'vue'
import {runnerBudgets,type BudgetList,type BudgetRef,type BudgetPreview} from '@/api/runnerBudgets'
const props=defineProps<{modelValue:BudgetRef|null;disabled?:boolean;skill?:string}>()
const emit=defineEmits<{'update:modelValue':[BudgetRef|null]}>()
const opened=ref(false),data=ref<BudgetList|null>(null),error=ref(''),preview=ref<BudgetPreview|null>(null),busy=ref(false)
async function open(){opened.value=!opened.value;if(opened.value){busy.value=true;try{data.value=await runnerBudgets.list();error.value=''}catch(e){error.value=e instanceof Error?e.message:'读取失败'}finally{busy.value=false}}}
async function change(e:Event){const b=data.value?.budgets.find(b=>b.id===(e.target as HTMLSelectElement).value);const v=b?{id:b.id,revision:b.revision}:null;emit('update:modelValue',v);preview.value=null;busy.value=true;try{preview.value=await runnerBudgets.preview(props.skill||'chat',v);error.value=''}catch(e){error.value=e instanceof Error?e.message:'校验失败'}finally{busy.value=false}}
</script>
<template><div class="run-budget"><button type="button" :disabled="disabled" :aria-expanded="opened" @click="open">任务额度{{ modelValue?' · 本轮自选':'' }}</button><div v-if="opened"><label>本次发送 <select :value="modelValue?.id||''" :disabled="disabled||busy" @change="change"><option value="">使用账号默认额度</option><option v-for="b in data?.budgets||[]" :key="b.id" :value="b.id">{{ b.name }} · v{{ b.revision }}</option></select></label><a href="/#/settings/runner/budgets">管理额度</a><p v-if="error" role="alert">{{ error }}</p><p v-if="preview">{{ preview.effective.max_turns }} 轮 · {{ preview.effective.max_calls }} 次工具 · {{ preview.effective.timeout_s }} 秒</p></div></div></template>
<style scoped>.run-budget{padding:6px 12px;font-size:12px}.run-budget select{max-width:100%;margin:6px}.run-budget a{margin:6px}.run-budget small{display:block;color:var(--text-muted,#777)}</style>
