import { defineStore } from 'pinia'
import { schedulesApi } from '@/api/schedules'
import type { Schedule, ScheduleCreate } from '@/api/types'

export const useSchedulesStore = defineStore('schedules', {
  state: () => ({
    schedules: [] as Schedule[],
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async refresh() {
      this.loading = true
      try {
        const { schedules } = await schedulesApi.list()
        this.schedules = schedules
        this.error = null
      } catch (e) {
        this.error = e instanceof Error ? e.message : '定时任务加载失败'
      } finally {
        this.loading = false
      }
    },
    async create(body: ScheduleCreate) {
      await schedulesApi.create(body)
      await this.refresh()
    },
    async toggle(id: number, enabled: boolean) {
      await schedulesApi.enable(id, enabled)
      await this.refresh()
    },
    async run(id: number) {
      await schedulesApi.run(id)
      await this.refresh()
    },
  },
})
