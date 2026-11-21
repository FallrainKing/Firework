<script setup lang="ts">
import {computed,ref} from 'vue'
import type {PaperGuideController} from '@/reader/usePaperGuide'
const props=withDefaults(defineProps<{controller:PaperGuideController;ready:boolean;pageCount:number;readingBusy?:boolean;menuOpen?:boolean}>(),{menuOpen:true})
const emit=defineEmits<{'read':[prompt:string];'show-guide':[];'selected':[]}>()
const choice=ref<'annotate'|'read'|null>(null),goal=ref('理解论文重点、建议阅读顺序及重要内容的解释'),skillId=ref('paper_guide'),maxItems=ref(6),maxPages=ref(6)
const selected=computed(()=>props.controller.skills.value.find(x=>x.id===skillId.value))
async function select(mode:'annotate'|'read'){choice.value=mode;emit('selected');if(mode==='annotate')await props.controller.loadSkills()}
async function confirm(){if(choice.value==='read'){emit('read',goal.value.trim()||'请读取这篇论文的已有材料，概述问题、方法、实验和局限，说明阅读覆盖。');choice.value=null;return}if(!selected.value)return;await props.controller.start({skill_id:selected.value.id,skill_version_id:selected.value.version_id,reading_goal:goal.value,max_items:maxItems.value,max_pages:Math.min(maxPages.value,props.pageCount)});if(!props.controller.error.value){choice.value=null;emit('show-guide')}}
</script>
<template>
<section v-if="menuOpen||choice||controller.running.value||controller.error.value||controller.state.value.task?.error" class="guide-actions" aria-label="论文阅读任务">
 <template v-if="menuOpen"><h3>阅读任务 <small>确认后执行</small></h3><div class="guide-suggestions"><button type="button" :disabled="!ready||controller.busy.value||controller.running.value" @click="select('annotate')">自动批注</button><button type="button" :disabled="!ready||readingBusy" @click="select('read')">阅读论文</button><button v-if="controller.state.value.guide" type="button" @click="emit('show-guide');emit('selected')">查看导读</button></div></template>
 <p v-if="controller.running.value" role="status">批注 Skill 正在执行，打开或刷新不会重复触发。<button type="button" :disabled="controller.busy.value" @click="controller.cancel">停止</button></p>
 <div v-if="choice" class="guide-confirm">
  <strong>{{choice==='annotate'?'生成导读与原文批注':'开始论文阅读'}}</strong>
  <label>阅读要求<textarea v-model="goal" rows="2" maxlength="500" aria-label="Skill 阅读要求"></textarea></label>
  <template v-if="choice==='annotate'"><label>使用 Skill<select v-model="skillId" aria-label="自动批注技能"><option v-for="s in controller.skills.value" :key="s.id" :value="s.id">{{s.name}}</option></select></label><div class="guide-limits"><label>重点数量<input v-model.number="maxItems" type="number" min="1" max="10"></label><label>最多材料页<input v-model.number="maxPages" type="number" min="1" :max="Math.min(6,pageCount)"></label></div><p>本次调用现有智能体，预算上限 {{selected?'$'+selected.max_budget_usd.toFixed(2):'待选择技能'}}。部分材料会如实标注，当前不看图、不读代码。相同结果优先复用。</p></template>
  <p v-else>确认后在新的阅读会话调用现有阅读 Skill；仅打开此提示不会执行任务。</p>
  <div class="guide-buttons"><button type="button" @click="choice=null">取消</button><button type="button" class="primary" :disabled="controller.busy.value||readingBusy||(choice==='annotate'&&!selected)" @click="confirm">{{choice==='annotate'?'确认生成批注':'确认开始阅读'}}</button></div>
 </div>
 <p v-if="controller.error.value" class="error" role="alert">{{controller.error.value}}</p>
 <p v-if="controller.state.value.task?.error" class="error">{{controller.state.value.task.error}} <button type="button" :disabled="controller.busy.value" @click="controller.hide">移除失败记录</button></p>
</section>
</template>
<style scoped>
.guide-actions{padding:8px;font-size:12px}.guide-actions h3{font-size:12px;margin:0 0 8px}.guide-actions small{color:var(--text-muted);font-weight:400;margin-left:6px}.guide-suggestions{display:flex;align-items:center;flex-wrap:wrap;gap:6px}.guide-actions button{font-size:12px;padding:4px 7px}.guide-confirm{display:grid;gap:9px;padding-top:10px}.guide-confirm label{display:grid;gap:4px}.guide-confirm textarea,.guide-confirm select,.guide-confirm input{width:100%;min-width:0;box-sizing:border-box}.guide-limits{display:grid;grid-template-columns:1fr 1fr;gap:8px}.guide-confirm p{margin:0;color:var(--text-muted);line-height:1.6}.guide-buttons{display:flex;gap:8px;justify-content:flex-end}.error{color:var(--danger)}
</style>
