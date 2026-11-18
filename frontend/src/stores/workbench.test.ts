import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkbenchStore } from './workbench'
import { workbenchApi } from '@/api/workbench'
import type { WorkspaceState } from '@/api/types'

const fixture: WorkspaceState = {
  layout: { left_width: 300, right_width: 380, left_hidden: false, right_hidden: true },
  tabs: [{ paper_id: 1, session_id: 10 }, { paper_id: 2, session_id: null }],
  active_paper_id: 2,
  view: 'read',
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.useFakeTimers()
  vi.spyOn(workbenchApi, 'getState').mockResolvedValue(fixture)
  vi.spyOn(workbenchApi, 'saveState').mockImplementation(async (_id, s) => s)
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('workbench store', () => {
  it('load restores tabs, layout, active and view', async () => {
    const wb = useWorkbenchStore()
    await wb.load()
    expect(wb.tabs).toEqual(fixture.tabs)
    expect(wb.layout).toEqual(fixture.layout)
    expect(wb.activePaperId).toBe(2)
    expect(wb.view).toBe('read')
    expect(workbenchApi.getState).toHaveBeenCalledWith(wb.workspaceId)
    expect(wb.workspaceId).toMatch(/^[a-f0-9]{32}$/)
  })

  it('workspace id persists across store instances', async () => {
    const first = useWorkbenchStore()
    await first.load()
    setActivePinia(createPinia())
    const second = useWorkbenchStore()
    expect(second.workspaceId).toBe(first.workspaceId)
  })

  it('openPaper reuses existing tab and rebinds explicit session', async () => {
    const wb = useWorkbenchStore()
    await wb.load()
    wb.openPaper(1, 99)
    expect(wb.tabs).toHaveLength(2)
    expect(wb.tabs[0].session_id).toBe(99) // explicit session rebinds (legacy parity)
    expect(wb.activePaperId).toBe(1)
    wb.openPaper(1)
    expect(wb.tabs[0].session_id).toBe(99) // no session arg keeps binding
  })

  it('openPaper appends new tab and enforces cap 20', async () => {
    const wb = useWorkbenchStore()
    await wb.load()
    wb.openPaper(3)
    expect(wb.tabs).toHaveLength(3)
    expect(wb.tabs[2]).toEqual({ paper_id: 3, session_id: null })
    for (let i = 4; i <= 20; i++) wb.openPaper(i)
    expect(wb.tabs).toHaveLength(20)
    expect(() => wb.openPaper(21)).toThrow('标签')
  })

  it('closeTab removes view only and falls back active', async () => {
    const wb = useWorkbenchStore()
    await wb.load()
    wb.closeTab(2)
    expect(wb.tabs.map(t => t.paper_id)).toEqual([1])
    expect(wb.activePaperId).toBe(1)
    wb.closeTab(1)
    expect(wb.activePaperId).toBeNull()
  })

  it('persists snapshot shape after debounce, merging rapid changes', async () => {
    const wb = useWorkbenchStore()
    await wb.load()
    wb.openPaper(3)
    wb.setLayout({ left_width: 280 })
    wb.setView('compare')
    expect(workbenchApi.saveState).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(500)
    expect(workbenchApi.saveState).toHaveBeenCalledTimes(1)
    const [id, snapshot] = vi.mocked(workbenchApi.saveState).mock.calls[0]
    expect(id).toBe(wb.workspaceId)
    expect(snapshot).toEqual({
      layout: { left_width: 280, right_width: 380, left_hidden: false, right_hidden: true },
      tabs: [...fixture.tabs, { paper_id: 3, session_id: null }],
      active_paper_id: 3,
      view: 'compare',
    })
  })

  it('setTabSession updates binding (bridge reader-session)', async () => {
    const wb = useWorkbenchStore()
    await wb.load()
    wb.setTabSession(2, 42)
    expect(wb.tabs[1].session_id).toBe(42)
  })
})
