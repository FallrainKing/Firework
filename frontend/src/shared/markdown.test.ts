import { describe, expect, it } from 'vitest'
import { parseMarkdown, renderMarkdown, renderMarkdownElement } from './markdown'

describe('unified Marked renderer', () => {
  it('renders headings, nested lists, tables, blockquotes and fenced code', () => {
    const html = renderMarkdown('# 标题\n\n> 引用\n\n- 外层\n  - 内层\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n```python\nprint("ok")\n```')
    for (const tag of ['<h1>','<blockquote>','<ul>','<table>','<pre>','language-python']) expect(html).toContain(tag)
    expect(parseMarkdown('# 文档')[0]).toMatchObject({ type: 'heading', depth: 1, text: '文档' })
  })
  it('preserves the HTMLElement compatibility contract', () => {
    const element = renderMarkdownElement('**重点**')
    expect(element).toBeInstanceOf(HTMLElement)
    expect(element.innerHTML).toContain('<strong>重点</strong>')
  })
  it('strips scripts, events, unsafe URLs, SVG and active forms', () => {
    const html = renderMarkdown('<script>alert(1)</script>\n\n<img src="x" onerror="alert(1)">\n\n[危险](javascript:alert%281%29)\n\n<svg onload="alert(1)"></svg><form><input autofocus name="secret"><button>提交</button></form>')
    const el = document.createElement('div'); el.innerHTML = html
    expect(el.querySelector('script,svg,form,button,input:not([type="checkbox"])')).toBeNull()
    expect(html).not.toMatch(/onerror|onload|javascript:|autofocus/)
  })
  it('keeps display-only task lists and safe images and links', () => {
    const el = renderMarkdownElement('- [x] 完成\n- [ ] 待办\n\n[来源](https://example.com/paper)\n\n![图](https://example.com/figure.png)')
    expect(el.querySelectorAll('input[disabled]')).toHaveLength(2)
    expect(el.querySelector('a')?.rel).toBe('noopener noreferrer')
    expect(el.querySelector('img')?.getAttribute('loading')).toBe('lazy')
  })
  it('does not parse inline HTML inside code or corrupt escaped pipes', () => {
    const html = renderMarkdown('`<script>safe</script>`\n\n| 论文 | 值 |\n| --- | --- |\n| P1\\|3 | 2 |')
    expect(html).toContain('&lt;script&gt;')
    expect(html).toContain('P1|3')
  })
  it('supports BOM-prefixed documents and repeated rendering without state leakage', () => {
    expect(renderMarkdown('\uFEFF# 标题')).toContain('<h1>标题</h1>')
    renderMarkdown('`first`')
    expect(renderMarkdown('`second`')).not.toContain('first')
  })
})
