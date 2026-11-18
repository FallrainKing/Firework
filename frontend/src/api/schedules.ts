import { api } from './client'
import type { Run, Schedule, ScheduleCreate } from './types'

export const schedulesApi = {
  list(): Promise<{ schedules: Schedule[] }> {
    return api('/api/workbench/schedules')
  },
  create(body: ScheduleCreate): Promise<Schedule> {
    return api('/api/workbench/schedules', { body })
  },
  enable(id: number, enabled: boolean): Promise<{ saved: boolean }> {
    return api(`/api/workbench/schedules/${id}`, { method: 'PATCH', body: { enabled } })
  },
  run(id: number): Promise<Run> {
    return api(`/api/workbench/schedules/${id}/run`, { method: 'POST' })
  },
}
