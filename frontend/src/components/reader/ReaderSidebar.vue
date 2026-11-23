<script setup lang="ts">
import GuideActions from './GuideActions.vue'
import GuidePanel from './GuidePanel.vue'
import type { PaperGuideController } from '@/reader/usePaperGuide'
import { renderMarkdown } from '@/shared/markdown'
import {api} from '@/api/client'
import { computed, ref, watch } from 'vue'
import StateFeedback from '@/components/StateFeedback.vue'
import { readerApi } from '@/api/reader'
import type { Annotation, Position, ReaderDoc, SelectionContext, Session, TranslationRecord } from '@/api/types'

interface Orch {
  setTab: (tab: Position['tab']) => void
  savePosition: () => void
  jump: (ctx: SelectionContext) => void
  selectionAction: (action: string, ctx: SelectionContext, color?: string) => Promise<void>
  watchRun: (runId: string) => void
  refreshAnnotations: () => Promise<void>
  sidebarTab: { value: Position['tab'] }
  noteContext: { value: SelectionContext | null }
  profile: { value: { id: number; title: string; authors?: string[]; affiliations?: string[]; abstract?: string | null; summary?: string; doi?: string | null; affiliation_source?: string } | null }
  annotationsVersion: { value: number }
  positionSnapshot: () => { page: number } | null
}

const props = defineProps<{ doc: ReaderDoc | null; session: Session | null; orchestrator?: unknown; guideController?: PaperGuideController }>()
const orch = props.orchestrator as Orch | undefined

const TABS: Array<{ id: Position['tab']; label: string }> = [
  { id: 'outline', label: '目录' },
  { id: 'notes', label: '批注' },
  { id: 'guide', label: '导读' },
  { id: 'translations', label: '译文' },
  { id: 'info', label: '信息' },
]

const tab = ref<Position['tab']>('outline')
const originFilter=ref('all')
const annotations = ref<Annotation[]>([])
const readingArtifacts=ref<{id:string;title:string;kind:string;markdown:string;current_revision:number}[]>([])
async function adoptExternal(a:Annotation){try{await api(`/api/reader/annotations/${a.id}/adopt`,{method:'POST'});await refresh();await orch?.refreshAnnotations()}catch(e){showToast(String(e))}}
const translations = ref<TranslationRecord[]>([])
const visibleAnnotations=computed(()=>annotations.value.filter(a=>originFilter.value==='all'||(originFilter.value==='ai'?a.origin==='ai':a.origin!=='ai')))
const noteText = ref('')
const editingNote=ref<Annotation|null>(null)
function editNote(a:Annotation){editingNote.value=a;noteText.value=a.content||'';focusNote()}
async function readFromSidebar(prompt:string){const ctx=orch?.noteContext.value;await orch?.selectionAction('chat',ctx||{paper_id:props.doc!.paper_id,file_version:props.doc!.file_version,page:1,quote:prompt,rects:[]})}
const toast = ref<{ message: string; undo?: () => Promise<void> } | null>(null)
const loading = ref(false)
const loadError = ref<string | null>(null)
const savingNote = ref(false)
const noteSaved = ref(false)
const noteSaveError = ref<string | null>(null)
const noteArea = ref<HTMLTextAreaElement | null>(null)

function showToast(message: string, undo?: () => Promise<void>) {
  toast.value = { message, undo }
  setTimeout(() => { toast.value = null }, 6000)
}

function setTab(t: Position['tab']) {
  tab.value = t
  orch?.setTab(t)
  orch?.savePosition()
}

function focusNote() {
  setTab('notes')
  noteArea.value?.focus()
}

async function refresh() {
  if (!props.doc) return
  loading.value = true
  loadError.value = null
  try {
    const [a, t] = await Promise.all([readerApi.annotations(props.doc.paper_id), readerApi.translations(props.doc.paper_id)])
    annotations.value = a.annotations
    translations.value = t.translations
    try{readingArtifacts.value=(await api<{artifacts:typeof readingArtifacts.value}>(`/api/research/artifacts?paper_id=${props.doc.paper_id}&limit=100`)).artifacts.filter(a=>['reading','guide'].includes(a.kind))}catch{readingArtifacts.value=[]}
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '阅读记录载入失败'
  } finally {
    loading.value = false
  }
}

