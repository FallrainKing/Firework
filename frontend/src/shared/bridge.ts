// 与现有 reader.html 的 postMessage 协议（对照旧 workbench/app.js 核对）。
// 父→子：save-reader / reader-layout / refresh-reader-draft
// 子→父：reader-saved / reader-ready / reader-session / reader-layout-change /
//        open-paper / open-import / navigate-workbench
import { uid32 } from '@/api/client'
import type { Layout } from '@/api/types'

export interface BridgeHandlers {
  onSaved?: (requestId: string) => void
  onReady?: (frame: HTMLIFrameElement, paperId: number, sessionId: number) => void
  onSession?: (paperId: number, sessionId: number) => void
  onLayoutChange?: (layout: Layout) => void
  onOpenPaper?: (paperId: number, sessionId?: number) => void
  onOpenImport?: (paperId?: number) => void
  onNavigate?: (view: string) => void
  onLibraryUpdated?: () => void
}

interface Pending {
  source: Window | null
  finish: (ok: boolean) => void
}

const pending = new Map<string, Pending>()

export function attachBridge(getFrames: () => HTMLIFrameElement[], handlers: BridgeHandlers): () => void {
  const listener = (event: MessageEvent) => {
    if (event.origin !== location.origin) return
    const frame = getFrames().find(f => f.contentWindow === event.source)
    if (!frame) return
    const m = (event.data ?? {}) as Record<string, unknown>
    switch (m.type) {
      case 'reader-saved': {
        const p = pending.get(m.request_id as string)
        if (p && p.source === event.source) {
          pending.delete(m.request_id as string)
          p.finish(true)
        }
        handlers.onSaved?.(m.request_id as string)
        break
      }
      case 'reader-ready':
        handlers.onReady?.(frame, Number(m.paper_id), Number(m.session_id))
        break
      case 'reader-session':
        handlers.onSession?.(Number(m.paper_id), Number(m.session_id))
        break
      case 'reader-layout-change':
        handlers.onLayoutChange?.(m.layout as Layout)
        break
      case 'open-paper':
        handlers.onOpenPaper?.(Number(m.paper_id), m.session_id !== undefined ? Number(m.session_id) : undefined)
        break
      case 'open-import':
        handlers.onOpenImport?.(m.paper_id !== undefined ? Number(m.paper_id) : undefined)
        break
      case 'navigate-workbench':
        handlers.onNavigate?.(String(m.view))
        break
      case 'library-updated':
        handlers.onLibraryUpdated?.()
        break
    }
  }
  window.addEventListener('message', listener)
  return () => window.removeEventListener('message', listener)
}

export function requestSave(frame: HTMLIFrameElement, timeoutMs = 2000): Promise<boolean> {
  return new Promise(resolve => {
    const requestId = uid32()
    const timer = setTimeout(() => {
      if (pending.delete(requestId)) resolve(false)
    }, timeoutMs)
    pending.set(requestId, {
      source: frame.contentWindow,
      finish: ok => {
        clearTimeout(timer)
        resolve(ok)
      },
    })
    frame.contentWindow?.postMessage({ type: 'save-reader', request_id: requestId }, location.origin)
  })
}

export function sendLayout(frame: HTMLIFrameElement, layout: Layout): void {
  frame.contentWindow?.postMessage({ type: 'reader-layout', layout }, location.origin)
}

export function refreshDraft(frame: HTMLIFrameElement): void {
  frame.contentWindow?.postMessage({ type: 'refresh-reader-draft' }, location.origin)
}
