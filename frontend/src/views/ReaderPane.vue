<script setup lang="ts">
import { nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { PDFReader } from '@/reader/pdf-engine'
import { useReaderOrchestrator } from '@/reader/useReaderOrchestrator'
import { useReaderLayout } from '@/reader/useReaderLayout'
import { sessionsApi } from '@/api/sessions'
import type { SelectionContext, Session } from '@/api/types'
import ReaderSidebar from '@/components/reader/ReaderSidebar.vue'
import ChatPanel from '@/components/reader/ChatPanel.vue'
import TaskDialog from '@/components/TaskDialog.vue'

const props = defineProps<{ paperId: number; sessionId?: number | null }>()
const emit = defineEmits<{
  'open-paper': [paperId: number, sessionId?: number]
  'open-import': [paperId: number]
  'session-bound': [sessionId: number]
  'save-failed': [message: string]
}>()

const toast = (m: string) => emit('save-failed', m)
const scrollEl = ref<HTMLElement | null>(null)
const pagesEl = ref<HTMLElement | null>(null)
const chatRef = ref<InstanceType<typeof ChatPanel> | null>(null)
const sidebarRef = ref<InstanceType<typeof ReaderSidebar> | null>(null)

const pageInput = ref(1)
const selected = ref<(SelectionContext & { screen: { left: number; bottom: number; top: number } }) | null>(null)
const popupStyle = ref<Record<string, string>>({})
const sessions = ref<Session[]>([])
const dialogOpen = ref(false)
const narrow = ref(window.innerWidth <= 760)
const mobileToolsOpen = ref(false)
const color = ref('#f5d76e')
const mode = ref('select')

let engine: PDFReader | null = null
const layout = useReaderLayout()
const orch = useReaderOrchestrator({
  paperId: props.paperId,
  engine: {
    load: (info, pos) => engine!.load(info, pos),
    layout: () => engine!.layout(),
    jump: (p, f) => engine!.jump(p, f),
    setAnnotations: items => engine!.setAnnotations(items),
    get currentPage() { return engine?.currentPage ?? 1 },
    set currentPage(v: number) { if (engine) engine.currentPage = v },
    get zoom() { return engine?.zoom ?? 'fit' },
    set zoom(v: string) { if (engine) engine.zoom = v },
    get info() { return engine!.info },
    get pdf() { return engine?.pdf },
  },
  toast,
  onOpenPaper: (pid, sid) => emit('open-paper', pid, sid),
  onOpenImport: pid => emit('open-import', pid),
  onSessionBound: sid => { emit('session-bound', sid); void refreshSessions(sid) },
})

async function refreshSessions(current?: number) {
  const { sessions: list } = await sessionsApi.list({ paper_id: props.paperId, limit: 100 })
  sessions.value = list.filter(s => ['paper_read', 'paper_review', 'paper_compare', 'chat'].includes(s.skill))
  if (current) orch.session.value = sessions.value.find(s => s.id === current) ?? orch.session.value
}

function onSelection(e: Event) {
  const detail = (e as CustomEvent).detail
  selected.value = detail
  if (detail) {
    const width = Math.min(340, window.innerWidth - 16)
    popupStyle.value = {
      left: Math.max(8, Math.min(detail.screen.left, window.innerWidth - width - 8)) + 'px',
      top: Math.max(55, Math.min(detail.screen.bottom + 8, window.innerHeight - 65)) + 'px',
    }
  }
}

async function runAction(action: string) {
  if (!selected.value) return
  const ctx: SelectionContext = { paper_id: selected.value.paper_id, page: selected.value.page, file_version: selected.value.file_version, quote: selected.value.quote, rects: selected.value.rects }
  selected.value = null
  await orch.selectionAction(action, ctx, color.value)
  window.getSelection()?.removeAllRanges()
  if (action === 'note') (sidebarRef.value as unknown as { focusNote?: () => void })?.focusNote?.()
  if (action === 'chat' || action === 'explain') layout.setMobile('chat')
  if (action === 'translate' || action === 'note') { if (narrow.value) layout.setMobile('left') }
}

function setTool(m: string) {
  mode.value = m
  engine?.setMode(m)
}

async function onSessionChange(id: number) {
  await orch.activate(id)
}

function onCreated(session: Session, _prompt: string) {
  dialogOpen.value = false
  if (session.paper_ids.includes(props.paperId)) void orch.activate(session.id, true)
  else emit('open-paper', session.paper_ids[0], session.id)
}

async function flush() {
  try { await orch.flush() } catch (e) { emit('save-failed', e instanceof Error ? e.message : '保存未完成') }
}

const onResize = () => { narrow.value = window.innerWidth <= 760 }

onMounted(async () => {
  window.addEventListener('resize', onResize)
  await nextTick()
  engine = new PDFReader(scrollEl.value!, pagesEl.value!)
  engine.addEventListener('page', e => { pageInput.value = (e as CustomEvent).detail; orch.savePosition() })
  engine.addEventListener('zoom', () => orch.savePosition())
  engine.addEventListener('selection', onSelection)
  engine.addEventListener('ink', e => orch.saveInk((e as CustomEvent).detail))
  engine.addEventListener('erase', e => orch.eraseAnnotation((e as CustomEvent).detail))
  const bridge = (chatRef.value as unknown as { bridge?: Parameters<typeof orch.registerChat>[0] })?.bridge
  if (bridge) orch.registerChat(bridge)
  await orch.boot(props.sessionId ?? null)
  pageInput.value = engine.currentPage
  await refreshSessions(orch.session.value?.id)
})

watch(() => props.sessionId, sid => { if (sid && sid !== orch.session.value?.id) void orch.activate(sid) })

onActivated(() => { if (engine?.pdf) { void nextTick(() => engine?.layout()) } })
onDeactivated(() => { selected.value = null; void flush() })
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  void flush()
  engine?.destroy()
})

