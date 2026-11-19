<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { papersApi } from '@/api/papers'
import type { Collection, Paper } from '@/api/types'
import PaperEditDialog from '@/components/manage/PaperEditDialog.vue'
import StateFeedback from '@/components/StateFeedback.vue'
import TaskDialog from '@/components/TaskDialog.vue'
import type { Session } from '@/api/types'

const emit = defineEmits<{ 'open-paper': [paperId: number]; 'open-import': [paperId?: number]; 'open-session': [sessionId: number] }>()

const papers = ref<Paper[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const loadError = ref<string | null>(null)
const saveError = ref<string | null>(null)
const savedMessage = ref(false)
const collections = ref<Collection[]>([])
const total = ref(0)
const offset = ref(0)
const hasMore = ref(false)
const query = ref('')
const collectionId = ref('')
const selected = ref<Set<number>>(new Set())
const density = ref<'card' | 'compact'>(localStorage.getItem('library-density') === 'compact' ? 'compact' : 'card')
const readingStatus = ref<'' | 'unread' | 'reading' | 'read'>('')
const failedThumbnails = ref<Set<number>>(new Set())
const openMenuId = ref<number | null>(null)
const batchCollectionOpen = ref(false)
const batchCollectionId = ref('')
const batchSaving = ref(false)
const savingCollection = ref(false)
const editId = ref<number | null>(null)
const task = ref<{ mode: 'compare' | 'review'; paperIds: number[] } | null>(null)
const newCollectionOpen = ref(false)
const newCollectionName = ref('')

async function load(reset: boolean) {
  const busy = reset ? loading : loadingMore
  if (busy.value) return
  busy.value = true
  const requestOffset = reset ? 0 : offset.value
  const params: { q?: string; collection_id?: number; reading_status?: 'unread' | 'reading' | 'read'; limit: number; offset: number } = { limit: 30, offset: requestOffset }
  if (query.value) params.q = query.value
  if (collectionId.value !== '') params.collection_id = Number(collectionId.value)
  if (readingStatus.value) params.reading_status = readingStatus.value
  try {
    const d = await papersApi.list(params)
    papers.value = reset ? d.papers : [...papers.value, ...d.papers]
    offset.value = requestOffset + d.papers.length
    total.value = d.total
    hasMore.value = d.has_more
    if (reset) loadError.value = null
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '论文列表载入失败'
  } finally {
    busy.value = false
  }
}

function reload() {
  void load(true)
  void refreshCollections()
}

async function refreshCollections() {
  try {
    collections.value = (await papersApi.collections()).collections
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '论文分类载入失败'
  }
}

onMounted(() => {
  reload()
})

function toggleSelect(id: number, on: boolean) {
  if (on) selected.value.add(id)
  else selected.value.delete(id)
  selected.value = new Set(selected.value)
}

function setDensity(value: 'card' | 'compact') {
  density.value = value
  localStorage.setItem('library-density', value)
}

function markThumbnailFailed(paperId: number) {
  failedThumbnails.value = new Set([...failedThumbnails.value, paperId])
}

function closeMenus() {
  openMenuId.value = null
}

async function applyBatchCollection() {
  if (!selected.value.size || !batchCollectionId.value || batchSaving.value) return
  batchSaving.value = true
  saveError.value = null
  savedMessage.value = false
  const collectionIds = batchCollectionId.value === '0' ? [] : [Number(batchCollectionId.value)]
  try {
    for (const id of selected.value) {
      const current = await papersApi.get(id)
      await papersApi.patch(id, { metadata_version: current.metadata_version, collection_ids: collectionIds })
    }
    selected.value = new Set()
    batchCollectionOpen.value = false
    batchCollectionId.value = ''
    await Promise.all([load(true), refreshCollections()])
    savedMessage.value = true
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : '批量分类失败'
  } finally {
    batchSaving.value = false
  }
}

async function createCollection() {
  const name = newCollectionName.value.trim()
  if (!name) return
  savingCollection.value = true
  saveError.value = null
  savedMessage.value = false
  try {
    await papersApi.createCollection(name)
    newCollectionOpen.value = false
    newCollectionName.value = ''
    await refreshCollections()
    savedMessage.value = true
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : '新增分类失败'
  } finally {
    savingCollection.value = false
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
      <form @submit.prevent="reload()">
        <input v-model="query" type="search" placeholder="搜索标题 / 摘要 / 作者…" aria-label="搜索论文" />
        <button type="submit">搜索</button>
      </form>
      <select v-model="collectionId" class="collection-filter" aria-label="按分类筛选" @change="reload()">
        <option value="">全部论文</option>
        <option value="0">未分类</option>
        <option v-for="c in collections" :key="c.id" :value="String(c.id)">{{ c.name }}</option>
      </select>
      <select v-model="readingStatus" class="reading-filter" aria-label="按阅读状态筛选" @change="reload()">
        <option value="">全部阅读状态</option>
        <option value="unread">未开始阅读</option>
        <option value="reading">阅读中</option>
        <option value="read">已完成阅读任务</option>
      </select>
      <div class="density-toggle" role="group" aria-label="列表密度">
        <button :aria-pressed="density === 'card'" @click="setDensity('card')">卡片</button>
        <button :aria-pressed="density === 'compact'" @click="setDensity('compact')">紧凑列表</button>
      </div>
      <button @click="newCollectionOpen = true">＋ 新分类</button>
      <span class="muted">共 {{ total }} 篇论文</span>
      <span class="spacer"></span>
      <button class="primary" @click="emit('open-import')">添加论文</button>
    </div>
    <div v-if="selected.size" class="batch-bar" role="toolbar" aria-label="批量操作">
      <strong>已选择 {{ selected.size }} 篇</strong>
      <button class="compare-selected" :disabled="selected.size < 2" @click="task = { mode: 'compare', paperIds: [...selected] }">对比所选</button>
      <button @click="batchCollectionOpen = true">分类所选</button>
      <button @click="selected = new Set()">清空选择</button>
    </div>
    <StateFeedback
      :loading="loading && !papers.length"
      :error="loadError"
      :empty="!loading && !loadError && !papers.length"
      empty-text="没有匹配论文。可调整筛选或添加论文。"
      :saving="batchSaving || savingCollection"
      :saved="savedMessage"
      :save-error="saveError"
      @retry="reload"
    />

    <div class="paper-grid" :class="{ compact: density === 'compact' }">
      <article v-for="p in papers" :key="p.id" class="paper-card">
        <div class="paper-visual">
          <img v-if="p.thumbnail_url && !failedThumbnails.has(p.id)" :src="p.thumbnail_url" :alt="p.title + ' 的原始 PDF 首页预览'" loading="lazy" @error="markThumbnailFailed(p.id)" />
          <span v-else class="image-placeholder muted">仅书目信息 · 待添加全文</span>
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
            <span class="badge" :class="{ danger: !p.has_pdf }">{{ p.has_pdf ? '有全文' : '缺全文' }}</span>
            <span class="badge">{{ { unread: '未开始阅读', reading: '阅读中', read: '已完成阅读任务' }[p.reading_status] }}</span>
            <span v-for="c in p.collections" :key="c.id" class="badge">{{ c.name }}</span>
            <span v-if="!p.collections.length" class="badge">未分类</span>
          </div>
          <div class="paper-actions">
            <button v-if="p.has_pdf" class="primary read-paper" @click="emit('open-paper', p.id)">打开原文</button>
            <button v-else class="primary supplement-pdf" @click="emit('open-import', p.id)">补充全文</button>
            <div class="card-more">
              <button class="more-actions" :aria-expanded="openMenuId === p.id" aria-haspopup="true" @click.stop="openMenuId = openMenuId === p.id ? null : p.id">更多</button>
              <div v-if="openMenuId === p.id" class="card-menu" role="menu" :aria-label="'论文操作 ' + p.title">
                <button class="edit-paper" role="menuitem" @click="closeMenus(); editId = p.id">完整信息 / 管理信息</button>
                <button role="menuitem" @click="closeMenus(); task = { mode: 'review', paperIds: [p.id] }">审查</button>
                <button v-if="!p.has_pdf" class="supplement-pdf" role="menuitem" @click="closeMenus(); emit('open-import', p.id)">补充 PDF</button>
              </div>
            </div>
          </div>
        </div>
      </article>
    </div>
    <button v-if="hasMore" class="more-papers" :disabled="loadingMore" @click="load(false)">{{ loadingMore ? '正在载入…' : '加载更多' }}</button>

    <div v-if="editId !== null" class="dialog-overlay" @click.self="editId = null">
      <PaperEditDialog :paper-id="editId" @close="editId = null" @saved="onSaved" />
    </div>
    <div v-if="task" class="dialog-overlay" @click.self="task = null">
      <TaskDialog :mode="task.mode" :paper-ids="task.paperIds" @created="onCreated" @close="task = null" @open-import="emit('open-import')" />
    </div>
    <div v-if="batchCollectionOpen" class="dialog-overlay" @click.self="batchCollectionOpen = false">
      <div class="name-dialog" role="dialog" aria-label="批量设置分类">
        <h2>批量设置分类</h2>
        <select v-model="batchCollectionId" aria-label="目标分类">
          <option value="" disabled>请选择分类</option>
          <option value="0">未分类</option>
          <option v-for="c in collections" :key="c.id" :value="String(c.id)">{{ c.name }}</option>
        </select>
        <div class="dialog-footer">
          <button @click="batchCollectionOpen = false">取消</button>
          <button class="primary" :disabled="!batchCollectionId || batchSaving" @click="applyBatchCollection">{{ batchSaving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

    <div v-if="newCollectionOpen" class="dialog-overlay" @click.self="newCollectionOpen = false">
      <div class="name-dialog" role="dialog" aria-label="新建论文分类">
        <h2>新建论文分类</h2>
        <input v-model="newCollectionName" maxlength="80" placeholder="分类名称" @keydown.enter="createCollection" />
        <div class="dialog-footer">
          <button @click="newCollectionOpen = false">取消</button>
          <button class="primary" :disabled="savingCollection || !newCollectionName.trim()" @click="createCollection">{{ savingCollection ? '保存中…' : '保存' }}</button>
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
.paper-grid.compact { grid-template-columns: 1fr; }
.paper-grid.compact .paper-card { display:grid; grid-template-columns:84px minmax(0,1fr); }
.paper-grid.compact .paper-visual { height:84px; }
.paper-grid.compact .image-caption { display:none; }
.paper-grid.compact .paper-summary { display:none; }
.paper-grid.compact .paper-checkbox { position:absolute; top:4px; left:4px; }
.paper-card { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); overflow: hidden; display: flex; flex-direction: column; }
.paper-visual { position: relative; min-width:0; background: var(--bg); height: 180px; flex: 0 0 180px; display: flex; align-items: center; justify-content: center; border-bottom: 1px solid var(--border); }
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
.more-state { margin-top: var(--space-2); }
.empty { grid-column: 1 / -1; }
.dialog-overlay { position: fixed; inset: 0; background: rgb(0 0 0 / 0.25); display: flex; align-items: center; justify-content: center; z-index: 50; }
.name-dialog { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-4); background: var(--bg); border-radius: var(--radius); width: min(400px, 92vw); }
.name-dialog h2 { margin: 0; font-size: 16px; }
.dialog-footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
.library-grid-view { min-width:0; }
.library-toolbar form { flex:1 1 250px; min-width:0; }
.library-toolbar form input { flex:1; width:100%; min-width:0; }
.library-toolbar select { max-width:100%; }
.paper-title,.paper-authors,.paper-units { display:-webkit-box; -webkit-box-orient:vertical; overflow:hidden; }
.paper-title { -webkit-line-clamp:3; }
.paper-authors,.paper-units { -webkit-line-clamp:2; }
.badges { margin-top:auto; padding-top:8px; }
.batch-bar { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:-6px 0 var(--space-3); padding:8px 10px; border:1px solid var(--accent); border-radius:var(--radius); background:var(--accent-soft); }
.density-toggle { display:flex; gap:0; }
.density-toggle button[aria-pressed='true'] { color:var(--accent); background:var(--accent-soft); }
.card-more { position:relative; margin-left:auto; }
.card-menu { position:absolute; right:0; top:100%; z-index:20; min-width:170px; padding:4px; border:1px solid var(--border); border-radius:var(--radius); background:var(--bg); box-shadow:var(--shadow); }
.card-menu button { display:block; width:100%; padding:7px 8px; text-align:left; }
.badge.danger { border-color:var(--danger); color:var(--danger); }
.image-placeholder { display:grid; place-items:center; height:100%; text-align:center; }
@media(max-width:600px) { .paper-grid.compact .paper-card { grid-template-columns:1fr; }.card-menu { right:4px; }.library-grid-view { padding:12px; } .library-toolbar form { flex-basis:100%; } .library-toolbar button,.library-toolbar select { font-size:12px; padding:7px 10px; } .spacer { display:none; } }
</style>
