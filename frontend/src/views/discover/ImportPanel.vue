<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { importsApi } from '@/api/imports'
import { papersApi } from '@/api/papers'
import { uid32 } from '@/api/client'
import type { Collection, ImportRequest } from '@/api/types'

const props = withDefaults(defineProps<{ targetPaperId?: number | null }>(), { targetPaperId: null })
const emit = defineEmits<{ 'open-paper': [paperId: number]; 'library-updated': [] }>()

const collections = ref<Collection[]>([])
const collectionId = ref('')
const sourceValue = ref('')
const target = ref<number | null>(props.targetPaperId)
const imports = ref<ImportRequest[]>([])
const status = ref('')
const error = ref('')
const submitting = ref(false)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const tracking = new Set<string>()

const STATUS_TEXT: Record<string, string> = { pending: '等待智能体执行', running: '正在下载、解析和索引', completed: '已入库', failed: '未完成' }

async function track(item: ImportRequest) {
  const i = imports.value.findIndex(x => x.id === item.id)
  if (i >= 0) imports.value[i] = item
  else imports.value.unshift(item)
  if (item.status === 'completed') emit('library-updated')
  if (['completed', 'failed'].includes(item.status)) { tracking.delete(item.id); return }
  if (tracking.has(item.id)) return
  tracking.add(item.id)
  await new Promise(r => setTimeout(r, 2000))
  try {
    await track(await importsApi.get(item.id))
  } catch (e) {
    tracking.delete(item.id)
    error.value = e instanceof Error ? e.message : '状态获取失败'
  }
}

onMounted(async () => {
  const [cols, list] = await Promise.all([papersApi.collections(), importsApi.list()])
  collections.value = cols.collections
  for (const item of list.imports.slice().reverse()) void track(item)
})

async function submitSource() {
  if (!sourceValue.value.trim()) return
  submitting.value = true
  error.value = ''
  try {
    const item = await importsApi.source({ value: sourceValue.value.trim(), channel: 'auto', collection_id: collectionId.value ? Number(collectionId.value) : null, target_paper_id: target.value, request_key: uid32() })
    void track(item)
    status.value = '导入任务已保存，离开页面后仍可查看状态。'
    sourceValue.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '导入失败'
  } finally {
    submitting.value = false
  }
}

async function uploadFiles(files: File[]) {
  if (files.length > 8) throw new Error('一次最多上传 8 个文件')
  if (files.some(f => f.size > 30 * 1024 * 1024)) throw new Error('每个 PDF 不得超过 30MB')
  if (target.value && files.length !== 1) throw new Error('补充已有条目时请选择一个 PDF')
  uploading.value = true
  error.value = ''
  try {
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      form.append('request_key', uid32())
      if (collectionId.value) form.append('collection_id', collectionId.value)
      if (target.value) form.append('target_paper_id', String(target.value))
      const item = await importsApi.upload(form)
      void track(item)
    }
    status.value = files.length + ' 个上传任务已保存。'
    if (fileInput.value) fileInput.value.value = ''
  } finally {
    uploading.value = false
  }
}

function onFiles() {
  void uploadFiles(Array.from(fileInput.value?.files ?? [])).catch(e => { error.value = e instanceof Error ? e.message : '上传失败' })
}

async function retry(id: string) {
  try {
    void track(await importsApi.retry(id))
  } catch (e) {
    error.value = e instanceof Error ? e.message : '重试失败'
  }
}

defineExpose({ uploadFiles })
</script>

<template>
  <div class="import-panel">
    <h2>添加论文</h2>
    <label>保存到分类
      <select v-model="collectionId" class="import-collection">
        <option value="">未分类</option>
        <option v-for="c in collections" :key="c.id" :value="String(c.id)">{{ c.name }}</option>
      </select>
    </label>
    <form class="source-form" @submit.prevent="submitSource">
      <label>arXiv ID / DOI / 公开 PDF 链接
        <input v-model="sourceValue" class="source-value" required maxlength="2000" placeholder="2406.09246 或 10.… 或 https://…pdf" />
      </label>
      <button class="primary" type="submit" :disabled="submitting">识别并导入</button>
    </form>
    <p class="muted fine">DOI 首先保存书目信息；无法取得全文时可继续上传 PDF。链接需为可直接下载的公开 HTTPS PDF。</p>
    <form class="upload-form" @submit.prevent="onFiles">
      <label>上传本地 PDF（支持多选）
        <input ref="fileInput" type="file" accept="application/pdf,.pdf" multiple required />
      </label>
      <label>补充到已有论文（可选）
        <input v-model.number="target" type="number" min="1" placeholder="填写仅有书目信息的论文编号" />
      </label>
      <button type="submit" :disabled="uploading">上传并入库</button>
    </form>
    <p v-if="status" role="status">{{ status }}</p>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>

    <h3>导入记录</h3>
    <article v-for="item in imports" :key="item.id" class="import-row">
      <strong>{{ item.original_filename || item.source_value }}</strong>
      <p class="muted">{{ STATUS_TEXT[item.status] || item.status }} · {{ item.created_at }}</p>
      <p :class="item.error ? 'form-error' : 'muted'">{{ item.error || item.message || '' }}</p>
      <div class="result-actions">
        <button v-if="item.paper_id" @click="emit('open-paper', item.paper_id)">打开论文 #{{ item.paper_id }}</button>
        <button v-if="item.status === 'failed'" class="retry-import" @click="retry(item.id)">手动重试</button>
      </div>
    </article>
    <p v-if="!imports.length" class="muted">暂无导入记录</p>
  </div>
</template>

<style scoped>
.import-panel { padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-2); overflow-y: auto; height: 100%; }
h2 { margin: 0; font-size: 17px; }
h3 { margin: var(--space-3) 0 0; font-size: 14px; }
label { display: flex; flex-direction: column; gap: var(--space-1); font-size: 13px; color: var(--text-muted); }
form { display: flex; flex-direction: column; gap: var(--space-2); }
.fine { font-size: 11px; }
.import-row { border: 1px solid var(--border); border-radius: var(--radius); padding: var(--space-2) var(--space-3); background: var(--surface); display: flex; flex-direction: column; gap: var(--space-1); }
.import-row p { margin: 0; font-size: 12px; }
.result-actions { display: flex; gap: var(--space-1); }
.result-actions button { padding: var(--space-1) var(--space-2); font-size: 12px; }
.form-error { color: var(--danger); }
</style>
