<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { uid32 } from '@/api/client'
import {
  skillsApi,
  type Skill,
  type SkillAuditEvent,
  type SkillCategory,
  type SkillImport,
  type SkillResource,
  type SkillResourceContent,
  type SkillVersionHistoryItem,
} from '@/api/skills'
import SkillDesigner from '@/components/SkillDesigner.vue'
import StateFeedback from '@/components/StateFeedback.vue'

const designerOpen=ref(false),designerSkill=ref<Skill|null>(null)
function design(skill:Skill|null=null){designerSkill.value=skill;designerOpen.value=true}
const skills = ref<Skill[]>([])
const categories = ref<SkillCategory[]>([])
const loading = ref(false)
const error = ref('')
const query = ref('')
const statusFilter = ref('')
const sourceFilter = ref('')
const categoryFilter = ref<number | null>(null)
const busyId = ref<string | null>(null)
const validationBusyId = ref<string | null>(null)
const validationRuns = ref<Record<string, { run_id: string; status: string; model_invocation: boolean }>>({})
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const importResult = ref<SkillImport | null>(null)
const installName = ref('')
const installDescription = ref('')
const installCategory = ref('')
const installBudget = ref('short')
const installError = ref('')
const installSkillId = ref('')
const expandedSkillId = ref<string | null>(null)
const historyLoadingId = ref<string | null>(null)
const versionHistories = ref<Record<string, SkillVersionHistoryItem[]>>({})
const versionBusyKey = ref<string | null>(null)
const resourceVersionKey = ref<string | null>(null)
const resourceLoadingKey = ref<string | null>(null)
const resources = ref<Record<string, SkillResource[]>>({})
const resourceContent = ref<SkillResourceContent | null>(null)
const resourceContentKey = ref<string | null>(null)
const resourceContentLoadingKey = ref<string | null>(null)
const auditSkillId = ref<string | null>(null)
const auditLoadingId = ref<string | null>(null)
const auditEvents = ref<Record<string, SkillAuditEvent[]>>({})

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
    installSkillId.value = ''
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
      skill_id: installSkillId.value || undefined,
    })
    importResult.value = null
    installCategory.value = ''
    installSkillId.value = ''
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

