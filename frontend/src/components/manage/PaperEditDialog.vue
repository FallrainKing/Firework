<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { papersApi } from '@/api/papers'
import type { Collection, Paper } from '@/api/types'
import StateFeedback from '@/components/StateFeedback.vue'

const props = defineProps<{ paperId: number }>()
const emit = defineEmits<{ close: []; saved: [] }>()

const paper = ref<Paper | null>(null)
const collections = ref<Collection[]>([])
const title = ref('')
const authors = ref('')
const affiliations = ref('')
const confirmAffiliations = ref(false)
const summary = ref('')
const selectedCollections = ref<number[]>([])
const provenance = ref('')
const loading = ref(true)
const loadError = ref<string | null>(null)
const saved = ref(false)
const saveError = ref<string | null>(null)
const saving = ref(false)

function fill(p: Paper) {
  paper.value = p
  title.value = p.title || ''
  authors.value = p.authors.join('\n')
  affiliations.value = p.affiliations.join('\n')
  confirmAffiliations.value = (p as Paper & { affiliation_source?: string }).affiliation_source === 'user'
  summary.value = p.brief_summary || p.summary || ''
  selectedCollections.value = p.collections.map(c => c.id)
  const source = (p as Paper & { affiliation_source?: string }).affiliation_source
  provenance.value = source === 'user' ? '单位：用户已确认' : source === 'missing' ? '单位：尚未补全' : '单位：PDF 首页候选，尚未确认'
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const [p, c] = await Promise.all([papersApi.get(props.paperId), papersApi.collections()])
    collections.value = c.collections
    fill(p)
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '论文信息载入失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => { void load() })

const split = (v: string) => v.split('\n').map(s => s.trim()).filter(Boolean)

async function save() {
  if (!paper.value) return
  saving.value = true
  saveError.value = null
  saved.value = false
  try {
    await papersApi.patch(props.paperId, {
      metadata_version: paper.value.metadata_version,
      title: title.value,
      authors: split(authors.value),
      affiliations: split(affiliations.value),
      confirm_affiliations: confirmAffiliations.value,
      brief_summary: summary.value,
      collection_ids: selectedCollections.value,
    })
    saved.value = true
    emit('saved')
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function refreshCard() {
  try {
    fill(await papersApi.refreshCard(props.paperId))
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : '刷新失败'
  }
}
</script>

<template>
  <div class="paper-dialog" role="dialog" aria-label="管理论文信息">
    <div class="dialog-heading">
      <h2>管理论文信息</h2>
      <button type="button" aria-label="关闭" @click="emit('close')">×</button>
    </div>
    <StateFeedback :loading="loading && !paper" :error="loadError" :empty="!loading && !loadError && !paper" empty-text="未提供论文。" @retry="load" />
    <template v-if="paper">
      <label>标题<input v-model="title" maxlength="500" /></label>
      <label>作者（每行一个）<textarea v-model="authors" rows="3"></textarea></label>
      <label>单位（每行一个）<textarea v-model="affiliations" rows="2"></textarea></label>
      <p class="muted provenance">{{ provenance }}</p>
      <label class="checkbox"><input v-model="confirmAffiliations" type="checkbox" />单位已核对确认</label>
      <label>简要摘要<textarea v-model="summary" rows="3" maxlength="4000"></textarea></label>
      <label>论文分类
        <select v-model="selectedCollections" multiple size="4">
          <option v-for="c in collections" :key="c.id" :value="c.id">{{ c.path ?? c.name }}</option>
        </select>
      </label>
      <StateFeedback :saving="saving" :saved="saved" :save-error="saveError" />
      <div class="dialog-footer">
        <button type="button" @click="refreshCard">刷新首页卡片</button>
        <button type="button" @click="emit('close')">取消</button>
        <button type="button" class="primary save-paper" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.paper-dialog { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-4); background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); width: min(560px, 92vw); max-height: 86dvh; overflow-y: auto; }
.dialog-heading { display: flex; justify-content: space-between; align-items: center; }
.dialog-heading h2 { margin: 0; font-size: 16px; }
.dialog-heading button { border: none; background: none; font-size: 18px; }
label { display: flex; flex-direction: column; gap: var(--space-1); font-size: 13px; color: var(--text-muted); }
label.checkbox { flex-direction: row; align-items: center; gap: var(--space-2); }
.provenance { font-size: 12px; margin: 0; }
.dialog-footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
</style>
