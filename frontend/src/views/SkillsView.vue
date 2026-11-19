<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { skillsApi, type Skill, type SkillCategory, type SkillImport, type SkillVersionHistoryItem } from '@/api/skills'

const skills = ref<Skill[]>([])
const categories = ref<SkillCategory[]>([])
const loading = ref(false)
const error = ref('')
const query = ref('')
const statusFilter = ref('')
const sourceFilter = ref('')
const categoryFilter = ref<number | null>(null)
const busyId = ref<string | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const importResult = ref<SkillImport | null>(null)
const installName = ref('')
const installDescription = ref('')
const installCategory = ref('')
const installBudget = ref('short')
const installError = ref('')
const expandedSkillId = ref<string | null>(null)
const historyLoadingId = ref<string | null>(null)
const versionHistories = ref<Record<string, SkillVersionHistoryItem[]>>({})
const versionBusyKey = ref<string | null>(null)

const filteredSkills = computed(() => skills.value.filter(skill => {
  if (sourceFilter.value && skill.source !== sourceFilter.value) return false
  if (statusFilter.value && skill.status !== statusFilter.value) return false
  if (categoryFilter.value !== null && !skill.categories.some(category => category.id === categoryFilter.value)) return false
  const terms = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const haystack = `${skill.name} ${skill.description} ${skill.id}`.toLowerCase()
  return terms.every(term => haystack.includes(term))
}))

onMounted(refresh)

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [skillData, categoryData] = await Promise.all([skillsApi.list(), skillsApi.categories()])
    skills.value = skillData.skills
    categories.value = categoryData.categories
  } catch (e) {
    error.value = e instanceof Error ? e.message : '技能库载入失败'
  } finally {
    loading.value = false
  }
}

