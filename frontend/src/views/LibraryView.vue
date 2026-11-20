<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import LibraryGrid from './manage/LibraryGrid.vue'
import SessionsManager from './manage/SessionsManager.vue'
import { papersApi } from '@/api/papers'
import { frontierApi } from '@/api/frontier'
import type { Collection } from '@/api/types'

// 论文库管理容器：论文库 / 任务会话两页（替代旧 manage.html iframe）。
const props = withDefaults(defineProps<{ sessionId?: number | null }>(), { sessionId: null })
const emit = defineEmits<{ 'open-paper': [paperId: number, sessionId?: number]; 'open-import': [paperId?: number]; 'open-session': [sessionId: number] }>()

const page = ref<'library' | 'sessions' | 'projects'>(props.sessionId ? 'sessions' : 'library')
const collections = ref<Collection[]>([])
const category = ref('')
const reading = ref<'' | 'unread' | 'reading' | 'read'>('')
const projects = ref<Array<Record<string, any>>>([])
const projectError = ref('')
const categoryName = ref('')
async function loadCollections() { try { collections.value = (await papersApi.collections()).collections } catch (e) { projectError.value = e instanceof Error ? e.message : '分类载入失败' } }
async function loadProjects() { try { projects.value = (await frontierApi.projects(category.value ? Number(category.value) : undefined)).projects; projectError.value = '' } catch(e) { projectError.value = e instanceof Error ? e.message : '项目载入失败' } }
async function addCategory() { if (!categoryName.value.trim()) return; try { const c = await papersApi.createCollection(categoryName.value); await loadCollections(); category.value = String(c.id); categoryName.value = '' } catch(e) { projectError.value = e instanceof Error ? e.message : '分类保存失败' } }
watch([category, page], () => { if(page.value === 'projects') void loadProjects() })
onMounted(() => { void loadCollections() })
const openSessionId = ref<number | null>(props.sessionId)
watch(() => props.sessionId, sid => { if (sid) { page.value = 'sessions'; openSessionId.value = sid } })

function onOpenSession(sid: number) {
  openSessionId.value = sid
  page.value = 'sessions'
  emit('open-session', sid)
}
</script>

<template>
  <div class="manage-view">
    <aside class="library-nav" aria-label="资料库导航">
      <button class="primary" @click="emit('open-import')">＋ 添加论文</button>
      <button :class="{active:page==='library'&&category===''}" @click="page='library'; category='';reading=''">全部论文</button>
      <button :class="{active:page==='projects'}" @click="page='projects'">开源项目</button>
      <h2>领域分类</h2>
      <button v-for="c in collections" :key="c.id" :class="{active:category===String(c.id)}" @click="category=String(c.id); if(page==='sessions')page='library'">{{c.path ?? c.name}} <small>{{c.count??0}} 篇论文</small></button>
      <form class="category-create" @submit.prevent="addCategory"><input v-model="categoryName" maxlength="80" placeholder="新增分类" aria-label="新增资料分类"><button :disabled="!categoryName.trim()">＋</button></form>
      <h2>阅读状态</h2>
      <button v-for="s in [{id:'unread',name:'未开始阅读'},{id:'reading',name:'阅读中'},{id:'read',name:'已完成阅读'}] as const" :key="s.id" :class="{active:reading===s.id&&page==='library'}" @click="page='library';reading=s.id">{{s.name}}</button>
      <button @click="category='';reading=''">清除筛选</button>
    </aside>
    <section class="manage-area">
    <div class="manage-nav">
      <button :aria-current="page === 'library' ? 'page' : undefined" @click="page = 'library'">论文库</button>
      <button :aria-current="page === 'sessions' ? 'page' : undefined" @click="page = 'sessions'">任务会话</button>
      <button :aria-current="page === 'projects' ? 'page' : undefined" @click="page = 'projects'">开源项目</button>
    </div>
    <div class="manage-content">
    <LibraryGrid v-if="page === 'library'" :filter-collection="category" :filter-status="reading" @filter-change="(c, s) => { category = c; reading = s }" @open-paper="pid => emit('open-paper', pid)" @open-import="pid => emit('open-import', pid)" @open-session="onOpenSession" />
    <SessionsManager v-else-if="page === 'sessions'" :initial-session-id="openSessionId" @open-paper="(pid, sid) => emit('open-paper', pid, sid)" @open-import="emit('open-import')" />
    <section v-else class="projects-view"><h1>开源项目</h1><p class="muted">前沿追踪中经批准保存的项目。项目资料不代表已审查代码。</p><p v-if="projectError" role="alert">{{projectError}}</p><button @click="loadProjects()">刷新</button><p v-if="!projects.length">该范围暂无项目，可在前沿追踪中发现并批准入库。</p><article v-for="p in projects" :key="p.id" class="project-card"><h2>{{p.title}}</h2><p>{{p.description}}</p><p class="muted">{{p.owner}}<template v-if="p.metadata.release"> · 最新版本 {{p.metadata.release.tag}}</template> · 许可证 {{p.license??'未提供'}} · 最近活动 {{p.metadata.activity_at??'未提供'}}</p><a :href="p.url" target="_blank" rel="noopener noreferrer">打开原始仓库 ↗</a></article></section>
    </div>
    <p v-if="projectError && page !== 'projects'" class="library-error" role="alert">{{projectError}}</p>
    </section>
  </div>
</template>

<style scoped>
.manage-view { display: flex; height: 100%; min-height: 0; min-width: 0; overflow: hidden; }
.manage-nav { flex: 0 0 auto; display: flex; gap: var(--space-1); padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border); }
.manage-nav button[aria-current='page'] { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.manage-content { flex: 1; min-height: 0; min-width: 0; overflow: hidden; }
</style>

<style scoped>
.manage-area{flex:1;min-width:0;min-height:0;display:flex;flex-direction:column}.library-nav{width:225px;flex-shrink:0;padding:16px;display:flex;flex-direction:column;gap:7px;border-right:1px solid var(--border);overflow:auto}.library-nav h2{font-size:11px;color:var(--text-muted);margin:18px 0 3px}.library-nav button{text-align:left;overflow-wrap:anywhere}.library-nav small{font-size:10px;color:var(--text-muted)}.library-nav .active{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}.category-create{display:flex;gap:4px}.category-create input{min-width:0;width:100%}.projects-view{height:100%;overflow:auto;padding:24px;box-sizing:border-box}.project-card{padding:18px;border:1px solid var(--border);background:var(--surface);border-radius:8px;margin:14px 0;overflow-wrap:anywhere}.project-card h2{font-size:16px}.project-card a{color:var(--accent)}.library-error{color:var(--danger);padding:8px 16px}@media(max-width:760px){.library-nav{width:155px;padding:10px}}@media(max-width:500px){.manage-view{flex-direction:column}.library-nav{width:auto;max-height:150px;flex-direction:row;flex-wrap:wrap;border-right:0;border-bottom:1px solid var(--border)}.library-nav h2,.category-create{display:none}.library-nav button{font-size:11px}.library-nav small{display:none}}
</style>
