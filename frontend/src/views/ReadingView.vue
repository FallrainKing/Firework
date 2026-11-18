<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { attachBridge, requestSave, sendLayout } from '@/shared/bridge'
import { useWorkbenchStore } from '@/stores/workbench'
import type { WorkspaceState } from '@/api/types'

const props = defineProps<{ paperId: number | null; sessionId: number | null }>()
const emit = defineEmits<{ 'open-import': [paperId?: number]; 'save-timeout': [paperId: number] }>()
const wb = useWorkbenchStore()

const MAX_LOADED = 3

interface Loaded {
  paperId: number
  sessionId: number | null
  src: string
  lastUsed: number
}

const loaded = ref<Loaded[]>([])
const frameRefs = new Map<number, HTMLIFrameElement>()
let detach: (() => void) | null = null
let useCounter = 0
// 串行化 ensure：并发切换时避免重复驱逐/超额加载。
let chain: Promise<void> = Promise.resolve()

function srcFor(paperId: number, sessionId: number | null): string {
  return '/reader.html?paper_id=' + paperId + (sessionId ? '&session_id=' + sessionId : '')
}

function dropFrame(paperId: number) {
  loaded.value = loaded.value.filter(l => l.paperId !== paperId)
  frameRefs.delete(paperId)
}

async function ensure(paperId: number, sessionId: number | null) {
  const existing = loaded.value.find(l => l.paperId === paperId)
  if (existing) {
    existing.lastUsed = ++useCounter
    // 会话重绑定：保存旧帧草稿后以新会话重建（旧版行为）。
    if (sessionId !== null && existing.sessionId !== sessionId) {
      const frame = frameRefs.get(paperId)
      if (frame) {
        const ok = await requestSave(frame)
        if (!ok) emit('save-timeout', paperId)
      }
      dropFrame(paperId)
      loaded.value.push({ paperId, sessionId, src: srcFor(paperId, sessionId), lastUsed: ++useCounter })
    }
    return
  }
  while (loaded.value.length >= MAX_LOADED) {
    // 不驱逐当前活动帧；await 后重新挑选，避免竞态误删。
    const candidates = loaded.value.filter(l => l.paperId !== props.paperId)
    if (!candidates.length) break
    const victim = candidates.sort((a, b) => a.lastUsed - b.lastUsed)[0]
    const frame = frameRefs.get(victim.paperId)
    if (frame) {
      const ok = await requestSave(frame)
      if (!ok) emit('save-timeout', victim.paperId)
    }
    if (victim.paperId === props.paperId) break
    dropFrame(victim.paperId)
  }
  loaded.value.push({ paperId, sessionId, src: srcFor(paperId, sessionId), lastUsed: ++useCounter })
}

function scheduleEnsure(paperId: number | null, sessionId: number | null) {
  if (paperId === null) return
  chain = chain.then(() => ensure(paperId, sessionId)).catch(() => {})
}

watch(() => [props.paperId, props.sessionId] as const, ([pid, sid]) => scheduleEnsure(pid, sid), { immediate: true })

watch(() => wb.layout, layout => {
  for (const f of frameRefs.values()) sendLayout(f, layout)
}, { deep: true })

onMounted(() => {
  detach = attachBridge(() => [...frameRefs.values()], {
    onReady: (frame, pid, sid) => {
      sendLayout(frame, wb.layout)
      wb.setTabSession(pid, sid)
      const l = loaded.value.find(x => x.paperId === pid)
      if (l) l.sessionId = sid
    },
    onSession: (pid, sid) => {
      wb.setTabSession(pid, sid)
      const l = loaded.value.find(x => x.paperId === pid)
      if (l) l.sessionId = sid
    },
    onLayoutChange: layout => wb.setLayout(layout),
    onOpenPaper: (pid, sid) => wb.openPaper(pid, sid),
    onOpenImport: pid => emit('open-import', pid),
    onNavigate: view => wb.setView(view as WorkspaceState['view']),
  })
})

onBeforeUnmount(async () => {
  detach?.()
  // 真实卸载（离开阅读模块）前请求保存所有帧。
  for (const [pid, frame] of frameRefs) {
    const ok = await requestSave(frame)
    if (!ok) emit('save-timeout', pid)
  }
})

function setFrame(pid: number, el: unknown) {
  if (el) frameRefs.set(pid, el as HTMLIFrameElement)
  else frameRefs.delete(pid)
}
</script>

<template>
  <div v-show="paperId !== null" class="reading-frames">
    <iframe
      v-for="l in loaded"
      :key="l.paperId + ':' + (l.sessionId ?? 'new')"
      :ref="el => setFrame(l.paperId, el)"
      :src="l.src"
      v-show="l.paperId === paperId"
      class="reader-frame"
      :title="'论文阅读 ' + l.paperId"
    />
  </div>
</template>

<style scoped>
.reading-frames { flex: 1; min-height: 0; position: relative; }
.reader-frame { position: absolute; inset: 0; width: 100%; height: 100%; border: none; }
</style>