watch(() => orch?.annotationsVersion.value, () => { void refresh() })
// 编排器侧的 tab 变更（恢复位置/高亮/翻译）同步到 UI，不回写位置。
watch(() => orch?.sidebarTab.value, t => { if (t) tab.value = t==='highlights'?'notes':t }, { immediate: true })
watch(() => props.doc, d => { if (d) void refresh() }, { immediate: true })
watch(() => orch?.noteContext.value, ctx => { if (ctx) focusNote() })

async function saveNote() {
  const content = noteText.value.trim()
  noteSaved.value = false
  noteSaveError.value = null
  if (!content) { noteSaveError.value = '请填写批注'; return }
  if (!props.doc) { noteSaveError.value = '请先添加 PDF 全文'; return }
  const c = orch?.noteContext.value ?? { paper_id: props.doc.paper_id, page: orch?.positionSnapshot()?.page ?? 1, file_version: props.doc.file_version, quote: '', rects: [] }
  savingNote.value = true
  try {
    if(editingNote.value)await readerApi.patchAnnotation(editingNote.value.id,{content})
    else await readerApi.createAnnotation({ ...c, kind: 'note', content, conversation_id: props.session?.id })
    editingNote.value=null
    noteText.value = ''
    if (orch) orch.noteContext.value = null
    noteSaved.value = true
    await refresh()
    await orch?.refreshAnnotations()
  } catch (e) {
    noteSaveError.value = e instanceof Error ? e.message : '批注保存失败'
  } finally {
    savingNote.value = false
  }
}

watch(noteText, () => { noteSaved.value = false; noteSaveError.value = null })

async function removeAnnotation(id: string) {
  try {
    await readerApi.patchAnnotation(id, { deleted: true })
    await refresh()
    await orch?.refreshAnnotations()
    showToast('已移除，可撤销。', async () => {
      await readerApi.patchAnnotation(id, { deleted: false })
      await refresh()
      await orch?.refreshAnnotations()
    })
  } catch (e) {
    showToast(e instanceof Error ? e.message : '移除失败')
  }
}

async function removeTranslation(id: string) {
  try {
    await readerApi.setTranslationVisible(id, true)
    await refresh()
    showToast('翻译记录已移除，可撤销。', async () => {
      await readerApi.setTranslationVisible(id, false)
      await refresh()
    })
  } catch (e) {
    showToast(e instanceof Error ? e.message : '移除失败')
  }
}

async function retryTranslation(t: TranslationRecord) {
  try {
    const r = await readerApi.translate({ paper_id: t.paper_id, page: t.page, file_version: t.file_version, quote: t.quote, rects: t.rects||[], conversation_id: props.session!.id })
    orch?.watchRun(r.run_id)
    await refresh()
  } catch (e) {
    showToast(e instanceof Error ? e.message : '重试失败')
  }
}

function locate(a: { page: number; file_version: string; paper_id?: number;quote?:string;rects?:number[][] }) {
  orch?.jump({ paper_id: a.paper_id ?? props.doc!.paper_id, page: a.page, file_version: a.file_version, quote: a.quote||'', rects: a.rects||[] })
}

function quoteToChat(a: Annotation) {
  void orch?.selectionAction('chat', { paper_id: a.paper_id, page: a.page, file_version: a.file_version, quote: a.quote, rects: a.rects })
}

function renderMd(text: string): string { return renderMarkdown(text) }

const versionMismatch = (fv: string) => fv !== props.doc?.file_version

defineExpose({ editNote, focusNote, refresh, setTab })
</script>

