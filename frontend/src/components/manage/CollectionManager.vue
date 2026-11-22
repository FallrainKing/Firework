<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { papersApi } from '@/api/papers'
import type { Collection } from '@/api/types'
const props = defineProps<{ collection: Collection | null; collections: Collection[]; trash: boolean }>()
const emit = defineEmits<{ close: []; changed: [] }>()
const name = ref(props.collection?.name ?? '')
const parent = ref(props.collection?.parent_id ? String(props.collection.parent_id) : '')
const busy = ref(false), error = ref(''), confirmDelete = ref(false)
const deleted = ref<Collection[]>([])
const priorFocus = document.activeElement as HTMLElement | null
const panel = ref<HTMLElement | null>(null)
const excluded = computed(() => {
  const ids = new Set<number>(props.collection ? [props.collection.id] : [])
  let changed = true
  while (changed) { changed = false; for (const c of props.collections) if (c.parent_id && ids.has(c.parent_id) && !ids.has(c.id)) { ids.add(c.id); changed = true } }
  return ids
})
const parents = computed(() => props.collections.filter(c => !c.managed && !excluded.value.has(c.id)))
async function loadTrash() { deleted.value = (await papersApi.collections(true)).collections.filter(c => c.restore_root) }
async function act(fn: () => Promise<void>) {
  busy.value = true; error.value = ''
  try { await fn() } catch (e) { error.value = e instanceof Error ? e.message : '分类操作失败，请刷新重试' }
  finally { busy.value = false }
}
async function save() { if (!props.collection) return; await act(async () => { await papersApi.editCollection(props.collection!.id, name.value.trim(), parent.value ? Number(parent.value) : null, props.collection!.revision!); emit('changed'); emit('close') }) }
async function remove() { if (!props.collection) return; await act(async () => { await papersApi.trashCollection(props.collection!.id, props.collection!.revision!); emit('changed'); emit('close') }) }
async function restore(c: Collection) { await act(async () => { await papersApi.restoreCollection(c.id, c.revision!); emit('changed'); await loadTrash() }) }
function close() { if (!busy.value) emit('close') }
function keys(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); close() }
  if (event.key !== 'Tab') return
  const items = Array.from(panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled),input,select') ?? [])
  const first = items[0], last = items.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
onMounted(() => { panel.value?.focus(); if (props.trash) void act(loadTrash) })
onUnmounted(() => priorFocus?.isConnected && priorFocus.focus())
</script>
<template>
  <Teleport to="body">
    <div class="collection-overlay" @click.self="close">
      <section ref="panel" tabindex="-1" class="collection-dialog" role="dialog" aria-modal="true" :aria-label="trash?'分类回收站':'管理分类'" @keydown="keys">
        <header><h2>{{ trash ? '分类回收站' : '管理分类' }}</h2><button aria-label="关闭分类管理" :disabled="busy" @click="close">×</button></header>
        <p v-if="error" role="alert" class="error">{{error}}</p>
        <template v-if="trash">
          <p>删除的分类及其原有归属可以整体恢复；论文、文件、批注和会话始终保留。</p>
          <p v-if="!deleted.length && !busy">分类回收站为空</p>
          <article v-for="c in deleted" :key="c.id"><span>{{ c.path || c.name }}</span><button :disabled="busy" @click="restore(c)">恢复分类</button></article>
          <button :disabled="busy" @click="act(loadTrash)">刷新</button>
        </template>
        <form v-else @submit.prevent="save">
          <p v-if="collection?.managed">Zotero 来源分类请在 Zotero 修改。</p>
          <label>分类名称<input v-model="name" aria-label="分类名称" maxlength="80" required :disabled="busy || collection?.managed" /></label>
          <label>移动到<select v-model="parent" aria-label="分类的目标父分类" :disabled="busy || collection?.managed"><option value="">顶层分类</option><option v-for="c in parents" :key="c.id" :value="String(c.id)">{{ c.path || c.name }}</option></select></label>
          <p>重命名或移动保留分类 ID 和论文归属，不改变历史研究证据。</p>
          <footer><button type="button" :disabled="busy" @click="close">取消</button><button class="primary" :disabled="busy || !name.trim() || collection?.managed">保存分类</button></footer>
          <div class="delete-category"><button type="button" :disabled="busy || collection?.managed" @click="confirmDelete=true">删除分类…</button><template v-if="confirmDelete"><p>将此分类及所有子分类移入分类回收站。不会删除论文或项目，也不传播 Zotero 删除；可从分类回收站恢复。</p><button type="button" :disabled="busy" @click="confirmDelete=false">保留分类</button><button class="danger" type="button" :disabled="busy" @click="remove">确认移入回收站</button></template></div>
        </form>
      </section>
    </div>
  </Teleport>
</template>
<style scoped>
.collection-overlay{position:fixed;inset:0;z-index:80;display:grid;place-items:center;padding:16px;background:rgb(0 0 0 / .3)}
.collection-dialog{width:min(480px,100%);max-height:85dvh;overflow:auto;box-sizing:border-box;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-panel,10px);padding:20px;box-shadow:var(--shadow)}
header,footer,article{display:flex;align-items:center;justify-content:space-between;gap:12px}h2{font-size:18px;margin:0}form,label{display:grid;gap:8px}form{margin-top:16px}input,select{min-width:0;width:100%;box-sizing:border-box}p{font-size:13px;color:var(--text-muted);line-height:1.7}footer{justify-content:flex-end}.delete-category{border-top:1px solid var(--border);padding-top:14px;margin-top:10px}.error,.danger{color:var(--danger)}article{padding:10px 0;border-bottom:1px solid var(--border)}article span{overflow-wrap:anywhere;min-width:0}
</style>
