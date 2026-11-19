<script setup lang="ts">
import {computed,nextTick,ref,watch} from 'vue'
import {guidesApi,type GuideItem} from '@/api/guides'
import {readerApi} from '@/api/reader'
import {uid32} from '@/api/client'
import {renderMarkdown} from '@/shared/markdown'
import type {PaperGuideController} from '@/reader/usePaperGuide'
import type {SelectionContext} from '@/api/types'
const props=defineProps<{controller:PaperGuideController;paperId:number;jump:(ctx:SelectionContext)=>void;refreshAnnotations:()=>Promise<void>}>()
const guide=computed(()=>props.controller.state.value.guide),busy=ref(false),message=ref(''),filter=ref('all')
const labels:Record<string,string>={problem:'问题',contribution:'贡献',method:'方法',definition:'定义',formula:'公式',figure:'图表',experiment:'实验',limitation:'边界'}
const priorities:Record<string,string>={essential:'必看',recommended:'建议看',optional:'按需阅读'}
const claims:Record<string,string>={author_claim:'作者主张',reported_evidence:'论文报道的证据',agent_interpretation:'AI 解释',reading_question:'建议核对的问题'}
const items=computed(()=>guide.value?.items.filter(i=>filter.value==='all'||i.item.category===filter.value)??[])
const panel=ref<HTMLElement|null>(null)
watch(()=>props.controller.focusItem.value,async id=>{if(!id)return;await nextTick();panel.value?.querySelector(`[data-guide-item="${id}"]`)?.scrollIntoView({block:'nearest',behavior:'smooth'})},{immediate:true})
function locate(i:GuideItem){const a=i.anchors[0];if(!a||!guide.value)return;props.jump({paper_id:props.paperId,file_version:guide.value.file_version,page:a.page,quote:a.status==='verified'?a.quote:'',rects:a.rects})}
async function action(fn:()=>Promise<unknown>){if(busy.value)return;busy.value=true;message.value='';try{await fn()}catch(e){message.value=e instanceof Error?e.message:'操作失败'}finally{busy.value=false}}
async function hideItem(i:GuideItem){const hidden=i.annotations.every(a=>!!a.deleted);await action(async()=>{for(const a of i.annotations)await readerApi.patchAnnotation(a.id,{deleted:!hidden});await props.controller.refresh();await props.refreshAnnotations()})}
async function adopt(i:GuideItem){await action(async()=>{await guidesApi.adopt(i.id,uid32());await props.refreshAnnotations();message.value='已采纳为可编辑的个人批注，后续生成不会覆盖。'})}
function exportGuide(){if(!guide.value?.result)return;const g=guide.value;const md=['# 论文导读',...Object.entries(g.result!.summary).map(([k,v])=>`## ${k}\n\n${v}`),...g.items.map(i=>`## ${i.item.title}\n\n${i.item.why_important_md}\n\n${i.item.explanation_md}\n\n来源物理页：${i.anchors.map(a=>a.page).join(', ')}；PDF ${g.file_version}`)].join('\n\n');const url=URL.createObjectURL(new Blob([md],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`paper-guide-${props.paperId}.md`;a.click();URL.revokeObjectURL(url)}
</script>
<template>
<section ref="panel" class="paper-guide-panel" aria-label="论文导读与智能批注">
 <p v-if="!guide" class="muted">可在右侧输入框选择“自动批注”，确认后调用 Skill，生成总结、阅读路线和重点解释。打开论文不会自动生成。</p>
 <p v-if="controller.running.value" role="status">导读与批注生成中，可继续阅读原文。</p>
 <p v-if="controller.error.value" class="error">{{controller.error.value}}</p>
 <template v-if="guide?.result">
  <div class="guide-overview"><strong>{{guide.status==='partial'?'部分材料导读':'论文导读'}}</strong><p>已提供物理页：{{guide.coverage.provided_pages?.join('、')||'未提供'}}{{guide.coverage.truncated?' · 文本已截断':''}}。本次没有图像/代码分析。</p><label><input v-model="controller.showAI.value" type="checkbox">显示 AI 批注图层</label><div><button @click="exportGuide">导出 MD</button><button @click="controller.refresh">刷新</button></div></div>
  <section v-for="(label,key) in {problem_md:'研究问题',approach_md:'核心思路',contributions_md:'贡献',limitations_md:'范围与边界'}" :key="key"><h3>{{label}}</h3><div class="markdown-content" v-html="renderMarkdown(guide.result.summary[key])"></div></section>
  <h3>建议阅读路线</h3><ol class="guide-route"><li v-for="r in guide.result.reading_route" :key="r.key"><strong>{{r.title}}</strong><div class="markdown-content" v-html="renderMarkdown(r.goal_md)"></div><button v-if="guide.items.find(i=>r.item_keys.includes(i.item.key))" @click="locate(guide.items.find(i=>r.item_keys.includes(i.item.key))!)">跳到原文</button></li></ol>
  <h3>重点与解释</h3><select v-model="filter" aria-label="按批注类型筛选"><option value="all">所有类型</option><option v-for="(label,key) in labels" :key="key" :value="key">{{label}}</option></select>
  <article v-for="i in items" :key="i.id" :data-guide-item="i.id" class="guide-item" :class="{focused:controller.focusItem.value===i.id}"><div class="guide-tags">AI · {{labels[i.item.category]}} · {{priorities[i.item.priority]}}</div><h4>{{i.item.title}}</h4><small>{{claims[i.item.claim_type]}} · {{i.location_status==='verified'?'原文定位已核验':'仅页级定位，未画精确高亮'}}</small><div class="markdown-content" v-html="renderMarkdown(i.item.why_important_md)"></div><details :open="controller.focusItem.value===i.id"><summary>解释与来源</summary><div class="markdown-content" v-html="renderMarkdown(i.item.explanation_md)"></div><blockquote v-for="(a,j) in i.anchors.filter(a=>a.status==='verified')" :key="j">{{a.quote}}<br>物理页 {{a.page}}</blockquote><p v-for="u in i.item.uncertainties" :key="u" class="muted">未确定：{{u}}</p><ul><li v-for="q in i.item.follow_up_questions" :key="q">{{q}}</li></ul></details><div class="guide-item-actions"><button @click="locate(i)">原文</button><button :disabled="busy" @click="adopt(i)">采纳为我的批注</button><button :disabled="busy" @click="hideItem(i)">{{i.annotations.every(a=>!!a.deleted)?'恢复标记':'移除标记'}}</button></div></article>
  <p v-for="u in guide.result.unknown_fields" :key="u.path" class="muted">材料缺口：{{u.reason}}</p>
  <p class="muted">费用估算：{{guide.cost===null?'未提供':'$'+guide.cost.toFixed(4)}}，非核实账单。</p>
 </template>
 <p v-if="controller.state.value.older_versions" class="muted">存在旧 PDF 版本的导读，未叠加到当前原文。</p><p v-if="message" role="status">{{message}}</p>
</section>
</template>
<style scoped>
.paper-guide-panel{padding:12px;font-size:12px;overflow-wrap:anywhere}.paper-guide-panel h3{font-size:13px;margin:18px 0 8px}.paper-guide-panel h4{font-size:13px;margin:7px 0}.guide-overview{padding:10px;background:var(--accent-soft);border-radius:8px}.guide-overview p{line-height:1.7}.guide-overview button{margin-top:8px}.paper-guide-panel button{font-size:10px;padding:4px 6px}.guide-route{padding-left:20px}.guide-route li{margin:12px 0}.guide-item{padding:12px 0;border-bottom:1px solid var(--border);scroll-margin-top:12px}.guide-item.focused{background:var(--accent-soft);border-radius:6px;padding:10px}.guide-tags{color:var(--accent);font-size:10px}.guide-item small,.muted{color:var(--text-muted);font-size:11px;line-height:1.7}.guide-item details{margin:10px 0}.guide-item summary{cursor:pointer;color:var(--accent)}.guide-item blockquote{border-left:2px solid var(--border);padding-left:8px;margin:10px 0}.guide-item-actions{display:flex;flex-wrap:wrap;gap:5px}.error{color:var(--danger)}
</style>
