import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const pdfState = {
  numPages: 3,
  pending: [] as Array<{ resolve: () => void }>,
  autoResolve: true,
}

vi.mock('/vendor/pdfjs/legacy/build/pdf.mjs', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument: () => ({
    promise: Promise.resolve({
      numPages: pdfState.numPages,
      getPage: (n: number) => Promise.resolve({
        getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }),
        render: () => {
          if (pdfState.autoResolve) return { promise: Promise.resolve(), cancel: () => {} }
          let resolve!: () => void
          const promise = new Promise<void>(r => { resolve = r })
          pdfState.pending.push({ resolve })
          return { promise, cancel: () => {} }
        },
        streamTextContent: () => ({}),
      }),
      destroy: () => {},
    }),
  }),
  TextLayer: class { render() { return Promise.resolve() } cancel() {} },
}))

import { PDFReader } from './pdf-engine'

class IOStub {
  static instances: IOStub[] = []
  constructor(public cb: IntersectionObserverCallback, public opts?: IntersectionObserverInit) { IOStub.instances.push(this) }
  observe() {} disconnect() {} unobserve() {} takeRecords() { return [] }
}
class ROStub { observe() {} disconnect() {} unobserve() {} }

const info = { paper_id: 1, title: 'T', file_version: 'v1', page_count: 3, width: 600, height: 800, pdf_url: '/api/reader/papers/1/file' }

let root: HTMLElement
let pages: HTMLElement

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', IOStub)
  vi.stubGlobal('ResizeObserver', ROStub)
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as never)
  IOStub.instances = []
  pdfState.numPages = 3
  pdfState.pending = []
  pdfState.autoResolve = true
  root = document.createElement('div')
  pages = document.createElement('div')
  root.append(pages)
  document.body.append(root)
  Object.defineProperty(root, 'clientWidth', { value: 800, configurable: true })
  root.scrollTo = vi.fn() as never
})

afterEach(() => {
  root.remove()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function makeReader() {
  const reader = new PDFReader(root, pages)
  await reader.load(info)
  return reader
}

describe('PDFReader engine', () => {
  it('load creates one holder per page', async () => {
    const reader = await makeReader()
    expect(pages.querySelectorAll('.pdf-page')).toHaveLength(3)
    reader.destroy()
  })

  it('keeps canvas CSS dimensions aligned with the PDF page on high-DPI screens', async () => {
    vi.stubGlobal('devicePixelRatio', 2)
    const reader = await makeReader()
    reader.enqueue(1)
    await new Promise(r => setTimeout(r, 0))
    const canvas = pages.querySelector('canvas')!
    expect(canvas.style.width).toBe(pages.querySelector<HTMLElement>('.pdf-page')!.style.width)
    expect(canvas.width).toBe(Math.ceil(parseFloat(canvas.style.width) * 1.5))
    expect(canvas.style.height).toBe(pages.querySelector<HTMLElement>('.pdf-page')!.style.height)
    reader.destroy()
  })

  it('render queue runs at most 2 concurrent renders' , async () => {
    pdfState.autoResolve = false
    const reader = await makeReader()
    reader.enqueue(1)
    reader.enqueue(2)
    reader.enqueue(3)
    await Promise.resolve()
    expect(pdfState.pending).toHaveLength(2)
    pdfState.pending.shift()!.resolve()
    await new Promise(r => setTimeout(r, 0))
    expect(pdfState.pending).toHaveLength(2) // 第 3 个补位
    reader.destroy()
  })

  it('generation guard drops stale renders after relayout', async () => {
    pdfState.autoResolve = false
    const reader = await makeReader()
    const rendered: number[] = []
    reader.addEventListener('rendered', e => rendered.push((e as CustomEvent).detail.page))
    reader.enqueue(1)
    await Promise.resolve()
    reader.setZoom('1.5') // generation++
    pdfState.pending.shift()!.resolve()
    await new Promise(r => setTimeout(r, 0))
    expect(rendered).not.toContain(1)
    reader.destroy()
  })

  it('evict clears ready pages far from current but keeps selection page', async () => {
    pdfState.numPages = 12
    const reader = await makeReader()
    reader.currentPage = 1
    const holders = Array.from(pages.querySelectorAll('.pdf-page')) as HTMLElement[]
    holders.forEach(h => { h.dataset.state = 'ready'; h.prepend(document.createElement('canvas')) })
    // 选区在第 10 页 → 不驱逐
    const sel = { anchorNode: holders[9].firstChild, isCollapsed: false }
    vi.spyOn(window, 'getSelection').mockReturnValue(sel as never)
    ;(reader as never as { evict: () => void }).evict()
    expect(holders[9].dataset.state).toBe('ready')
    expect(holders[11].dataset.state).toBe('idle') // 第 12 页远离当前页
    expect(holders[1].dataset.state).toBe('ready') // ±5 页内保留
    reader.destroy()
  })

  it('jump clamps page number and emits page event', async () => {
    const reader = await makeReader()
    const events: number[] = []
    reader.addEventListener('page', e => events.push((e as CustomEvent).detail))
    reader.jump(99)
    expect(reader.currentPage).toBe(3)
    reader.jump(0)
    expect(reader.currentPage).toBe(1)
    expect(events).toEqual([3, 1])
    reader.destroy()
  })
})
