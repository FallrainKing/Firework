<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { papersApi } from '@/api/papers'
import type { Paper } from '@/api/types'
import StateFeedback from '@/components/StateFeedback.vue'

const props = defineProps<{ modelValue: number[] }>()
const emit = defineEmits<{ 'update:modelValue': [ids: number[]]; 'open-import': [] }>()

const query = ref('')
const results = ref<Paper[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const selected = ref<Set<number>>(new Set(props.modelValue))

async function search() {
  loading.value = true
  error.value = null
  try {
    const { papers } = await papersApi.list({ q: query.value, limit: 50 })
    results.value = papers
  } catch (e) {
    error.value = e instanceof Error ? e.message : '论文搜索失败'
  } finally {
    loading.value = false
  }
}

onMounted(search)
watch(query, () => { void search() })

function toggle(id: number, on: boolean) {
  if (on) selected.value.add(id)
  else selected.value.delete(id)
  emit('update:modelValue', [...selected.value])
}

watch(() => props.modelValue, ids => { selected.value = new Set(ids) })
</script>

<template>
  <div class="paper-picker">
    <div class="picker-head">
      <input v-model="query" type="search" placeholder="搜索论文标题 / 摘要…" aria-label="搜索论文" />
      <button type="button" data-action="open-import" @click="emit('open-import')">导入新论文</button>
    </div>
    <ul class="picker-list">
      <li v-for="p in results" :key="p.id">
        <label>
          <input type="checkbox" :checked="selected.has(p.id)" @change="toggle(p.id, ($event.target as HTMLInputElement).checked)" />
          <span class="picker-title">{{ p.title }}</span>
          <span v-if="!p.has_pdf" class="muted no-pdf">缺全文</span>
        </label>
      </li>
    </ul>
    <StateFeedback :loading="loading && !results.length" :error="error" :empty="!loading && !error && !results.length" empty-text="没有匹配的论文，可导入新材料。" @retry="search" />
  </div>
</template>

<style scoped>
.paper-picker { display: flex; flex-direction: column; gap: var(--space-2); }
.picker-head { display: flex; gap: var(--space-2); }
.picker-head input { flex: 1; }
.picker-list { list-style: none; margin: 0; padding: 0; max-height: 220px; overflow-y: auto; border: 1px solid var(--border); border-radius: var(--radius); }
.picker-list li + li { border-top: 1px solid var(--border); }
.picker-list label { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); cursor: pointer; }
.picker-list label:hover { background: var(--accent-soft); }
.picker-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.no-pdf { font-size: 11px; flex-shrink: 0; }
</style>
