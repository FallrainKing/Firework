// PDF 引擎：自 app/web/reader/pdf-view.js 行为保持地移植。
// 变更点：构造器接收 root/pages 元素（替代全局 id）；新增 destroy()；TS 化；
// PDF.js 改为运行时动态加载（@vite-ignore，绝对路径由服务端 /vendor 提供）。
// 渲染管线（generation 守卫、并发 2 队列、±5 页驱逐、选区/画笔/橡皮）逻辑不变。

let pdfjsPromise: Promise<any> | null = null
function loadPdfjs(): Promise<any> {
  if (!pdfjsPromise) {
    // 变量 specifier + @vite-ignore：保持运行时绝对路径 import，不被构建器解析。
    const url = '/vendor/pdfjs/legacy/build/pdf.mjs'
    pdfjsPromise = import(/* @vite-ignore */ url).then(m => {
      m.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/legacy/build/pdf.worker.mjs'
      return m
    })
  }
  return pdfjsPromise
}

const NS = 'http://www.w3.org/2000/svg'
const svg = (tag: string, attrs: Record<string, unknown> = {}) => {
  const n = document.createElementNS(NS, tag)
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v))
  return n
}
const el = (tag: string, text?: string, cls?: string) => {
  const n = document.createElement(tag)
  if (text != null) n.textContent = text
  if (cls) n.className = cls
  return n
}
const clamp = (n: number) => Math.max(0, Math.min(1, n))

export interface PdfDocInfo {
  paper_id: number
  title: string
  file_version: string
  page_count: number
  width: number
  height: number
  pdf_url: string
}

export interface EngineAnnotation {
  id: string
  page: number
  file_version: string
  kind: string
  color: string
  origin?: string
  guide_item_id?: string | null
  rects?: number[][]
  points?: number[][]
}

export class PDFReader extends EventTarget {
  root: HTMLElement
  pages: HTMLElement
  currentPage = 1
  zoom = 'fit'
  mode = 'select'
  color = '#f5d76e'
  annotations: EngineAnnotation[] = []
  info!: PdfDocInfo
  pdf: any = null
  private pdfjs: any = null
  scale = 1
  holders: HTMLElement[] = []
  private tasks = new Map<number, any>()
  private queue: Array<{ number: number; generation: number }> = []
  private active = 0
  private generation = 0
  private scrollFrame: number | null = null
  private resizeTimer: ReturnType<typeof setTimeout> | null = null
  private observer: IntersectionObserver | null = null
  private resizeObserver: ResizeObserver
  private abort = new AbortController()

  constructor(root: HTMLElement, pages: HTMLElement) {
    super()
    this.root = root
    this.pages = pages
    const signal = this.abort.signal
    this.root.addEventListener('scroll', () => {
      if (!this.scrollFrame) this.scrollFrame = requestAnimationFrame(() => { this.scrollFrame = null; this.trackPage() })
    }, { signal })
    this.root.addEventListener('pointerup', e => {
      if (this.mode === 'select') setTimeout(() => this.captureSelection(e), 20)
    }, { signal })
    this.resizeObserver = new ResizeObserver(() => {
      if (this.resizeTimer) clearTimeout(this.resizeTimer)
      if (this.zoom === 'fit' && this.root.clientWidth > 120) this.resizeTimer = setTimeout(() => this.layout(), 150)
    })
    this.resizeObserver.observe(this.root)
  }

  destroy() {
    this.abort.abort()
    this.resizeObserver.disconnect()
    this.observer?.disconnect()
    for (const task of this.tasks.values()) { task.render?.cancel(); task.text?.cancel() }
    this.tasks.clear()
    this.queue = []
    if (this.resizeTimer) clearTimeout(this.resizeTimer)
    this.pdf?.destroy?.()
  }

  emit(type: string, detail: unknown) { this.dispatchEvent(new CustomEvent(type, { detail })) }

