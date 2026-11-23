<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {skillAuthoring} from '@/api/skillAuthoring'
import type {Skill} from '@/api/skills'
import PaperPicker from './PaperPicker.vue'
import { useSessionsStore } from '@/stores/sessions'
import { sessionsApi } from '@/api/sessions'
import type { Session } from '@/api/types'
import StateFeedback from '@/components/StateFeedback.vue'

const props = withDefaults(defineProps<{
  mode: 'read' | 'compare' | 'chat' | 'review'
  templateId?: string
  paperIds?: number[]
  question?: string
}>(), { templateId: '', paperIds: () => [], question: '' })

const emit = defineEmits<{
  created: [session: Session, startingPrompt: string]
  close: []
  'open-import': []
}>()

const store = useSessionsStore()
const tab = ref<'new' | 'existing'>('new')
const title = ref('')
const templateId = ref(props.templateId || (props.mode === 'compare' ? 'compare' : props.mode === 'chat' ? 'chat' : 'read'))
const categoryId = ref<number | null>(null)
const prompt = ref(props.question)
const paperIds = ref<number[]>([...props.paperIds])
const skillChoices = ref<(Skill & {selectable:boolean})[]>([])
const skillId = ref('')
const surface = props.mode==='compare'?'compare':props.mode==='review'?'review':props.mode==='chat'?'research_chat':'reader_chat'
const creating = ref(false)
const error = ref('')

const existingSessions = ref<Session[]>([])
const existingId = ref<number | null>(null)

const showNewCategory = ref(false)
const newCategoryName = ref('')
const showNewTemplate = ref(false)
const newTemplate = ref({ name: '', skill: 'chat', prompt: '' })

const template = computed(() => store.templates.find(t => t.id === templateId.value))
const needsPapers = computed(() => ['read', 'compare', 'review'].includes(props.mode))
const canCreate = computed(() => {
  if (creating.value) return false
  if (!templateId.value) return false
  if (props.mode === 'compare') return paperIds.value.length >= 2
  if (needsPapers.value) return paperIds.value.length >= 1
  return true
})

watch(templateId, id => {
  const t = store.templates.find(x => x.id === id)
  if (t && !prompt.value) prompt.value = t.prompt
})

onMounted(async () => {
  await store.load()
  try { skillChoices.value=(await skillAuthoring.available(surface)).skills } catch { error.value='技能列表加载失败' }
  const t = store.templates.find(x => x.id === templateId.value)
  if (t && !prompt.value) prompt.value = t.prompt
  const { sessions } = await sessionsApi.list({ archived: false, limit: 100 })
  existingSessions.value = sessions
})

async function confirmCategory() {
  const name = newCategoryName.value.trim()
  if (!name) return
  try {
    const created = await store.addCategory(name)
    categoryId.value = created.id
    showNewCategory.value = false
    newCategoryName.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '新增分类失败'
  }
}

async function confirmTemplate() {
  if (!newTemplate.value.name.trim()) return
  try {
    const created = await store.addTemplate({ ...newTemplate.value, name: newTemplate.value.name.trim() })
    templateId.value = created.id
    showNewTemplate.value = false
    newTemplate.value = { name: '', skill: 'chat', prompt: '' }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '新增模板失败'
  }
}

async function create() {
  if (!canCreate.value) return
  creating.value = true
  error.value = ''
  try {
    const result = await sessionsApi.create({
      title: title.value.trim(),
      template_id: templateId.value,
      starting_prompt: prompt.value,
      category_id: categoryId.value,
      paper_ids: paperIds.value,
      ...(skillId.value?{skill_id:skillId.value,skill_version_id:skillChoices.value.find(s=>s.id===skillId.value)?.default_version_id??undefined,entry_context:surface}:{}),
    })
    emit('created', result.session, result.starting_prompt)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '创建任务失败'
  } finally {
    creating.value = false
  }
}

function openExisting() {
  const session = existingSessions.value.find(s => s.id === existingId.value)
  if (session) emit('created', session, session.draft_prompt)
}
</script>