defineExpose({ flush, orchestrator: orch })
</script>

<template>
  <div
    class="reading-layout"
    :class="{ 'hide-left': layout.layout.value.left_hidden, 'hide-chat': layout.layout.value.right_hidden }"
    :data-mobile="layout.mobileMode.value"
    :style="{ '--aux-width': layout.layout.value.left_width + 'px', '--chat-width': layout.layout.value.right_width + 'px' }"
  >
    <div class="reader-body">
      <aside class="left-pane">
        <ReaderSidebar ref="sidebarRef" :doc="orch.doc.value" :session="orch.session.value" :orchestrator="orch" />
      </aside>
      <div
        class="resizer" role="separator" aria-orientation="vertical" tabindex="0" aria-label="调整侧栏宽度"
        :aria-valuenow="layout.layout.value.left_width" aria-valuemin="140" aria-valuemax="600"
        @pointerdown="layout.startDrag('left', $event, $event.currentTarget as HTMLElement, layout.layout.value.left_width)"
        @keydown="layout.onResizerKey('left', $event)"
      ></div>
      <main class="pdf-pane" :aria-label="'论文原文：' + (orch.profile.value?.title ?? '论文阅读')">
        <div class="reader-top" role="toolbar" aria-label="论文阅读工具栏">
          <div class="page-controls">
            <button aria-label="上一页" @click="engine?.jump(pageInput - 1)">‹</button>
            <input v-model.number="pageInput" type="number" min="1" :max="orch.doc.value?.page_count ?? 1" aria-label="页码" @change="engine?.jump(pageInput)" @keydown.enter="engine?.jump(pageInput)" />
            <span class="muted">/ {{ orch.doc.value?.page_count ?? '—' }}</span>
            <button aria-label="下一页" @click="engine?.jump(pageInput + 1)">›</button>
          </div>
          <select class="zoom" :value="engine?.zoom ?? 'fit'" aria-label="缩放" @change="engine?.setZoom(($event.target as HTMLSelectElement).value)">
            <option value="fit">适合宽度</option>
            <option value="1">100%</option>
            <option value="1.25">125%</option>
            <option value="1.5">150%</option>
            <option value="2">200%</option>
          </select>
          <div v-if="!narrow" class="tools" role="group" aria-label="阅读工具">
            <button :aria-pressed="mode === 'select'" @click="setTool('select')">选择</button>
            <button :aria-pressed="mode === 'pen'" @click="setTool('pen')">画笔</button>
            <button :aria-pressed="mode === 'erase'" @click="setTool('erase')">橡皮</button>
            <input v-model="color" type="color" aria-label="批注颜色" @change="engine && (engine.color = color)" />
          </div>
          <div v-if="!narrow" class="layout-presets" role="group" aria-label="布局预设">
            <button @click="layout.applyPreset('reading')">阅读优先</button>
            <button @click="layout.applyPreset('discussion')">讨论优先</button>
            <button @click="layout.applyPreset('default')">默认</button>
          </div>
          <button v-if="!narrow" class="toggle-left" aria-label="收起或展开侧栏" @click="layout.toggle('left')">◧</button>
          <button v-if="!narrow" class="toggle-chat" aria-label="收起或展开会话" @click="layout.toggle('right')">◨</button>
          <button v-if="narrow" class="mobile-more" aria-label="更多操作" :aria-expanded="mobileToolsOpen" @click="mobileToolsOpen = !mobileToolsOpen">⋯</button>
        </div>
        <div class="pdf-document">
          <div ref="scrollEl" class="pdf-scroll">
            <div ref="pagesEl" class="pdf-pages"></div>
          </div>
          <div v-if="orch.loading.value || orch.loadError.value" class="pdf-error" role="status">
            <strong>{{ orch.loading.value ? '正在打开论文…' : '暂时无法打开全文' }}</strong><p>{{ orch.loadError.value }}</p>
            <button v-if="orch.missingPdf.value" class="primary" @click="emit('open-import', paperId)">补充 PDF 全文</button>
          </div>
          <div v-if="selected" class="selection-actions" :style="popupStyle" @pointerdown.prevent>
            <button data-selection="explain" @click="runAction('explain')">解释</button>
            <button data-selection="translate" @click="runAction('translate')">翻译</button>
            <button data-selection="highlight" @click="runAction('highlight')">高亮</button>
            <button data-selection="note" @click="runAction('note')">批注</button>
            <button data-selection="chat" @click="runAction('chat')">加入对话</button>
          </div>
        </div>
      </main>
      <div
        class="resizer" role="separator" aria-orientation="vertical" tabindex="0" aria-label="调整会话宽度"
        :aria-valuenow="layout.layout.value.right_width" aria-valuemin="140" aria-valuemax="600"
        @pointerdown="layout.startDrag('right', $event, $event.currentTarget as HTMLElement, layout.layout.value.right_width)"
        @keydown="layout.onResizerKey('right', $event)"
      ></div>
      <aside class="chat-pane">
        <ChatPanel ref="chatRef" :session="orch.session.value" :paper-id="paperId" :paper-title="orch.profile.value?.title" :orchestrator="orch"><template #session-controls><div class="session-controls">      <select class="reader-session" :value="orch.session.value?.id" aria-label="当前会话" @change="onSessionChange(Number(($event.target as HTMLSelectElement).value))">
        <option v-for="s in sessions" :key="s.id" :value="s.id">{{ s.title }}</option>
      </select>
      <button class="new-session" @click="dialogOpen = true">＋ 新会话</button>
