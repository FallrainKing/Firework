import { beforeAll, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// 加载真实 public/md.js（与生产同源），钉住 mdRender 返回 HTMLElement 的契约。
beforeAll(() => {
  const src = readFileSync(resolve(__dirname, '../../public/md.js'), 'utf8')
  window.eval(src)
})

describe('real md.js contract', () => {
  it('mdRender returns an HTMLElement with rendered markup', () => {
    const out = window.mdRender!('**重点**')
    expect(out).toBeInstanceOf(HTMLElement)
    expect(out.innerHTML).toContain('<strong>')
  })

  it('escapes raw html input', () => {
    const out = window.mdRender!('<script>alert(1)</script>')
    expect(out.innerHTML).not.toContain('<script>')
  })

  it('innerHTML string is safe for v-html (no [object] coercion)', () => {
    const html = window.mdRender!('# 标题').innerHTML
    expect(typeof html).toBe('string')
    expect(html).not.toContain('[object')
    expect(html).toContain('<h1')
  })
})