<template>
  <div class="reader-sidebar">
    <div class="sidebar-tabs" role="tablist">
      <button v-for="t in TABS" :key="t.id" role="tab" :data-tab="t.id" :aria-selected="tab === t.id" @click="setTab(t.id)">{{ t.label }}</button>
    </div>

    <select v-if="tab==='notes'||tab==='highlights'" v-model="originFilter" aria-label="批注来源"><option value="all">全部批注</option><option value="user">我的批注</option><option value="ai">AI 导读批注</option></select>
    <GuidePanel class="tab-pane" v-if="tab === 'guide' && guideController && doc && orch" :controller="guideController" :paper-id="doc.paper_id" :file-version="doc.file_version" :jump="orch.jump" :refresh-annotations="orch.refreshAnnotations" />
    <div v-if="tab==='guide'" class="tab-pane"><article v-for="a in readingArtifacts" :key="a.id" class="aux-entry"><h3>{{a.title}}</h3><RouterLink :to="`/research?artifact=${a.id}`">产物 · v{{a.current_revision}}</RouterLink><div class="markdown-content" v-html="renderMd(a.markdown)"></div></article></div>
    <div v-show="tab === 'outline'" class="tab-pane">
      <button v-for="(item, i) in doc?.outline ?? []" :key="i" class="outline-button" :style="{ paddingLeft: Math.min(item.level - 1, 3) * 10 + 'px' }" @click="locate({ page: item.page, file_version: doc!.file_version })">
        <span>{{ item.title }}</span><small class="muted">第 {{ item.page }} 页</small>
      </button>
      <StateFeedback
        :loading="loading && !doc?.outline?.length"
        :error="loadError"
        :empty="!loading && !loadError && !doc?.outline?.length"
        empty-text="未识别到可靠目录，可通过工具栏按页阅读。"
        @retry="refresh()"
      />
    </div>

    <div v-show="tab === 'notes'||tab==='highlights'" class="tab-pane">
      <GuideActions v-if="guideController&&doc" :controller="guideController" :ready="!!session" :page-count="doc.page_count" :annotations-only="true" @show-guide="setTab('notes')" />
      <GuidePanel v-if="guideController&&doc&&orch&&originFilter!=='user'" mode="annotations" :controller="guideController" :paper-id="doc.paper_id" :file-version="doc.file_version" :jump="orch.jump" :refresh-annotations="orch.refreshAnnotations" />
      <div class="note-composer"><button v-if="editingNote" @click="editingNote=null;noteText=''">取消编辑备注</button>
        <p v-if="orch?.noteContext.value" class="note-context muted">第 {{ orch.noteContext.value.page }} 页<br />{{ orch.noteContext.value.quote }}</p>
        <textarea ref="noteArea" v-model="noteText" class="note-text" rows="3" placeholder="写下批注…"></textarea>
        <button class="primary save-note" :disabled="savingNote" @click="saveNote">{{ savingNote ? '保存中…' : '保存批注' }}</button>
        <StateFeedback
          :saving="savingNote"
          :saved="noteSaved"
          :save-error="noteSaveError"
        />
      </div>
      <article v-for="a in visibleAnnotations.filter(x=>!(x.origin==='ai'&&x.guide_item_id)) .sort((a,b)=>a.page-b.page)" :key="a.id" class="aux-entry">
        <strong><span class="entry-color" :style="{ background: a.color }"></span>{{a.kind==='highlight'?'高亮':a.kind==='ink'?'笔迹':'批注'}} · 第 {{ a.page }} 页 <small>{{a.origin==='ai'?'AI':a.origin==='ai_adopted'?'已采纳':''}}</small></strong>
        <blockquote v-if="a.quote">{{ a.quote }}</blockquote>
        <div v-if="a.content" class="markdown-content" v-html="renderMd(a.content)"></div>
        <div class="entry-actions">
          <button :disabled="versionMismatch(a.file_version)" @click="locate(a)">定位</button>
          <button v-if="a.quote" @click="quoteToChat(a)">加入对话</button>
          <button v-if="a.origin==='ai'&&!a.guide_item_id" @click="adoptExternal(a)">采纳为个人批注</button><button v-if="a.origin!=='ai'" @click="editNote(a)">编辑备注</button><button class="delete-annotation" @click="removeAnnotation(a.id)">删除</button>
        </div>
        <p v-if="versionMismatch(a.file_version)" class="muted">来自旧 PDF 版本，暂不自动定位。</p>
      </article>
      <StateFeedback
        :loading="loading && !visibleAnnotations.some(x => x.kind === 'note')"
        :error="loadError"
        :empty="!loading && !loadError && !visibleAnnotations.some(x => x.kind === 'note')"
        empty-text="这里会保存你的阅读记录。"
        @retry="refresh()"
      />
    </div>

    <div v-show="tab === 'translations'" class="tab-pane">
      <article v-for="t in translations" :key="t.id" class="aux-entry">
        <button class="link" @click="locate(t)">原文 · 第 {{ t.page }} 页</button>
        <blockquote>{{ t.quote }}</blockquote><small v-if="t.status==='partial'">部分译文</small>
        <div v-if="t.status === 'succeeded'||t.status==='partial'" class="answer markdown-content" v-html="renderMd(t.answer)"></div>
        <p v-else class="muted">{{ t.status === 'failed' ? '翻译失败，可重新选择原文后重试。' : t.status === 'cancelled' ? '翻译已取消，可重新选择原文后重试。' : '智能体正在翻译…' }}</p>
        <div class="entry-actions">
          <button class="delete-translation" @click="removeTranslation(t.id)">删除</button>
          <button v-if="t.status === 'failed' || t.status === 'cancelled'" class="retry-translation" @click="retryTranslation(t)">重试</button>
        </div>
      </article>
      <StateFeedback
        :loading="loading && !translations.length"
        :error="loadError"
        :empty="!loading && !loadError && !translations.length"
        empty-text="暂无翻译记录，选中原文即可开始。"
        @retry="refresh()"
      />
    </div>

    <div v-show="tab === 'info'" class="tab-pane paper-info">
      <template v-if="orch?.profile.value">
        <h2>{{ orch.profile.value.title }}</h2>
        <p>{{ (orch.profile.value.authors ?? []).join(' · ') }}</p>
        <p>{{ (orch.profile.value.affiliations ?? []).join(' · ') || '作者单位待补全' }}</p>
        <p class="muted">{{ orch.profile.value.abstract || orch.profile.value.summary || '暂无摘要' }}</p>
        <p v-if="orch.profile.value.doi">DOI：{{ orch.profile.value.doi }}</p>
        <p v-if="orch.profile.value.affiliation_source === 'pdf_first_page_unverified'" class="muted">单位由 PDF 首页提取，待核对。</p>
      </template>
    </div>

    <div v-if="toast" class="sidebar-toast" role="status">
      {{ toast.message }}
      <button v-if="toast.undo" class="undo" @click="toast.undo().then(() => { toast = null })">撤销</button>
    </div>
  </div>
