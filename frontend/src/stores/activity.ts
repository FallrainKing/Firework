import { defineStore } from 'pinia'
import { agentApi } from '@/api/agent'
import type { Run } from '@/api/types'

const TERMINAL = ['succeeded', 'failed', 'cancelled']
const POLL_MS = 2000

interface ActiveRun extends Run {
  cancelling?: boolean
}

// 非响应式资源：SSE 连接与定时器。
const sources = new Map<string, EventSource>()
const fallbackTimers = new Map<string, ReturnType<typeof setInterval>>()
let refreshTimer: ReturnType<typeof setInterval> | null = null

export const useActivityStore = defineStore('activity', {
  state: () => ({
    active: [] as ActiveRun[],
    visible: false,
    lastTerminal: null as { id: string; status: string; error: string | null } | null,
  }),
  actions: {
    async refresh() {
      try {
        const { runs } = await agentApi.listRuns()
        const active = runs.filter(r => r.status === 'queued' || r.status === 'running')
        this.active = active.map(r => {
          const prev = this.active.find(a => a.id === r.id)
          return { ...prev, ...r, cancelling: prev?.cancelling }
        })
        for (const r of this.active) {
          if (r.status === 'running' && !sources.has(r.id) && !fallbackTimers.has(r.id)) this.subscribe(r.id)
        }
      } catch {
        /* 面板静默重试 */
      }
    },
    subscribe(id: string) {
      const es = new EventSource(agentApi.runEventsUrl(id))
      sources.set(id, es)
      es.onmessage = ev => {
        try {
          this.applyFrame(id, JSON.parse(ev.data) as { status?: string; progress?: Run['progress'] })
        } catch {
          /* 忽略坏帧 */
        }
      }
      es.onerror = () => {
        es.close()
        sources.delete(id)
        this.fallback(id)
      }
    },
    applyFrame(id: string, frame: { status?: string; progress?: Run['progress'] }) {
      const run = this.active.find(r => r.id === id)
      if (!run) return
      if (frame.progress && Object.keys(frame.progress).length) run.progress = frame.progress
      if (frame.status) run.status = frame.status as Run['status']
      if (frame.status && TERMINAL.includes(frame.status)) this.finish(id, frame.status, run.error)
    },
    finish(id: string, status: string, error: string | null) {
      const es = sources.get(id)
      if (es) { es.close(); sources.delete(id) }
      const timer = fallbackTimers.get(id)
      if (timer) { clearInterval(timer); fallbackTimers.delete(id) }
      this.active = this.active.filter(r => r.id !== id)
      this.lastTerminal = { id, status, error }
    },
    fallback(id: string) {
      if (fallbackTimers.has(id)) return
      const timer = setInterval(async () => {
        try {
          const run = await agentApi.getRun(id)
          this.applyFrame(id, { status: run.status, progress: run.progress })
          if (TERMINAL.includes(run.status)) {
            clearInterval(timer)
            fallbackTimers.delete(id)
          }
        } catch {
          /* 继续重试 */
        }
      }, POLL_MS)
      fallbackTimers.set(id, timer)
    },
    async cancel(id: string) {
      const run = this.active.find(r => r.id === id)
      if (run) run.cancelling = true
      try {
        await agentApi.cancelRun(id)
      } catch {
        if (run) run.cancelling = false
      }
    },
    start() {
      if (this.visible) return
      this.visible = true
      void this.refresh()
      refreshTimer = setInterval(() => void this.refresh(), POLL_MS)
    },
    stop() {
      this.visible = false
      if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null }
      for (const es of sources.values()) es.close()
      sources.clear()
      for (const t of fallbackTimers.values()) clearInterval(t)
      fallbackTimers.clear()
    },
  },
})