</div></template></ChatPanel>
      </aside>
    </div>

    <div v-if="narrow && mobileToolsOpen" class="mobile-drawer" role="dialog" aria-label="更多阅读操作">
      <div class="drawer-row">
        <button @click="layout.applyPreset('reading'); mobileToolsOpen = false">阅读优先</button>
        <button @click="layout.applyPreset('discussion'); mobileToolsOpen = false">讨论优先</button>
        <button @click="layout.applyPreset('default'); mobileToolsOpen = false">恢复默认</button>
      </div>
      <div class="tools" role="group" aria-label="阅读工具">
        <button :aria-pressed="mode === 'select'" @click="setTool('select')">选择</button>
        <button :aria-pressed="mode === 'pen'" @click="setTool('pen')">画笔</button>
        <button :aria-pressed="mode === 'erase'" @click="setTool('erase')">橡皮</button>
        <input v-model="color" type="color" aria-label="批注颜色" @change="engine && (engine.color = color)" />
      </div>
      <div class="drawer-row">
        <button @click="layout.toggle('left'); mobileToolsOpen = false">目录面板</button>
        <button @click="layout.toggle('right'); mobileToolsOpen = false">会话面板</button>
        <button @click="mobileToolsOpen = false">完成</button>
      </div>
    </div>

    <div v-if="narrow" class="mobile-switch" role="group" aria-label="分区切换">
      <button :aria-pressed="layout.mobileMode.value === 'left'" @click="layout.setMobile('left')">目录</button>
      <button :aria-pressed="layout.mobileMode.value === 'pdf'" @click="layout.setMobile('pdf')">原文</button>
      <button :aria-pressed="layout.mobileMode.value === 'chat'" @click="layout.setMobile('chat')">会话</button>
    </div>

    <div v-if="dialogOpen" class="dialog-overlay" @click.self="dialogOpen = false">
      <TaskDialog mode="read" :paper-ids="[paperId]" @created="onCreated" @close="dialogOpen = false" />
    </div>
  </div>
</template>