</template>

<style scoped>
.reader-sidebar { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.sidebar-tabs { display: flex; border-bottom: 1px solid var(--border); }
.sidebar-tabs button { flex: 1; border: none; border-radius: 0; padding: var(--space-2) 0; font-size: 12px; color: var(--text-muted); }
.sidebar-tabs button[aria-selected='true'] { color: var(--accent); background: var(--accent-soft); }
.tab-pane { flex: 1; overflow-y: auto; padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-2); }
.outline-button { display: flex; justify-content: space-between; gap: var(--space-2); border: none; background: none; text-align: left; padding: var(--space-1) var(--space-2); }
.outline-button:hover { background: var(--accent-soft); color: var(--accent); }
.aux-entry { border: 1px solid var(--border); border-radius: var(--radius); padding: var(--space-2); background: var(--bg); display: flex; flex-direction: column; gap: var(--space-1); font-size: 13px; }
.entry-color { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: var(--space-1); }
blockquote { margin: 0; padding-left: var(--space-2); border-left: 3px solid var(--border); color: var(--text-muted); font-size: 12px; }
.entry-actions { display: flex; gap: var(--space-1); }
.entry-actions button { padding: var(--space-1) var(--space-2); font-size: 12px; }
.note-composer { display: flex; flex-direction: column; gap: var(--space-2); }
.link { border: none; background: none; color: var(--accent); padding: 0; text-align: left; }
.sidebar-toast { padding: var(--space-2) var(--space-3); border-top: 1px solid var(--border); font-size: 12px; display: flex; gap: var(--space-2); align-items: center; }
.paper-info h2 { font-size: 15px; margin: 0; }
</style>
