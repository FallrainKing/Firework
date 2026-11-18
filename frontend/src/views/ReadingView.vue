<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { attachBridge, requestSave, sendLayout } from '@/shared/bridge'
import { useWorkbenchStore } from '@/stores/workbench'
import type { WorkspaceState } from '@/api/types'

const props = defineProps<{ paperId: number; sessionId: number | null }>()
const emit = defineEmits<{ 'open-import': [paperId?: number] }>()
const wb = useWorkbenchStore()

const MAX_LOADED = 3

interface Loaded {
  paperId: number
  src: string
  lastUsed: number
}

const loaded = ref<Loaded[]>([])
const frameRefs = new Map<number, HTMLIFrameElement>()
let detach: (() => void) | null = null
let useCounter = 0

function srcFor(paperId: number, sessionId: number | null): string {
  return '/reader.html?paper_id=' + paperId + (sessionId ? '&session_id=' + sessionId : '')
}

async function ensure(paperId: number, sessionId: number | null) {
  const existing = loaded.value.find(l => l.paperId === paperId)
  if (existing) {
    existing.lastUsed = ++useCounter
    return
  }
  while (loaded.value.length >= MAX_LOADED) {
    const victim = [...loaded.value].sort((a, b) => a.lastUsed - b.lastUsed)[0]
    const frame = frameRefs.get(victim.paperId)
    // 释放前请求保存草稿/位置；超时兜底放行（bridge 内 2s）。
    if (frame) await requestSave(frame)
    loaded.value = loaded.value.filter(l => l.paperId !== victim.paperId)
    frameRefs.delete(victim.paperId)
  }
  loaded.value.push({ paperId, src: srcFor(paperId, sessionId), lastUsed: ++useCounter })
}

watch(() => [props.paperId, props.sessionId] as const, ([pid, sid]) => { void ensure(pid, sid) }, { immediate: true })

watch(() => wb.layout, layout => {
  for (const f of frameRefs.values()) sendLayout(f, layout)
}, { deep: true })

onMounted(() => {
  detach = attachBridge(() => [...frameRefs.values()], {
    onReady: (frame, pid, sid) => {
      sendLayout(frame, wb.layout)
      wb.setTabSession(pid, sid)
    },
    onSession: (pid, sid) => wb.setTabSession(pid, sid),
    onLayoutChange: layout => wb.setLayout(layout),
    onOpenPaper: (pid, sid) => wb.openPaper(pid, sid),
    onOpenImport: pid => emit('open-import', pid),
    onNavigate: view => wb.setView(view as WorkspaceState['view']),
  })
})

onBeforeUnmount(() => detach?.())

function setFrame(pid: number, el: unknown) {
  if (el) frameRefs.set(pid, el as HTMLIFrameElement)
  else frameRefs.delete(pid)
}
</script>

<template>
  <div class="reading-frames">
    <iframe
      v-for="l in loaded"
      :key="l.paperId"
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
