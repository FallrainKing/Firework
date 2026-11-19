/** One Markdown pipeline for documents, reports, translations and agent answers. */
import { Marked } from 'marked'
import DOMPurify from 'dompurify'

const parser = new Marked({ gfm: true, breaks: false, async: false })
const text = (source: string) => source.replace(/^[\u200B-\u200F\uFEFF]+/, '')

/** Marked's token tree, for document structure/TOC consumers; never HTML. */
export function parseMarkdown(source: string) {
  return parser.lexer(text(source))
}

/** Marked parses Markdown; DOMPurify and URL rules define display permissions. */
export function renderMarkdown(source: string): string {
  const clean = DOMPurify.sanitize(parser.parse(text(source), { async: false }), {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'form', 'button', 'textarea', 'select', 'iframe', 'object', 'embed', 'video', 'audio'],
    FORBID_ATTR: ['style', 'srcset', 'formaction', 'autofocus'],
  })
  const template = document.createElement('template')
  template.innerHTML = clean
  for (const el of template.content.querySelectorAll('a[href],img[src]')) {
    const attr = el.tagName === 'A' ? 'href' : 'src'
    const value = el.getAttribute(attr) || ''
    let allowed = false
    try {
      const url = new URL(value, window.location.href)
      allowed = ['http:', 'https:'].includes(url.protocol) || (attr === 'href' && url.protocol === 'mailto:')
    } catch { /* Invalid links stay inert. */ }
    if (!allowed) el.removeAttribute(attr)
    if (el.tagName === 'A' && allowed && !value.startsWith('#')) {
      el.setAttribute('target', '_blank')
      el.setAttribute('rel', 'noopener noreferrer')
    }
    if (el.tagName === 'IMG') { el.setAttribute('loading', 'lazy'); el.setAttribute('alt', el.getAttribute('alt') || '文档图片') }
  }
  // GFM task lists are display-only; arbitrary HTML inputs never become forms.
  for (const input of template.content.querySelectorAll('input')) {
    if (input.type !== 'checkbox') input.remove()
    else { input.disabled = true; input.removeAttribute('name'); input.removeAttribute('id') }
  }
  return template.innerHTML
}

/** Preserve the legacy HTMLElement contract without keeping a second parser. */
export function renderMarkdownElement(source: string): HTMLElement {
  const el = document.createElement('div')
  el.className = 'md markdown-content'
  el.innerHTML = renderMarkdown(source)
  return el
}