async function validateRun(skill: Skill) {
  if (skill.status !== 'enabled') {
    error.value = '只有已启用技能才能发起真实执行验证。'
    return
  }
  const confirmed = window.confirm('验证执行会显式发起一次真实模型调用，并记录用量与成本。确定继续吗？')
  if (!confirmed) return

  validationBusyId.value = skill.id
  error.value = ''
  try {
    const result = await skillsApi.validateRun(
      skill.id,
      '请执行一次最小技能验证，并简要说明结果。',
      uid32(),
    )
    validationRuns.value = {
      ...validationRuns.value,
      [skill.id]: {
        run_id: result.run_id,
        status: result.status,
        model_invocation: result.model_invocation,
      },
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '技能验证执行提交失败'
  } finally {
    validationBusyId.value = null
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

async function toggleResources(skill: Skill, version: SkillVersionHistoryItem) {
  const key = `${skill.id}:${version.id}`
  if (resourceVersionKey.value === key) {
    resourceVersionKey.value = null
    resourceContent.value = null
    resourceContentKey.value = null
    return
  }
  resourceVersionKey.value = key
  resourceContent.value = null
  resourceContentKey.value = null
  if (resources.value[key]?.length) return

  resourceLoadingKey.value = key
  error.value = ''
  try {
    const data = await skillsApi.versionResources(skill.id, version.id)
    resources.value = { ...resources.value, [key]: data.resources }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '技能资源列表载入失败'
    resourceVersionKey.value = null
  } finally {
    resourceLoadingKey.value = null
  }
}

async function openResource(skill: Skill, version: SkillVersionHistoryItem, resource: SkillResource) {
  const key = `${skill.id}:${version.id}`
  resourceContentLoadingKey.value = `${key}:${resource.path}`
  error.value = ''
  try {
    resourceContent.value = await skillsApi.versionResourceContent(skill.id, version.id, resource.path)
    resourceContentKey.value = key
  } catch (e) {
    error.value = e instanceof Error ? e.message : '技能资源预览失败'
  } finally {
    resourceContentLoadingKey.value = null
  }
}

async function toggleAudit(skill: Skill) {
  if (auditSkillId.value === skill.id) {
    auditSkillId.value = null
    return
  }
  auditSkillId.value = skill.id
  if (auditEvents.value[skill.id]?.length) return

  auditLoadingId.value = skill.id
  error.value = ''
  try {
    const data = await skillsApi.audit(skill.id)
    auditEvents.value = { ...auditEvents.value, [skill.id]: data.audit }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '技能审计历史载入失败'
    auditSkillId.value = null
  } finally {
    auditLoadingId.value = null
  }
}

const auditActionLabels: Record<string, string> = {
  install: '安装',
  enable: '启用',
  disable: '停用',
  'default-version': '默认版本切换',
  'validate-run': '执行验证',
}

watch(categoryFilter, () => undefined)
</script>

<template>
  <section class="skills-workspace">
    <SkillDesigner v-if="designerOpen" :skill="designerSkill" @close="designerOpen=false" @saved="refresh"/>
    <div class="module-heading">
      <div>
        <p class="eyebrow">DYNAMIC SKILLS</p>
        <h1>技能库</h1>
        <p class="muted">创建、编辑或导入技能，管理显示名、版本和适用功能。</p>
      </div>
      <div class="heading-actions">
        <button type="button" @click="design()">＋ 新建 Skill</button>
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

    <StateFeedback
      :loading="loading && !skills.length"
      :error="error || null"
      :empty="!loading && !error && !filteredSkills.length"
      empty-text="没有匹配的技能。"
      :saving="uploading || installing || busyId !== null || versionBusyKey !== null"
      :save-error="installError || null"
      @retry="refresh"
    />

    <div v-if="importResult" class="import-panel" data-testid="skill-import-panel">
      <div class="panel-copy">
        <strong>检查完成：{{ importResult.filename || '技能包' }}</strong>
        <span>{{ importResult.total_bytes }} 字节 · 入口 {{ importResult.entry }} · {{ importResult.files.length }} 个文件</span>
        <span v-if="importResult.manifest?.requested_tools?.length">申请工具：{{ importResult.manifest.requested_tools.join(', ') }}</span>
      </div>
      <div class="panel-form">
        <label>安装目标
          <select v-model="installSkillId">
            <option value="">创建新技能</option>
            <option v-for="target in skills.filter(item => item.source === 'zip')" :key="target.id" :value="target.id">
              升级：{{ target.name }}（当前 {{ target.default_version?.version ?? '—' }}）
            </option>
          </select>
        </label>
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
          <p v-if="validationRuns[skill.id]" class="validation-result" data-testid="skill-validation-result">
            验证运行 {{ validationRuns[skill.id].run_id }} · {{ validationRuns[skill.id].status }} · 真实模型调用
          </p>
        </div>
        <div class="skill-actions">
          <button type="button" @click="design(skill)">配置 / 编辑</button>
          <button
            type="button"
            data-testid="skill-version-toggle"
            :aria-expanded="expandedSkillId === skill.id"
            :disabled="historyLoadingId === skill.id"
            @click="toggleVersions(skill)"
          >{{ historyLoadingId === skill.id ? '版本载入中…' : '版本' }}</button>
          <button
            type="button"
            :disabled="auditLoadingId === skill.id"
            @click="toggleAudit(skill)"
          >{{ auditLoadingId === skill.id ? '记录载入中…' : '记录' }}</button>
          <button v-if="skill.status !== 'enabled'" type="button" :disabled="busyId === skill.id" @click="setStatus(skill, true)">启用</button>
          <button v-else type="button" :disabled="busyId === skill.id" @click="setStatus(skill, false)">停用</button>
          <button
            type="button"
            data-testid="skill-validate-run"
            :disabled="skill.status !== 'enabled' || validationBusyId === skill.id"
            :title="skill.status !== 'enabled' ? '启用后才能验证' : '显式发起一次真实模型调用'"
            @click="validateRun(skill)"
          >{{ validationBusyId === skill.id ? '提交中…' : '验证执行' }}</button>
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
            <button
              type="button"
              :disabled="resourceLoadingKey === `${skill.id}:${version.id}`"
              @click="toggleResources(skill, version)"
            >{{ resourceLoadingKey === `${skill.id}:${version.id}` ? '资源载入中…' : '资源' }}</button>
          <div
            v-if="resourceVersionKey === `${skill.id}:${version.id}`"
            class="resource-panel"
            data-testid="skill-resource-panel"
          >
            <div class="resource-list">
              <button
                v-for="resource in resources[`${skill.id}:${version.id}`] || []"
                :key="resource.path"
                type="button"
                :disabled="!resource.readable || resourceContentLoadingKey === `${skill.id}:${version.id}:${resource.path}`"
                @click="openResource(skill, version, resource)"
              >{{ resource.is_entry ? '入口 · ' : '' }}{{ resource.path }}</button>
            </div>
            <StateFeedback v-if="!(resources[`${skill.id}:${version.id}`] || []).length" empty empty-text="暂无可预览的文本资源。" />
            <div v-if="resourceContent && resourceContentKey === `${skill.id}:${version.id}`" class="resource-preview">
              <div class="resource-preview-header">
                <strong>{{ resourceContent.path }}</strong>
                <span>{{ resourceContent.size_bytes }} 字节{{ resourceContent.truncated ? ' · 已截断' : '' }}</span>
              </div>
              <pre>{{ resourceContent.content }}</pre>
            </div>
          </div>
          </div>
          <StateFeedback v-if="!(versionHistories[skill.id] || []).length" empty empty-text="暂无版本记录。" />
        </div>
        <div v-if="auditSkillId === skill.id" class="audit-panel" data-testid="skill-audit-panel">
          <strong>操作记录</strong>
          <div v-for="event in auditEvents[skill.id] || []" :key="event.id" class="audit-row">
            <strong>{{ auditActionLabels[event.action] || event.action }}</strong>
            <span>{{ formatVersionTime(event.created_at) }}</span>
            <span v-if="event.version_id">版本 #{{ event.version_id }}</span>
          </div>
          <StateFeedback v-if="!(auditEvents[skill.id] || []).length" empty empty-text="暂无操作记录。" />
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.skills-workspace { display:flex; flex-direction:column; flex:1; min-height:0; padding:var(--space-5); overflow-y:auto; }
.module-heading { display:flex; justify-content:space-between; align-items:flex-start; gap:var(--space-4); margin-bottom:var(--space-4); }
.eyebrow { color:var(--accent); font-size:12px; letter-spacing:.12em; margin:0 0 var(--space-1); }
h1 { margin:0 0 var(--space-1); font-size:22px; }
.heading-actions { display:flex; align-items:center; gap:var(--space-2); }
.heading-actions input[type=file] { display:none; }
.skills-toolbar { display:grid; grid-template-columns:minmax(180px,1fr) repeat(3,minmax(120px,160px)); gap:var(--space-2); margin-bottom:var(--space-3); }
.skill-list { display:flex; flex-direction:column; gap:var(--space-3); }
.skill-card { display:flex; justify-content:space-between; gap:var(--space-3); padding:var(--space-3) var(--space-4); border:1px solid var(--border); border-radius:var(--radius); background:var(--bg); }
.skill-main { min-width:0; display:flex; flex-direction:column; gap:var(--space-1); }
.skill-title { display:flex; align-items:center; gap:var(--space-2); flex-wrap:wrap; }
.badge { padding:2px 7px; border-radius:999px; border:1px solid var(--border); color:var(--text-muted); font-size:12px; }
.badge.enabled { color:var(--success); border-color:var(--success); }
.badge.zip { color:var(--accent); }
.skill-meta { display:flex; gap:var(--space-3); flex-wrap:wrap; color:var(--text-muted); font-size:12px; }
.skill-actions { display:flex; align-items:center; flex-shrink:0; }
.validation-result { margin:0; color:var(--text-muted); font-size:12px; word-break:break-all; }
.version-panel { width:100%; display:flex; flex-direction:column; gap:var(--space-2); padding-top:var(--space-3); border-top:1px solid var(--border); }
.version-header { display:flex; flex-direction:column; gap:2px; }
.version-header span { color:var(--text-muted); font-size:12px; }
.version-row { display:flex; justify-content:space-between; align-items:center; gap:var(--space-3); padding:var(--space-2) var(--space-3); border:1px solid var(--border); border-radius:var(--radius); }
.version-row.default { border-color:var(--success); }
.version-main { min-width:0; display:flex; flex-direction:column; gap:2px; }
.version-title { display:flex; align-items:center; gap:var(--space-2); flex-wrap:wrap; }
.version-meta { display:flex; gap:var(--space-3); flex-wrap:wrap; color:var(--text-muted); font-size:12px; word-break:break-all; }
.resource-panel { display:flex; flex-direction:column; gap:var(--space-2); padding:var(--space-2); border:1px solid var(--border); border-radius:var(--radius); }
.resource-list { display:flex; flex-wrap:wrap; gap:var(--space-2); }
.resource-preview { display:flex; flex-direction:column; gap:var(--space-1); }
.resource-preview-header { display:flex; justify-content:space-between; align-items:center; gap:var(--space-2); color:var(--text-muted); font-size:12px; }
.resource-preview pre { max-height:260px; overflow:auto; margin:0; padding:var(--space-2); border:1px solid var(--border); border-radius:var(--radius); white-space:pre-wrap; word-break:break-word; }
.audit-panel { width:100%; display:flex; flex-direction:column; gap:var(--space-2); padding-top:var(--space-3); border-top:1px solid var(--border); }
.audit-row { display:flex; align-items:center; gap:var(--space-3); flex-wrap:wrap; padding:var(--space-2) var(--space-3); border:1px solid var(--border); border-radius:var(--radius); font-size:12px; color:var(--text-muted); }
.import-panel { display:flex; flex-direction:column; gap:var(--space-3); margin-bottom:var(--space-4); padding:var(--space-4); border:1px solid var(--accent); border-radius:var(--radius); background:var(--bg); }
.panel-copy { display:flex; flex-direction:column; gap:4px; }
.panel-form { display:grid; grid-template-columns:repeat(2,minmax(160px,1fr)); gap:var(--space-2); align-items:end; }
.panel-form label { display:flex; flex-direction:column; gap:4px; font-size:12px; color:var(--text-muted); }
.empty-state { padding:var(--space-5); text-align:center; }
@media(max-width:900px) { .module-heading,.skill-card { flex-direction:column; } .skills-toolbar { grid-template-columns:1fr 1fr; } .heading-actions { width:100%; } }
@media(max-width:600px) { .skills-workspace { padding:var(--space-3); } .skills-toolbar,.panel-form { grid-template-columns:1fr; } }
</style>