<style scoped>
.reading-layout { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.reader-top { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--border); flex-wrap: wrap; min-height:50px; flex-shrink:0; }
.session-controls { display:flex; gap:6px; min-width:0; }
.reader-session { flex:1; min-width:0; max-width:100%; font-size:11px; padding:5px; }
.new-session { flex-shrink:0; font-size:11px; padding:5px 8px; }
.reader-top button,.reader-top select { padding:4px 7px; font-size:12px; }
.page-controls { flex-shrink:0; display: flex; align-items: center; gap: var(--space-1); }
.page-controls input { width: 64px; }
.tools { display: flex; gap: var(--space-1); align-items: center; }
.tools button[aria-pressed='true'] { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.tools input[type='color'] { width: 32px; height: 32px; padding: 2px; }
.reader-top { overflow:hidden; min-width:0; }
.layout-presets { display:flex; gap:4px; flex-shrink:0; }
.mobile-more { flex-shrink:0; }
.reader-body { display: flex; flex: 1; min-height: 0; min-width:0; overflow:hidden; }
.left-pane { width:min(var(--aux-width), 34%); min-width:140px; flex-shrink:0; overflow:hidden; border-right: 1px solid var(--border); background: var(--surface); }
.chat-pane { width:min(var(--chat-width), 52%); min-width:240px; flex-shrink:0; overflow:hidden; border-left: 1px solid var(--border); background: var(--surface); }
.hide-left .left-pane, .hide-left .resizer:first-of-type { display: none; }
.hide-chat .chat-pane, .hide-chat .resizer:last-of-type { display: none; }
.resizer { width: 6px; cursor: col-resize; touch-action:none; background:var(--surface); flex-shrink: 0; }
.resizer:hover, .resizer:focus { background: var(--accent); outline: none; }
.pdf-pane { flex: 1; min-width: 0; position: relative; display: flex; flex-direction: column; }
.pdf-document { flex:1; min-height:0; min-width:0; display:flex; flex-direction:column; position:relative; }
.pdf-scroll { flex: 1; min-height:0; overflow: auto; background: var(--canvas); padding:20px 16px; }
.pdf-pages { min-width:100%; width:max-content; display: flex; flex-direction: column; align-items: center; gap: var(--space-3); }
.pdf-error { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-3); background: var(--bg); }
.selection-actions { position: fixed; display: flex; gap: var(--space-1); padding: var(--space-1); background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); z-index: 30; }
.selection-actions button { padding: var(--space-1) var(--space-2); font-size: 12px; }
.mobile-drawer { position:absolute; top:0; right:0; z-index:40; width:min(320px,100%); max-height:calc(100% - 46px); overflow:auto; background:var(--bg); border:1px solid var(--border); box-shadow:var(--shadow); }
.drawer-row,.mobile-drawer .tools { display:flex; flex-wrap:wrap; gap:6px; padding:10px; }
.mobile-switch { display: flex; border-top: 1px solid var(--border); }
.mobile-switch button { flex: 1; border: none; border-radius: 0; }
.mobile-switch button[aria-pressed='true'] { color: var(--accent); background: var(--accent-soft); }
.dialog-overlay { position: fixed; inset: 0; background: rgb(0 0 0 / 0.25); display: flex; align-items: center; justify-content: center; z-index: 50; }
@media (max-width: 760px) {
  .reader-top { gap:5px; padding:6px; }
  .left-pane,.chat-pane { min-width:0; max-width:none; }
  .reader-body > .left-pane, .reader-body > .chat-pane, .reader-body > .pdf-pane, .resizer { display: none; }
  .reader-top { padding:4px; gap:4px; }
  .page-controls input { width:52px; }
  .reading-layout[data-mobile='left'] .left-pane { display: block; width: 100%; }
  .reading-layout[data-mobile='pdf'] .pdf-pane { display: flex; }
  .reading-layout[data-mobile='chat'] .chat-pane { display: block; width: 100%; }
}
</style>

<style>
/* PDF 页与批注覆盖层（引擎生成的 DOM，非 scoped） */
.pdf-page { position: relative; background: #fff; box-shadow: var(--shadow); }
.pdf-page .page-loading { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--text-muted); }
.pdf-page canvas { display: block; }
.pdf-page .textLayer { position: absolute; inset: 0; overflow: hidden; opacity: 0.25; line-height: 1; }
.pdf-page .textLayer ::selection { background: var(--accent); }
.pdf-page .annotation-overlay { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.pdf-page .annotation-overlay .highlight { opacity: 0.4; }
.pdf-page .annotation-overlay .ink { fill: none; stroke-width: 0.004; stroke-linecap: round; stroke-linejoin: round; }
.pdf-page.pen-mode { cursor: crosshair; }
.pdf-page.pen-mode .textLayer { pointer-events: none; }
.pdf-page.erase-mode .annotation-overlay { pointer-events: auto; cursor: pointer; }
.pdf-page.flash { outline: 3px solid var(--accent); outline-offset: 2px; }
</style>
