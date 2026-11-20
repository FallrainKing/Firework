// Browser page navigation is always rooted at /#/; API/file paths never use this helper.
export function safeReturnTarget(value: unknown): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return '/'
  let decoded: string
  try { decoded = decodeURIComponent(value) } catch { return '/' }
  if (/[\\\u0000-\u0020]/.test(decoded) || decoded.startsWith('//')) return '/'
  const path = value.split(/[?#]/, 1)[0]
  if (!/^\/(?:reader\/\d+|integrations\/zotero|accounts)?\/?$/.test(path)) return '/'
  return value
}

export function appHref(path = '/'): string { return '/#' + path }
export function replaceAppLocation(path: string): void { window.location.replace(appHref(path)) }
export function loginPath(returnTo: string): string {
  const target = safeReturnTarget(returnTo)
  return target === '/' ? '/login' : '/login?redirect=' + encodeURIComponent(target)
}

export function legacyHashUrl(location: Pick<Location, 'pathname' | 'search' | 'hash'>): string | null {
  const { pathname, search, hash } = location
  if (hash.startsWith('#/')) return pathname === '/' && !search ? null : '/' + hash
  if (!/^\/(?:login|register|accounts|integrations\/zotero|reader\/\d+)?\/?$/.test(pathname)) return null
  return appHref(pathname + search + hash)
}

export function migrateLegacyLocation(): void {
  const next = legacyHashUrl(window.location)
  if (next) window.history.replaceState(window.history.state, '', next)
}
