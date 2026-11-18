import { defineStore } from 'pinia'
import { workbenchApi } from '@/api/workbench'
import { uid32 } from '@/api/client'
import type { Layout, Tab, WorkspaceState } from '@/api/types'

const ID_KEY = 'research-workspace-id'
export const MAX_TABS = 20

function workspaceId(): string {
  let id = localStorage.getItem(ID_KEY)
  if (!id || !/^[a-f0-9]{32}$/.test(id)) {
    id = uid32()
    localStorage.setItem(ID_KEY, id)
  }
  return id
}

const DEFAULT_LAYOUT: Layout = { left_width: 235, right_width: 340, left_hidden: false, right_hidden: false }

let persistTimer: ReturnType<typeof setTimeout> | null = null

export const useWorkbenchStore = defineStore('workbench', {
  state: () => ({
    workspaceId: workspaceId(),
    tabs: [] as Tab[],
    activePaperId: null as number | null,
    view: 'read' as WorkspaceState['view'],
    layout: { ...DEFAULT_LAYOUT } as Layout,
    loaded: false,
    saveError: null as string | null,
  }),
  getters: {
    snapshot(state): WorkspaceState {
      return {
        layout: { ...state.layout },
        tabs: state.tabs.map(t => ({ ...t })),
        active_paper_id: state.activePaperId,
        view: state.view,
      }
    },
  },
  actions: {
    async load() {
      const s = await workbenchApi.getState(this.workspaceId)
      this.tabs = s.tabs.map(t => ({ ...t }))
      this.layout = { ...s.layout }
      this.activePaperId = s.active_paper_id
      this.view = s.view
      this.loaded = true
    },
    openPaper(paperId: number, sessionId?: number) {
      const existing = this.tabs.find(t => t.paper_id === paperId)
      if (existing) {
        this.activePaperId = paperId
      } else {
        if (this.tabs.length >= MAX_TABS) throw new Error('打开的标签已达上限（20），请先关闭一些标签')
        this.tabs.push({ paper_id: paperId, session_id: sessionId ?? null })
        this.activePaperId = paperId
      }
      this.schedulePersist()
    },
    closeTab(paperId: number) {
      this.tabs = this.tabs.filter(t => t.paper_id !== paperId)
      if (this.activePaperId === paperId) {
        this.activePaperId = this.tabs.length ? this.tabs[this.tabs.length - 1].paper_id : null
      }
      this.schedulePersist()
    },
    activate(paperId: number) {
      this.activePaperId = paperId
      this.schedulePersist()
    },
    setTabSession(paperId: number, sessionId: number) {
      const tab = this.tabs.find(t => t.paper_id === paperId)
      if (tab) {
        tab.session_id = sessionId
        this.schedulePersist()
      }
    },
    setView(view: WorkspaceState['view']) {
      this.view = view
      this.schedulePersist()
    },
    setLayout(partial: Partial<Layout>) {
      Object.assign(this.layout, partial)
      this.schedulePersist()
    },
    schedulePersist() {
      if (persistTimer) clearTimeout(persistTimer)
      persistTimer = setTimeout(() => {
        persistTimer = null
        void this.persist()
      }, 500)
    },
    async persist() {
      try {
        await workbenchApi.saveState(this.workspaceId, this.snapshot)
        this.saveError = null
      } catch (e) {
        this.saveError = e instanceof Error ? e.message : '工作区保存失败'
      }
    },
  },
})
