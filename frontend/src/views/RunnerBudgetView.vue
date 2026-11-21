<script setup lang="ts">
import {onMounted,ref} from 'vue'
import RunnerSettingsNav from '@/components/RunnerSettingsNav.vue'
import {runnerBudgets,type Budget,type BudgetList,type BudgetValues,type BudgetPreview} from '@/api/runnerBudgets'
const data=ref<BudgetList|null>(null),error=ref(''),notice=ref(''),busy=ref(false),selected=ref(''),name=ref('我的研究额度'),editing=ref<Budget|null>(null),skill=ref('chat'),preview=ref<BudgetPreview|null>(null)
const values=ref<BudgetValues>({max_turns:24,max_output_tokens:8192,max_calls:24,timeout_s:1800,cost_mode:'disabled',max_budget_usd:null})
async function action(fn:()=>Promise<void>){busy.value=true;error.value='';notice.value='';try{await fn()}catch(e){error.value=e instanceof Error?e.message:'操作失败'}finally{busy.value=false}}
async function load(){await action(async()=>{data.value=await runnerBudgets.list();selected.value=data.value.default_budget_id||''})}
function edit(b:Budget,copy=false){editing.value=copy||b.builtin?null:b;name.value=b.name+(copy||b.builtin?'（副本）':'');values.value={...b.values};preview.value=null}
async function save(){await action(async()=>{const b=await runnerBudgets.save(name.value,values.value,editing.value||undefined);data.value=await runnerBudgets.list();editing.value=b;name.value=b.name;notice.value='额度已保存；正在运行和历史任务保持原配置。'})}
async function apply(){await action(async()=>{data.value=await runnerBudgets.setDefault(selected.value||null,data.value!.settings_revision);notice.value='默认额度已更新，仅影响之后创建的任务。'})}
async function check(){await action(async()=>{const b=data.value?.budgets.find(x=>x.id===selected.value);preview.value=await runnerBudgets.preview(skill.value,b?{id:b.id,revision:b.revision}:null,!b)})}
onMounted(load)
</script>
<template>
 <main class="budget-page">
  <RunnerSettingsNav/><h1>Runner · 任务额度</h1>
  <p>当前账号独立保存。此页配置任务额度；模型连接已提供独立入口，MCP 管理仍在后续交付。</p>
  <p role="alert" v-if="error" class="error">{{ error }} <button @click="load" :disabled="busy">重新载入</button></p><p role="status">{{ notice }}</p>
  <section v-if="data"><h2>账号默认额度</h2>
   <label>新任务使用 <select v-model="selected" :disabled="busy"><option value="">沿用各 Skill 原有额度</option><option v-for="b in data.budgets" :key="b.id" :value="b.id">{{ b.name }} · v{{ b.revision }}</option></select></label>
   <button :disabled="busy" @click="apply">保存默认选择</button>
   <p>原有额度可能包含 $0.20 估价上限。选择“标准研究”可关闭该金额守卫，同时保留轮次、输出、工具次数和时长限制。不会自动重跑失败任务。</p>
   <label>验证任务 <select v-model="skill"><option value="chat">阅读问答</option><option value="paper_guide">阅读导读与批注</option><option value="frontier_monitor">前沿追踪</option></select></label><button :disabled="busy" @click="check">仅校验所选额度，不调用模型</button>
   <div v-if="preview"><p>{{ preview.warning }}</p><pre>{{ JSON.stringify(preview.effective,null,2) }}</pre><p>保留工具权限：{{ preview.tools.join('、') || '无' }}</p></div>
   <h2>额度预设</h2><ul><li v-for="b in data.budgets" :key="b.id">{{ b.name }} · v{{ b.revision }} · {{ b.values.max_turns }} 轮 / {{ b.values.timeout_s }} 秒 <button :disabled="busy" @click="edit(b,true)">复制</button><button v-if="!b.builtin" :disabled="busy" @click="edit(b)">编辑</button></li></ul>
   <h2>{{ editing?'修改额度':'新建额度' }}</h2>
   <form @submit.prevent="save">
    <label>名称<input v-model="name" maxlength="80" required /></label>
    <label>每轮任务最大推理轮次<input type="number" v-model.number="values.max_turns" min="1" max="100" required /></label>
    <label>单次模型输出 token 上限<input type="number" v-model.number="values.max_output_tokens" min="256" max="32768" required /></label>
    <label>本轮工具调用上限<input type="number" v-model.number="values.max_calls" min="0" max="100" required /></label>
    <label>本轮执行时长上限（秒）<input type="number" v-model.number="values.timeout_s" min="30" max="7200" required /></label>
    <label>金额限制<select v-model="values.cost_mode" @change="values.max_budget_usd=values.cost_mode==='disabled'?null:1"><option value="disabled">关闭 CLI 估价金额守卫</option><option value="cli_estimate_guard">启用 CLI 估价金额守卫</option></select></label>
    <label v-if="values.cost_mode==='cli_estimate_guard'">CLI 估价金额上限（美元）<input type="number" v-model.number="values.max_budget_usd" min="0.001" max="100" step="0.001" required /></label>
    <p>金额为 CLI 估算，无法保证服务商账单硬上限。输出限制不是累计 token 限制；尚不提供请求级或累计 token 硬限制。</p>
    <button :disabled="busy || !name.trim()" type="submit">{{ busy?'保存中…':'保存额度' }}</button>
   </form>
  </section>
 </main>
</template>
<style scoped>
.budget-page{max-width:1000px;margin:0 auto;padding:28px;overflow:auto;height:100%;box-sizing:border-box}.budget-page section{display:grid;gap:14px}.budget-page form{display:grid;gap:14px;max-width:620px}.budget-page label{display:grid;gap:6px}.budget-page input,.budget-page select{padding:9px;max-width:100%}.budget-page li{padding:9px 0}.budget-page button{padding:7px 12px;width:fit-content;margin-right:8px}.budget-page pre{white-space:pre-wrap}.error{color:#b33}.budget-page p{line-height:1.6}
</style>
