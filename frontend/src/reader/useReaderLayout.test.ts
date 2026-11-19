import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReaderLayout } from './useReaderLayout'
import { useWorkbenchStore } from '@/stores/workbench'
import { workbenchApi } from '@/api/workbench'

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.spyOn(workbenchApi, 'saveState').mockImplementation(async (_id, s) => s)
})

describe('useReaderLayout', () => {
  it('nudge clamps width to 140-600 and persists via store', () => {
    const wb = useWorkbenchStore()
    const { nudge } = useReaderLayout()
    nudge('left', 1000)
    expect(wb.layout.left_width).toBe(600)
    nudge('left', -1000)
    expect(wb.layout.left_width).toBe(140)
    nudge('right', 50)
    expect(wb.layout.right_width).toBe(390)
  })

  it('toggle flips hidden flags', () => {
    const wb = useWorkbenchStore()
    const { toggle } = useReaderLayout()
    toggle('left')
    expect(wb.layout.left_hidden).toBe(true)
    toggle('left')
    expect(wb.layout.left_hidden).toBe(false)
    toggle('right')
    expect(wb.layout.right_hidden).toBe(true)
  })

  it('drag updates width with side-specific sign and clamps', () => {
    const wb = useWorkbenchStore()
    const { startDrag } = useReaderLayout()
    const target = document.createElement('div')
    target.setPointerCapture = vi.fn()
    // jsdom 无 PointerEvent，用 MouseEvent 携带 pointerId 模拟。
    const pe = (type: string, clientX: number, pointerId = 1) => Object.assign(new MouseEvent(type, { button: 0, clientX }), { pointerId })
    startDrag('left', pe('pointerdown', 100) as never, target, 235)
    window.dispatchEvent(pe('pointermove', 180))
    expect(wb.layout.left_width).toBe(315)
    window.dispatchEvent(pe('pointerup', 180))
    // 右栏方向相反
    startDrag('right', pe('pointerdown', 100, 2) as never, target, 340)
    window.dispatchEvent(pe('pointermove', 150, 2))
    expect(wb.layout.right_width).toBe(290)
    window.dispatchEvent(pe('pointerup', 150, 2))
  })

  it('restored layout remains reactive after replacing the workspace layout', () => {
    const wb = useWorkbenchStore()
    const { layout, toggle } = useReaderLayout()
    wb.layout = { left_width: 310, right_width: 410, left_hidden: false, right_hidden: true }
    expect(layout.value.left_width).toBe(310)
    toggle('right')
    expect(layout.value.right_hidden).toBe(false)
  })

  it('mobile mode switches partitions' , () => {
    const { mobileMode, setMobile } = useReaderLayout()
    expect(mobileMode.value).toBe('pdf')
    setMobile('chat')
    expect(mobileMode.value).toBe('chat')
  })
})

describe('useReaderLayout presets and drag persistence', () => {
  it('applies named layout presets', () => {
    const wb = useWorkbenchStore()
    const { applyPreset } = useReaderLayout()
    applyPreset('reading')
    expect(wb.layout).toMatchObject({ left_width: 360, right_width: 180 })
    applyPreset('discussion')
    expect(wb.layout).toMatchObject({ left_width: 150, right_width: 500 })
    applyPreset('default')
    expect(wb.layout).toMatchObject({ left_width: 235, right_width: 340 })
  })

  it('persists drag once on pointerup instead of every move', async () => {
    const save = vi.mocked(workbenchApi.saveState)
    save.mockClear()
    const wb = useWorkbenchStore()
    const { startDrag } = useReaderLayout()
    const target = document.createElement('div')
    target.setPointerCapture = vi.fn()
    const pe = (type: string, clientX: number, pointerId = 1) => Object.assign(new MouseEvent(type, { button: 0, clientX }), { pointerId })
    startDrag('left', pe('pointerdown', 100) as never, target, 235)
    window.dispatchEvent(pe('pointermove', 140))
    window.dispatchEvent(pe('pointermove', 180))
    expect(wb.layout.left_width).toBe(315)
    expect(save).not.toHaveBeenCalled()
    window.dispatchEvent(pe('pointerup', 180))
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(save).toHaveBeenCalledTimes(1)
  })
})