<template>
  <div class="task-dialog" role="dialog" aria-label="任务窗口">
    <div class="dialog-heading">
      <h2>{{ mode === 'compare' ? '新建论文比较' : mode === 'chat' ? '新建研究讨论' : '新建论文阅读' }}</h2>
      <button type="button" aria-label="关闭" @click="emit('close')">×</button>
    </div>

    <div class="dialog-tabs">
      <button type="button" :class="{ active: tab === 'new' }" @click="tab = 'new'">新建任务</button>
      <button type="button" :class="{ active: tab === 'existing' }" @click="tab = 'existing'">选择已有会话</button>
    </div>

    <template v-if="tab === 'existing'">
      <select v-model="existingId" aria-label="已有会话">
        <option :value="null" disabled>选择会话…</option>
        <option v-for="s in existingSessions" :key="s.id" :value="s.id">{{ s.title }}（{{ s.last_status }}）</option>
      </select>
      <div class="dialog-footer">
        <button type="button" @click="emit('close')">取消</button>
        <button type="button" class="primary" :disabled="existingId === null" @click="openExisting">打开会话</button>
      </div>
    </template>

    <template v-else>
      <label>任务标题（可选）
        <input v-model="title" data-field="title" maxlength="160" placeholder="留空则使用模板名称" />
      </label>

      <label>执行技能
        <select v-model="skillId" aria-label="执行技能">
          <option value="">使用任务模板关联技能</option>
          <option v-for="s in skillChoices" :key="s.id" :value="s.id" :disabled="!s.selectable">{{ s.name }}</option>
        </select>
      </label>
      <label>任务模板
        <div class="inline-row">
          <select v-model="templateId" data-field="template">
            <option v-for="t in store.templates" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
          <button type="button" data-action="new-template" @click="showNewTemplate = !showNewTemplate">＋ 新模板</button>
        </div>
      </label>
      <div v-if="showNewTemplate" class="inline-create">
        <input v-model="newTemplate.name" placeholder="模板名称" maxlength="80" />
        <select v-model="newTemplate.skill">
          <option v-for="s in store.skills" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <textarea v-model="newTemplate.prompt" rows="2" placeholder="起步提示词" maxlength="3000" />
        <button type="button" data-action="confirm-template" @click="confirmTemplate">保存模板</button>
      </div>

      <label>会话分类
        <div class="inline-row">
          <select v-model="categoryId" data-field="category">
            <option :value="null">未分类</option>
            <option v-for="c in store.categories" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
          <button type="button" data-action="new-category" @click="showNewCategory = !showNewCategory">＋ 新分类</button>
        </div>
      </label>
      <div v-if="showNewCategory" class="inline-create">
        <input v-model="newCategoryName" data-field="new-category-name" placeholder="分类名称" maxlength="80" />
        <button type="button" data-action="confirm-category" @click="confirmCategory">保存分类</button>
      </div>

      <label v-if="needsPapers">关联论文{{ mode === 'compare' ? '（至少两篇）' : '' }}
        <PaperPicker v-model="paperIds" @open-import="emit('open-import')" />
      </label>

      <label>起步要求
        <textarea v-model="prompt" data-field="prompt" rows="3" maxlength="3000" placeholder="选择模板后可修改；发送前不会调用智能体" />
      </label>

      <StateFeedback :saving="creating" :save-error="error || null" />
      <div class="dialog-footer">
        <button type="button" @click="emit('close')">取消</button>
        <button type="button" class="primary" data-action="create" :disabled="!canCreate" @click="create">
          {{ creating ? '创建中…' : '创建任务' }}
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.task-dialog { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-4); background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); width: min(560px, 92vw); max-height: 86dvh; overflow-y: auto; }
.dialog-heading { display: flex; justify-content: space-between; align-items: center; }
.dialog-heading h2 { margin: 0; font-size: 16px; }
.dialog-heading button { border: none; background: none; font-size: 18px; }
.dialog-tabs { display: flex; gap: var(--space-1); }
.dialog-tabs button { flex: 1; }
.dialog-tabs button.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
label { display: flex; flex-direction: column; gap: var(--space-1); font-size: 13px; color: var(--text-muted); }
.inline-row { display: flex; gap: var(--space-2); }
.inline-row select { flex: 1; }
.inline-create { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); background: var(--surface); border-radius: var(--radius); }
.dialog-footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
</style>
