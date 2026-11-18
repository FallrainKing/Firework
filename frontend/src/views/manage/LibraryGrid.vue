<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { papersApi } from '@/api/papers'
import type { Collection, Paper } from '@/api/types'
import PaperEditDialog from '@/components/manage/PaperEditDialog.vue'
import TaskDialog from '@/components/TaskDialog.vue'
import type { Session } from '@/api/types'

const emit = defineEmits<{ 'open-paper': [paperId: number]; 'open-import': [paperId?: number]; 'open-session': [sessionId: number] }>()

const papers = ref<Paper[]>([])
const collections = ref<Collection[]>([])
const total = ref(0)
const offset = ref(0)
const hasMore = ref(false)
const query = ref('')
const collectionId = ref('')
const selected = ref<Set<number>>(new Set())
const editId = ref<number | null>(null)
const task = ref<{ mode: 'compare' | 'review'; paperIds: number[] } | null>(null)
const newCollectionOpen = ref(false)
const newCollectionName = ref('')
const error = ref('')

async function load(reset: boolean) {
  if (reset) { offset.value = 0; papers.value = [] }
  const params: { q?: string; collection_id?: number; limit: number; offset: number } = { limit: 30, offset: offset.value }
  if (query.value) params.q = query.value
  if (collectionId.value !== '') params.collection_id = Number(collectionId.value)
  const d = await papersApi.list(params)
  papers.value = reset ? d.papers : [...papers.value, ...d.papers]
  offset.value += d.papers.length
  total.value = d.total
  hasMore.value = d.has_more
}

async function refreshCollections() {
  collections.value = (await papersApi.collections()).collections
}

onMounted(async () => {
  await Promise.all([load(true), refreshCollections()])
})

function toggleSelect(id: number, on: boolean) {
  if (on) selected.value.add(id)
  else selected.value.delete(id)
  selected.value = new Set(selected.value)
}

async function createCollection() {
  const name = newCollectionName.value.trim()
  if (!name) return
  try {
    await papersApi.createCollection(name)
    newCollectionOpen.value = false
    newCollectionName.value = ''
    await refreshCollections()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '新增分类失败'
  }
}

function onCreated(session: Session, _prompt: string) {
  task.value = null
  // 对照旧版 createTask：创建后打开会话（起步要求保存在会话草稿中，可继续发送）。
  emit('open-session', session.id)
}

function onSaved() {
  void load(true)
  void refreshCollections()
}
</script>

<template>
  <div class="library-grid-view">
    <div class="library-toolbar">
      <form @submit.prevent="load(true)">
        <input v-model="query" type="search" placeholder="搜索标题 / 摘要 / 作者…" aria-label="搜索论文" />
        <button type="submit">搜索</button>
      </form>
      <select v-model="collectionId" class="collection-filter" aria-label="按分类筛选" @change="load(true)">
        <option value="">全部论文</option>
        <option value="0">未分类</option>
        <option v-for="c in collections" :key="c.id" :value="String(c.id)">{{ c.name }}</option>
      </select>
      <button @click="newCollectionOpen = true">＋ 新分类</button>
      <span class="muted">共 {{ total }} 篇论文</span>
      <span class="spacer"></span>
      <span class="muted">{{ selected.size ? `已选择 ${selected.size} 篇` : '未选择论文' }}</span>
      <button class="compare-selected" :disabled="selected.size < 2" @click="task = { mode: 'compare', paperIds: [...selected] }">对比所选</button>
      <button :disabled="!selected.size" @click="selected = new Set()">清空选择</button>
      <button class="primary" @click="emit('open-import')">添加论文</button>
    </div>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>

    <div class="paper-grid">
      <article v-for="p in papers" :key="p.id" class="paper-card">
        <div class="paper-visual">
          <img v-if="p.thumbnail_url" :src="p.thumbnail_url" :alt="p.title + ' 的原始 PDF 首页预览'" loading="lazy" />
          <span v-else class="muted">仅书目信息 · 待添加全文</span>
          <span class="image-caption muted">{{ p.image_caption }}</span>
          <label class="paper-checkbox">
            <input class="paper-select" type="checkbox" :checked="selected.has(p.id)" :aria-label="'选择 ' + p.title" @change="toggleSelect(p.id, ($event.target as HTMLInputElement).checked)" />
            <span>选择</span>
          </label>
        </div>
        <div class="paper-content">
          <h2 class="paper-title" :title="p.title">{{ p.title }}</h2>
          <p class="paper-authors" :title="p.authors.join(' · ')">{{ p.authors.length ? p.authors.join(' · ') : '作者待补全' }}</p>
          <p class="paper-units" :title="p.affiliations.join(' · ')">{{ p.affiliations.length ? p.affiliations.join(' · ') : '作者单位待补全' }}</p>
          <p class="paper-summary muted">{{ p.summary || '摘要待补全' }}</p>
          <div class="badges">
            <span v-for="c in p.collections" :key="c.id" class="badge">{{ c.name }}</span>
            <span v-if="!p.collections.length" class="badge">未分类</span>
          </div>
          <div class="paper-actions">
            <button class="primary read-paper" @click="emit('open-paper', p.id)">阅读</button>
            <button @click="task = { mode: 'review', paperIds: [p.id] }">审查</button>
            <button class="edit-paper" @click="editId = p.id">管理信息</button>
            <button v-if="!p.has_pdf" class="supplement-pdf" @click="emit('open-import', p.id)">补充 PDF</button>
          </div>
        </div>
      </article>
      <p v-if="!papers.length" class="muted empty">没有匹配论文。可调整筛选或添加论文。</p>
    </div>
    <button v-if="hasMore" class="more-papers" @click="load(false)">加载更多</button>

    <div v-if="editId !== null" class="dialog-overlay" @click.self="editId = null">
      <PaperEditDialog :paper-id="editId" @close="editId = null" @saved="onSaved" />
    </div>
    <div v-if="task" class="dialog-overlay" @click.self="task = null">
      <TaskDialog :mode="task.mode" :paper-ids="task.paperIds" @created="onCreated" @close="task = null" @open-import="emit('open-import')" />
    </div>
    <div v-if="newCollectionOpen" class="dialog-overlay" @click.self="newCollectionOpen = false">
      <div class="name-dialog" role="dialog" aria-label="新建论文分类">
        <h2>新建论文分类</h2>
        <input v-model="newCollectionName" maxlength="80" placeholder="分类名称" @keydown.enter="createCollection" />
        <div class="dialog-footer">
          <button @click="newCollectionOpen = false">取消</button>
          <button class="primary" :disabled="!newCollectionName.trim()" @click="createCollection">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.library-grid-view { padding: var(--space-4); overflow-y: auto; height: 100%; }
