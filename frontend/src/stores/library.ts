import { defineStore } from 'pinia'
import { papersApi } from '@/api/papers'
import { workbenchApi } from '@/api/workbench'
import type { Collection, Paper, RecentRead } from '@/api/types'

export const useLibraryStore = defineStore('library', {
  state: () => ({
    recent: [] as RecentRead[],
    collections: [] as Collection[],
    papersByCollection: {} as Record<number, Paper[]>,
    papersById: {} as Record<number, Paper>,
    loading: false,
  }),
  actions: {
    async refresh() {
      this.loading = true
      try {
        const [recent, collections, papers] = await Promise.all([
          workbenchApi.recent(),
          papersApi.collections(),
          papersApi.list({ limit: 100 }),
        ])
        this.recent = recent.recent
        this.collections = collections.collections
        this.papersById = Object.fromEntries(papers.papers.map(p => [p.id, p]))
      } finally {
        this.loading = false
      }
    },
    async loadCollection(id: number) {
      const { papers } = await papersApi.list({ collection_id: id, limit: 100 })
      this.papersByCollection[id] = papers
    },
    async createCollection(name: string, parentId: number|null = null): Promise<Collection> {
      const created = await papersApi.createCollection(name,parentId)
      await this.refresh()
      return created
    },
  },
})
