import { defineStore } from 'pinia'
import { papersApi } from '@/api/papers'
import { workbenchApi } from '@/api/workbench'
import type { Collection, Paper, RecentRead } from '@/api/types'

export const useLibraryStore = defineStore('library', {
  state: () => ({
    recent: [] as RecentRead[],
    collections: [] as Collection[],
    papersByCollection: {} as Record<number, Paper[]>,
    loading: false,
  }),
  actions: {
    async refresh() {
      this.loading = true
      try {
        const [recent, collections] = await Promise.all([workbenchApi.recent(), papersApi.collections()])
        this.recent = recent.recent
        this.collections = collections.collections
      } finally {
        this.loading = false
      }
    },
    async loadCollection(id: number) {
      const { papers } = await papersApi.list({ collection_id: id, limit: 100 })
      this.papersByCollection[id] = papers
    },
    async createCollection(name: string): Promise<Collection> {
      const created = await papersApi.createCollection(name)
      await this.refresh()
      return created
    },
  },
})
