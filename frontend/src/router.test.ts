import { describe, it, expect, vi } from 'vitest'
const auth = vi.hoisted(() => ({ value: { authenticated: false, account: { role: 'admin' } } }))
vi.mock('@/auth/session', () => ({ authState: auth, refreshAuth: vi.fn().mockResolvedValue(undefined) }))
vi.mock('@/views/LoginView.vue', () => ({ default: {} }))
vi.mock('@/views/RegisterView.vue', () => ({ default: {} }))
vi.mock('@/views/WorkbenchView.vue', () => ({ default: {} }))
vi.mock('@/views/ZoteroView.vue', () => ({ default: {} }))
vi.mock('@/views/AccountsView.vue', () => ({ default: {} }))
import { router } from './router'

describe('Hash router and authentication', () => {
  it('uses hash links and preserves a protected deep link at login', async () => {
    await router.push('/reader/19?session_id=7')
    expect(router.currentRoute.value.path).toBe('/login')
    expect(router.currentRoute.value.query.redirect).toBe('/reader/19?session_id=7')
    expect(window.location.hash).toContain('#/login')
    expect(router.resolve('/integrations/zotero').href).toBe('#/integrations/zotero')
  })
  it('allows the same reader route after authentication', async () => {
    auth.value.authenticated = true
    await router.push('/reader/19?session_id=7')
    expect(window.location.hash).toBe('#/reader/19?session_id=7')
    expect(router.currentRoute.value.params.paperId).toBe('19')
  })
  it('keeps account management restricted', async () => {
    auth.value.account.role = 'user'
    await router.push('/accounts')
    expect(router.currentRoute.value.path).toBe('/')
  })
})
