import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkbenchStore } from '@/stores/workbench'

export type MobileMode = 'left' | 'pdf' | 'chat'
export type Side = 'left' | 'right'

const clampWidth = (v: number) => Math.max(140, Math.min(600, Math.round(v)))

// 对照旧 reader/layout.js：拖动/键盘 ±20/收起；持久化改经工作区 store（后端 Layout 140–600）。
export function useReaderLayout() {
  const wb = useWorkbenchStore()
  const { layout } = storeToRefs(wb)
  const mobileMode = ref<MobileMode>('pdf')

  function widthKey(side: Side): 'left_width' | 'right_width' {
    return side === 'left' ? 'left_width' : 'right_width'
  }

  function nudge(side: Side, delta: number) {
    const key = widthKey(side)
    wb.setLayout({ [key]: clampWidth(wb.layout[key] + delta) })
  }

  function toggle(side: Side) {
    if (side === 'left') wb.setLayout({ left_hidden: !wb.layout.left_hidden })
    else wb.setLayout({ right_hidden: !wb.layout.right_hidden })
  }

  function startDrag(side: Side, e: PointerEvent, separator: HTMLElement, currentWidth: number) {
    if (e.button !== 0) return
    const startX = e.clientX
    const sign = side === 'left' ? 1 : -1
    separator.setPointerCapture(e.pointerId)
    const move = (ev: PointerEvent) => {
      const delta = (ev.clientX - startX) * sign
      wb.setLayout({ [widthKey(side)]: clampWidth(currentWidth + delta) })
    }
    const finish = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', finish)
      window.removeEventListener('pointercancel', finish)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
    e.preventDefault()
  }

  function onResizerKey(side: Side, e: KeyboardEvent) {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    const sign = side === 'left' ? 1 : -1
    nudge(side, (e.key === 'ArrowRight' ? 20 : -20) * sign)
  }

  function setMobile(name: MobileMode) {
    mobileMode.value = name
  }

  return { layout, mobileMode, nudge, toggle, startDrag, onResizerKey, setMobile }
}