async function upload() {
  const file = fileInput.value?.files?.[0]
  if (!file) return
  uploading.value = true
  importResult.value = null
  installError.value = ''
  try {
    const result = await skillsApi.upload(file)
    importResult.value = result
    installName.value = result.manifest?.name || file.name.replace(/\.zip$/i, '')
    installDescription.value = result.manifest?.description || ''
    await refresh()
  } catch (e) {
    installError.value = e instanceof Error ? e.message : '技能包检查失败'
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function install() {
  if (!importResult.value || !installName.value.trim()) return
  installing.value = true
  installError.value = ''
  try {
    await skillsApi.install(importResult.value.import_id, {
      name: installName.value.trim(),
      description: installDescription.value.trim(),
      category_names: installCategory.value ? [installCategory.value] : [],
      budget_profile: installBudget.value,
    })
    importResult.value = null
    installCategory.value = ''
    await refresh()
  } catch (e) {
    installError.value = e instanceof Error ? e.message : '技能安装失败'
  } finally {
    installing.value = false
  }
}

const installing = ref(false)

async function setStatus(skill: Skill, enabled: boolean) {
  busyId.value = skill.id
  error.value = ''
  try {
    await (enabled ? skillsApi.enable(skill.id) : skillsApi.disable(skill.id))
    await refresh()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '技能状态更新失败'
  } finally {
    busyId.value = null
  }
}

async function toggleVersions(skill: Skill) {
  if (expandedSkillId.value === skill.id) {
    expandedSkillId.value = null
    return
  }
  expandedSkillId.value = skill.id
  if (versionHistories.value[skill.id]?.length) return

  historyLoadingId.value = skill.id
  error.value = ''
  try {
    const data = await skillsApi.versionHistory(skill.id)
    versionHistories.value = { ...versionHistories.value, [skill.id]: data.versions }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '技能版本历史载入失败'
    expandedSkillId.value = null
  } finally {
    historyLoadingId.value = null
  }
}

async function rollbackVersion(skill: Skill, version: SkillVersionHistoryItem) {
  versionBusyKey.value = `${skill.id}:${version.id}`
  error.value = ''
  try {
    await skillsApi.setDefaultVersion(skill.id, version.id, skill.revision)
    versionHistories.value = { ...versionHistories.value, [skill.id]: versionHistories.value[skill.id]?.map(item => ({
      ...item,
      is_default: item.id === version.id,
    })) ?? [] }
    await refresh()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '默认版本更新失败'
  } finally {
    versionBusyKey.value = null
  }
}

function formatVersionTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

watch(categoryFilter, () => undefined)
</script>

<template>
  <section class="skills-workspace">
    <div class="module-heading">
      <div>
        <p class="eyebrow">DYNAMIC SKILLS</p>
        <h1>技能库</h1>
        <p class="muted">上传 ZIP 技能包，先检查再安装；新技能默认停用，启用后无需重启即可被新任务发现。</p>
      </div>
      <div class="heading-actions">
        <input ref="fileInput" data-testid="skill-file" type="file" accept=".zip,application/zip" @change="upload">
        <button class="primary" type="button" :disabled="uploading" @click="fileInput?.click()">{{ uploading ? '检查中…' : '＋ 上传技能包' }}</button>
      </div>
    </div>

    <div class="skills-toolbar" role="search">
      <input v-model="query" data-testid="skill-search" type="search" placeholder="搜索技能名称、描述或 ID" aria-label="搜索技能">
      <select v-model="statusFilter" aria-label="按状态筛选">
        <option value="">全部状态</option>
        <option value="enabled">已启用</option>
        <option value="disabled">已停用</option>
      </select>
      <select v-model="sourceFilter" aria-label="按来源筛选">
        <option value="">全部来源</option>
        <option value="builtin">内置</option>
        <option value="zip">自定义</option>
      </select>
      <select v-model="categoryFilter" aria-label="按分类筛选">
        <option :value="null">全部分类</option>
        <option v-for="category in categories" :key="category.id" :value="category.id">{{ category.name }}</option>
      </select>
    </div>

    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-if="installError" class="form-error" role="alert">{{ installError }}</p>

    <div v-if="importResult" class="import-panel" data-testid="skill-import-panel">
      <div class="panel-copy">
        <strong>检查完成：{{ importResult.filename || '技能包' }}</strong>
        <span>{{ importResult.total_bytes }} 字节 · 入口 {{ importResult.entry }} · {{ importResult.files.length }} 个文件</span>
        <span v-if="importResult.manifest?.requested_tools?.length">申请工具：{{ importResult.manifest.requested_tools.join(', ') }}</span>
      </div>
      <div class="panel-form">
        <label>名称<input v-model="installName" maxlength="120"></label>
        <label>描述<input v-model="installDescription" maxlength="1000"></label>
        <label>分类<input v-model="installCategory" list="skill-categories" placeholder="未分类"></label>
        <datalist id="skill-categories">
          <option v-for="category in categories" :key="category.id" :value="category.name" />
        </datalist>
        <label>预算
          <select v-model="installBudget">
            <option value="short">短任务</option>
            <option value="read">深度阅读</option>
          </select>
        </label>
        <button class="primary" type="button" :disabled="installing || !installName.trim()" @click="install">{{ installing ? '安装中…' : '安装（默认停用）' }}</button>
        <button type="button" @click="importResult = null">取消</button>
      </div>
    </div>

    <div class="skill-list">
      <article v-for="skill in filteredSkills" :key="skill.id" class="skill-card" :data-skill-id="skill.id">
        <div class="skill-main">
          <div class="skill-title">
            <strong>{{ skill.name }}</strong>
            <span class="badge" :class="skill.source">{{ skill.source === 'builtin' ? '内置' : '自定义' }}</span>
            <span class="badge" :class="skill.status">{{ skill.status === 'enabled' ? '已启用' : skill.status === 'disabled' ? '已停用' : '已归档' }}</span>
          </div>
          <p class="muted">{{ skill.description || '暂无描述' }}</p>
          <div class="skill-meta">
            <span>{{ skill.default_version?.version ?? '—' }}</span>
            <span>{{ skill.categories.map(category => category.name).join(' / ') || '未分类' }}</span>
            <span v-if="skill.default_version?.manifest.requested_tools?.length">工具：{{ skill.default_version.manifest.requested_tools.join(', ') }}</span>
          </div>
        </div>
        <div class="skill-actions">
          <button
            type="button"
            data-testid="skill-version-toggle"
            :aria-expanded="expandedSkillId === skill.id"
            :disabled="historyLoadingId === skill.id"
            @click="toggleVersions(skill)"
          >{{ historyLoadingId === skill.id ? '版本载入中…' : '版本' }}</button>
          <button v-if="skill.status !== 'enabled'" type="button" :disabled="busyId === skill.id" @click="setStatus(skill, true)">启用</button>
          <button v-else type="button" :disabled="busyId === skill.id" @click="setStatus(skill, false)">停用</button>
        </div>
        <div v-if="expandedSkillId === skill.id" class="version-panel" data-testid="skill-version-panel">
          <div class="version-header">
            <strong>版本历史</strong>
            <span>回退只影响后续新会话，不会修改历史会话和运行记录。</span>
          </div>
          <div v-for="version in versionHistories[skill.id] || []" :key="version.id" class="version-row" :class="{ default: version.is_default }">
            <div class="version-main">
              <div class="version-title">
                <strong>{{ version.version }}</strong>
                <span v-if="version.is_default" class="badge enabled">默认</span>
                <span class="muted">{{ formatVersionTime(version.created_at) }}</span>
              </div>
              <div class="version-meta">
                <span>摘要 {{ version.content_hash }}</span>
                <span>引用：会话 {{ version.references.sessions }} · 运行 {{ version.references.runs }} · 模板 {{ version.references.templates }}</span>
              </div>
            </div>
            <button
              v-if="!version.is_default"
              type="button"
              data-testid="rollback-version"
              :disabled="versionBusyKey === `${skill.id}:${version.id}`"
              @click="rollbackVersion(skill, version)"
            >{{ versionBusyKey === `${skill.id}:${version.id}` ? '回退中…' : '设为默认' }}</button>
          </div>
          <p v-if="!(versionHistories[skill.id] || []).length" class="muted">暂无版本记录。</p>
        </div>
      </article>
      <p v-if="!loading && !filteredSkills.length" class="muted empty-state">没有匹配的技能。</p>
      <p v-if="loading" class="muted">正在载入技能…</p>
    </div>
  </section>
</template>

<style scoped>
.skills-workspace { display:flex; flex-direction:column; flex:1; min-height:0; padding:var(--space-5); overflow-y:auto; }
.module-heading { display:flex; justify-content:space-between; align-items:flex-start; gap:var(--space-4); margin-bottom:var(--space-4); }
.eyebrow { color:var(--accent); font-size:11px; letter-spacing:.12em; margin:0 0 var(--space-1); }
h1 { margin:0 0 var(--space-1); font-size:22px; }
.heading-actions { display:flex; align-items:center; gap:var(--space-2); }
.heading-actions input[type=file] { display:none; }
.skills-toolbar { display:grid; grid-template-columns:minmax(180px,1fr) repeat(3,minmax(120px,160px)); gap:var(--space-2); margin-bottom:var(--space-3); }
.skill-list { display:flex; flex-direction:column; gap:var(--space-3); }
.skill-card { display:flex; justify-content:space-between; gap:var(--space-3); padding:var(--space-3) var(--space-4); border:1px solid var(--border); border-radius:var(--radius); background:var(--surface); }
.skill-main { min-width:0; display:flex; flex-direction:column; gap:var(--space-1); }
.skill-title { display:flex; align-items:center; gap:var(--space-2); flex-wrap:wrap; }
.badge { padding:2px 7px; border-radius:999px; border:1px solid var(--border); color:var(--text-muted); font-size:11px; }
.badge.enabled { color:var(--success); border-color:var(--success); }
.badge.zip { color:var(--accent); }
.skill-meta { display:flex; gap:var(--space-3); flex-wrap:wrap; color:var(--text-muted); font-size:12px; }
.skill-actions { display:flex; align-items:center; flex-shrink:0; }
.version-panel { width:100%; display:flex; flex-direction:column; gap:var(--space-2); padding-top:var(--space-3); border-top:1px solid var(--border); }
.version-header { display:flex; flex-direction:column; gap:2px; }
.version-header span { color:var(--text-muted); font-size:12px; }
.version-row { display:flex; justify-content:space-between; align-items:center; gap:var(--space-3); padding:var(--space-2) var(--space-3); border:1px solid var(--border); border-radius:var(--radius); }
.version-row.default { border-color:var(--success); }
.version-main { min-width:0; display:flex; flex-direction:column; gap:2px; }
.version-title { display:flex; align-items:center; gap:var(--space-2); flex-wrap:wrap; }
.version-meta { display:flex; gap:var(--space-3); flex-wrap:wrap; color:var(--text-muted); font-size:11px; word-break:break-all; }
.import-panel { display:flex; flex-direction:column; gap:var(--space-3); margin-bottom:var(--space-4); padding:var(--space-4); border:1px solid var(--accent); border-radius:var(--radius); background:var(--surface); }
.panel-copy { display:flex; flex-direction:column; gap:4px; }
.panel-form { display:grid; grid-template-columns:repeat(2,minmax(160px,1fr)); gap:var(--space-2); align-items:end; }
.panel-form label { display:flex; flex-direction:column; gap:4px; font-size:12px; color:var(--text-muted); }
.empty-state { padding:var(--space-5); text-align:center; }
.form-error { color:var(--danger); }
@media(max-width:900px) { .module-heading,.skill-card { flex-direction:column; } .skills-toolbar { grid-template-columns:1fr 1fr; } .heading-actions { width:100%; } }
@media(max-width:600px) { .skills-workspace { padding:var(--space-3); } .skills-toolbar,.panel-form { grid-template-columns:1fr; } }
</style>