  async load(info: PdfDocInfo, position: { page?: number; zoom?: string } = {}) {
    this.info = info
    this.currentPage = position.page || 1
    this.zoom = position.zoom || 'fit'
    const pdfjs = await loadPdfjs()
    this.pdfjs = pdfjs
    this.pdf = await pdfjs.getDocument({ url: info.pdf_url, cMapUrl: '/vendor/pdfjs/cmaps/', cMapPacked: true, standardFontDataUrl: '/vendor/pdfjs/standard_fonts/', wasmUrl: '/vendor/pdfjs/wasm/', isEvalSupported: false }).promise
    this.layout()
  }

  layout() {
    if (!this.pdf || this.root.clientWidth < 120) return
    const keep = this.currentPage
    this.generation++
    for (const task of this.tasks.values()) { task.render?.cancel(); task.text?.cancel() }
    this.tasks.clear()
    this.observer?.disconnect()
    this.queue = []
    this.active = 0
    this.pages.replaceChildren()
    this.scale = this.zoom === 'fit' ? Math.max(0.3, (this.root.clientWidth - 38) / this.info.width) : Number(this.zoom)
    const width = this.info.width * this.scale, height = this.info.height * this.scale
    this.holders = []
    for (let n = 1; n <= this.pdf.numPages; n++) {
      const p = el('div', undefined, 'pdf-page') as HTMLElement
      p.dataset.page = String(n)
      p.style.width = width + 'px'
      p.style.height = height + 'px'
      p.style.setProperty('--scale-factor', String(this.scale))
      p.style.setProperty('--total-scale-factor', String(this.scale))
      p.append(el('span', '第 ' + n + ' 页 · 载入中…', 'page-loading'))
      p.dataset.state = 'idle'
      this.bindInk(p)
      this.pages.append(p)
      this.holders.push(p)
      this.modeOn(p)
    }
    this.observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) this.enqueue(Number((entry.target as HTMLElement).dataset.page))
    }, { root: this.root, rootMargin: '700px 0px' })
    this.holders.forEach(p => this.observer!.observe(p))
    this.jump(keep)
    this.renderAnnotations()
    this.emit('zoom', this.zoom)
  }

  enqueue(number: number) {
    const holder = this.holders[number - 1]
    if (!holder || holder.dataset.state !== 'idle') return
    holder.dataset.state = 'queued'
    this.queue.push({ number, generation: this.generation })
    this.pump()
  }

  private pump() {
    while (this.active < 2 && this.queue.length) {
      const item = this.queue.shift()!
      if (item.generation !== this.generation) continue
      this.active++
      this.renderPage(item.number, item.generation).finally(() => {
        if (item.generation === this.generation) { this.active--; this.pump() }
      })
    }
  }

  private async renderPage(number: number, generation: number) {
    const holder = this.holders[number - 1]
    const task: any = {}
    this.tasks.set(number, task)
    try {
      const page = await this.pdf.getPage(number)
      if (generation !== this.generation) return
      const viewport = page.getViewport({ scale: this.scale })
      holder.style.width = viewport.width + 'px'
      holder.style.height = viewport.height + 'px'
      const canvas = el('canvas') as HTMLCanvasElement
      canvas.setAttribute('aria-label', `论文第 ${number} 页`)
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5)
      canvas.width = Math.ceil(viewport.width * ratio)
      canvas.height = Math.ceil(viewport.height * ratio)
      // Backing pixels improve sharpness; CSS pixels must match text/annotations.
      canvas.style.width = viewport.width + 'px'
      canvas.style.height = viewport.height + 'px'
      holder.prepend(canvas)
      task.render = page.render({ canvasContext: canvas.getContext('2d'), viewport, transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0] })
      await task.render.promise
      if (generation !== this.generation) return
      const text = el('div', undefined, 'textLayer')
      holder.append(text)
      task.text = new this.pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: text, viewport })
      await task.text.render()
      if (generation !== this.generation) return
      holder.querySelector('.page-loading')?.remove()
      holder.dataset.state = 'ready'
      this.paintPage(holder)
      this.evict()
      this.emit('rendered', { page: number })
    } catch (e: any) {
      if (generation === this.generation && e.name !== 'RenderingCancelledException' && e.name !== 'AbortException') {
        holder.dataset.state = 'error'
        const label = holder.querySelector('.page-loading')
        if (label) label.textContent = '本页暂未完成渲染，请调整缩放重试。'
        console.error('PDF page rendering failed', e.name, e.message)
      }
    } finally {
      if (generation === this.generation) this.tasks.delete(number)
    }
  }

  private evict() {
    for (const p of this.holders) {
      if (p.dataset.state !== 'ready' || Math.abs(Number(p.dataset.page) - this.currentPage) <= 5) continue
      const selection = window.getSelection()
      if (selection?.anchorNode && p.contains(selection.anchorNode)) continue
      const canvas = p.querySelector('canvas')
      if (canvas) { canvas.width = 0; canvas.height = 0 }
      p.replaceChildren(el('span', '滚动至本页加载原文', 'page-loading'))
      p.dataset.state = 'idle'
      this.paintPage(p)
    }
  }

  private trackPage() {
    if (!this.holders?.length) return
    const top = this.root.getBoundingClientRect().top + 70
    let selected = this.currentPage, best = Infinity
    for (const holder of this.holders) {
      const r = holder.getBoundingClientRect()
      if (r.bottom > top && r.top < this.root.getBoundingClientRect().bottom) {
        const distance = Math.abs(r.top - top)
        if (distance < best) { best = distance; selected = Number(holder.dataset.page) }
      }
    }
    if (selected !== this.currentPage) { this.currentPage = selected; this.emit('page', selected) }
  }

  jump(number: number, flash = false) {
    number = Math.max(1, Math.min(this.info.page_count, Number(number) || 1))
    this.currentPage = number
    const holder = this.holders?.[number - 1]
    if (!holder) return
    this.enqueue(number)
    const top = holder.getBoundingClientRect().top - this.root.getBoundingClientRect().top + this.root.scrollTop - 14
    this.root.scrollTo({ top })
    this.emit('page', number)
    if (flash) { holder.classList.add('flash'); setTimeout(() => holder.classList.remove('flash'), 1600) }
  }

  setZoom(value: string) { this.zoom = value; this.layout() }

  setMode(mode: string) {
    this.mode = mode
    this.holders?.forEach(p => this.modeOn(p))
    window.getSelection()?.removeAllRanges()
    this.emit('selection', null)
  }

  private modeOn(p: HTMLElement) {
    p.classList.toggle('pen-mode', this.mode === 'pen')
    p.classList.toggle('erase-mode', this.mode === 'erase')
  }

  setAnnotations(items: EngineAnnotation[]) { this.annotations = items; this.renderAnnotations() }
  renderAnnotations() { this.holders?.forEach(p => this.paintPage(p)) }

  private paintPage(holder: HTMLElement) {
    holder.querySelector('.annotation-overlay')?.remove()
    const overlay = svg('svg', { viewBox: '0 0 1 1', preserveAspectRatio: 'none', 'class': 'annotation-overlay' })
    for (const a of this.annotations.filter(a => a.page === Number(holder.dataset.page) && a.file_version === this.info.file_version)) {
      if (a.kind === 'ink') {
        overlay.append(svg('polyline', { points: (a.points ?? []).map(p => p.join(',')).join(' '), stroke: a.color, 'class': 'ink', 'data-annotation-id': a.id }))
      } else {
        for (const r of a.rects || []) overlay.append(svg('rect', { x: r[0], y: r[1], width: r[2], height: r[3], fill: a.color, 'class': a.origin==='ai'?'highlight ai-highlight':'highlight', 'data-annotation-id': a.id }))
      }
    }
    let markerIndex=0
    for(const a of this.annotations.filter(a=>a.origin==='ai'&&a.guide_item_id&&a.page===Number(holder.dataset.page)&&a.file_version===this.info.file_version)){
      const cy=Math.min(.96,Math.max(.035,(a.rects?.[0]?.[1]??(.07+markerIndex*.045))))
      const marker=svg('circle',{cx:.975,cy,r:.012,'class':'ai-marker','data-annotation-id':a.id,'role':'button','aria-label':'查看 AI 批注解释','tabindex':0})
      const activate=()=>this.emit('guide-annotation',a.guide_item_id)
      marker.addEventListener('click',e=>{if(this.mode==='erase')return;e.stopPropagation();activate()})
      marker.addEventListener('keydown',e=>{if((e as KeyboardEvent).key==='Enter'){e.preventDefault();activate()}})
      overlay.append(marker);markerIndex++
    }
    holder.append(overlay)
    this.modeOn(holder)
  }

  private captureSelection(_event: Event) {
    const selection = window.getSelection()
    if (!selection || selection.isCollapsed || !selection.rangeCount) { this.emit('selection', null); return }
    const anchor = selection.anchorNode?.nodeType === 1 ? selection.anchorNode as Element : selection.anchorNode?.parentElement
    const focus = selection.focusNode?.nodeType === 1 ? selection.focusNode as Element : selection.focusNode?.parentElement
    const page = anchor?.closest('.pdf-page')
    if (!page || page !== focus?.closest('.pdf-page')) { this.emit('selection', null); return }
    const quote = selection.toString().trim()
    if (!quote) return
    const bounds = page.getBoundingClientRect()
    const range = selection.getRangeAt(0)
    const rects: number[][] = []
    const seen = new Set<string>()
    for (const rect of range.getClientRects()) {
      const left = Math.max(rect.left, bounds.left), top = Math.max(rect.top, bounds.top), right = Math.min(rect.right, bounds.right), bottom = Math.min(rect.bottom, bounds.bottom)
      if (right - left < 1 || bottom - top < 1) continue
      const item = [clamp((left - bounds.left) / bounds.width), clamp((top - bounds.top) / bounds.height), clamp((right - left) / bounds.width), clamp((bottom - top) / bounds.height)]
      const key = item.map(n => n.toFixed(4)).join(',')
      if (!seen.has(key)) { rects.push(item); seen.add(key) }
    }
    const rangeRect = range.getBoundingClientRect()
    this.emit('selection', { paper_id: this.info.paper_id, page: Number((page as HTMLElement).dataset.page), file_version: this.info.file_version, quote: quote.slice(0, 4000), rects: rects.slice(0, 100), screen: { left: rangeRect.left, bottom: rangeRect.bottom, top: rangeRect.top } })
  }

  private bindInk(holder: HTMLElement) {
    let points: number[][] | null = null
    const pos = (e: PointerEvent) => {
      const r = holder.getBoundingClientRect()
      return [clamp((e.clientX - r.left) / r.width), clamp((e.clientY - r.top) / r.height)]
    }
    const signal = this.abort.signal
    holder.addEventListener('pointerdown', e => {
      if (this.mode === 'erase') {
        const target = (e.target as Element).closest?.('[data-annotation-id]')
        if (target) { e.preventDefault(); this.emit('erase', (target as HTMLElement).dataset.annotationId) }
        return
      }
      if (this.mode !== 'pen' || e.button !== 0) return
      e.preventDefault()
      points = [pos(e)]
      holder.setPointerCapture(e.pointerId)
      const line = svg('polyline', { 'class': 'ink live-ink', stroke: this.color, points: points[0].join(',') })
      holder.querySelector('.annotation-overlay')?.append(line)
    }, { signal })
    holder.addEventListener('pointermove', e => {
      if (!points || points.length >= 2000) return
      points.push(pos(e))
      holder.querySelector('.live-ink')?.setAttribute('points', points.map(p => p.join(',')).join(' '))
    }, { signal })
    const end = () => {
      if (!points) return
      const captured = points
      points = null
      if (captured.length > 1) this.emit('ink', { paper_id: this.info.paper_id, page: Number(holder.dataset.page), file_version: this.info.file_version, quote: '', rects: [], points: captured, kind: 'ink', color: this.color })
      else holder.querySelector('.live-ink')?.remove()
    }
    holder.addEventListener('pointerup', end, { signal })
    holder.addEventListener('pointercancel', () => { points = null; holder.querySelector('.live-ink')?.remove() }, { signal })
  }
}