.library-toolbar { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; margin-bottom: var(--space-3); }
.library-toolbar form { display: flex; gap: var(--space-1); }
.spacer { flex: 1; }
.paper-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr)); gap: var(--space-3); }
.paper-card { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); overflow: hidden; display: flex; flex-direction: column; }
.paper-visual { position: relative; background: var(--bg); height: 180px; flex: 0 0 180px; display: flex; align-items: center; justify-content: center; border-bottom: 1px solid var(--border); }
.paper-visual img { width: 100%; height: 100%; object-fit: contain; }
.image-caption { max-width:calc(100% - 16px); background:var(--bg); padding:0 4px; border-radius:4px; position: absolute; bottom: var(--space-1); left: var(--space-2); font-size: 11px; }
.paper-checkbox { position: absolute; top: var(--space-1); right: var(--space-2); display: flex; gap: var(--space-1); align-items: center; font-size: 12px; background: var(--bg); padding: 2px var(--space-1); border-radius: var(--radius); }
.paper-content { flex: 1; min-width: 0; overflow-wrap: anywhere; padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-1); }
.paper-title { font-size: 15px; margin: 0; }
.paper-authors, .paper-units { font-size: 12px; margin: 0; color: var(--text-muted); }
.paper-summary { font-size: 12px; margin: 0; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.badges { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.badge { font-size: 11px; background: var(--accent-soft); color: var(--accent); padding: 1px var(--space-2); border-radius: 10px; }
.paper-actions { display: flex; gap: var(--space-1); flex-wrap: wrap; margin-top: var(--space-2); }
.paper-actions button { padding: var(--space-1) var(--space-2); font-size: 12px; }
.more-papers { margin-top: var(--space-3); width: 100%; }
.empty { grid-column: 1 / -1; }
.dialog-overlay { position: fixed; inset: 0; background: rgb(0 0 0 / 0.25); display: flex; align-items: center; justify-content: center; z-index: 50; }
.name-dialog { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-4); background: var(--bg); border-radius: var(--radius); width: min(400px, 92vw); }
.name-dialog h2 { margin: 0; font-size: 16px; }
.dialog-footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
.form-error { color: var(--danger); }
.library-grid-view { min-width:0; }
.library-toolbar form { flex:1 1 250px; min-width:0; }
.library-toolbar form input { flex:1; width:100%; min-width:0; }
.library-toolbar select { max-width:100%; }
.paper-title,.paper-authors,.paper-units { display:-webkit-box; -webkit-box-orient:vertical; overflow:hidden; }
.paper-title { -webkit-line-clamp:3; }
.paper-authors,.paper-units { -webkit-line-clamp:2; }
.badges { margin-top:auto; padding-top:8px; }
@media(max-width:600px) { .library-grid-view { padding:12px; } .library-toolbar form { flex-basis:100%; } .library-toolbar button,.library-toolbar select { font-size:12px; padding:7px 10px; } .spacer { display:none; } }
</style>
