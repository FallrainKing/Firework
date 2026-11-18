import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { parseDeepLink } from './deeplink'
import { router as appRouter } from '@/router'

describe('deep links', () => {
  it('parses /reader/:paperId with session query', () => {
    expect(parseDeepLink({ params: { paperId: '5' }, query: { session_id: '9' } })).toEqual({ paperId: 5, sessionId: 9 })
  })

  it('parses legacy ?paper_id query', () => {
    expect(parseDeepLink({ params: {}, query: { paper_id: '3' } })).toEqual({ paperId: 3, sessionId: null })
  })

  it('returns null for invalid ids', () => {
    expect(parseDeepLink({ params: { paperId: 'abc' }, query: {} })).toBeNull()
    expect(parseDeepLink({ params: {}, query: {} })).toBeNull()
  })

  it('router matches /reader/1 and redirects unknown paths', async () => {
    const r = createRouter({
      history: createMemoryHistory(),
      routes: appRouter.getRoutes().map(x => ({ path: x.path, redirect: (x as { redirect?: unknown }).redirect as never, component: x.components?.default as never, name: x.name as never })),
    })
    await r.push('/reader/1')
    expect(r.currentRoute.value.matched.length).toBeGreaterThan(0)
    expect(r.currentRoute.value.params.paperId).toBe('1')
    await r.push('/some/unknown/path')
    expect(r.currentRoute.value.path).toBe('/')
  })
})
