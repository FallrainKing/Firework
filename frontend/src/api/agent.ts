import { api, uid32 } from './client'
import type { Run, RunCreate } from './types'

export const agentApi = {
  createRun(body: RunCreate): Promise<Run> {
    return api<Run>('/api/agent/runs', { body: { ...body, request_key: body.request_key ?? uid32() } })
  },
  listRuns(conversationId?: number): Promise<{ runs: Run[] }> {
    const q = conversationId !== undefined ? `?conversation_id=${conversationId}` : ''
    return api(`/api/agent/runs${q}`)
  },
  getRun(id: string): Promise<Run> {
    return api(`/api/agent/runs/${id}`)
  },
  cancelRun(id: string): Promise<Run> {
    return api(`/api/agent/runs/${id}/cancel`, { method: 'POST' })
  },
  runEventsUrl(id: string): string {
    return `/api/agent/runs/${id}/events`
  },
  status(): Promise<Record<string, unknown>> {
    return api('/api/agent/status')
  },
}
