import { describe, it, expect } from 'vitest'
import { appHref, legacyHashUrl, loginPath, safeReturnTarget } from './navigation'

describe('Hash page addresses and old bookmarks', () => {
  it.each([
    ['/', '', '', '/#/'],
    ['/reader/19', '?session_id=7', '#page=2', '/#/reader/19?session_id=7#page=2'],
    ['/', '?paper_id=19&session_id=7', '', '/#/?paper_id=19&session_id=7'],
    ['/integrations/zotero', '', '', '/#/integrations/zotero'],
    ['/login', '?redirect=%2Freader%2F19', '', '/#/login?redirect=%2Freader%2F19'],
    ['/', '', '#/reader/19?session_id=7', null],
    ['/reader/19', '', '#/accounts', '/#/accounts'],
    ['/api/reader/papers/19/file', '', '', null],
    ['/downloads/plugin.xpi', '', '', null],
  ])('migrates %s without changing file/API paths', (pathname, search, hash, expected) => {
    expect(legacyHashUrl({ pathname, search, hash })).toBe(expected)
  })
  it('preserves the reader and session through login', () => {
    const target = '/reader/19?session_id=7#page=2'
    const login = loginPath(target)
    expect(new URLSearchParams(login.split('?')[1]).get('redirect')).toBe(target)
    expect(appHref(safeReturnTarget(target))).toBe('/#/reader/19?session_id=7#page=2')
  })
  it.each(['https://evil.example', '//evil.example', '/%2fevil.example', '/\\evil', '/reader/19?x=%0a', '/login?redirect=/login', '/register', '/api/private', ['accounts'], '/reader/%ZZ'])('rejects unsafe return target %s', value => {
    expect(safeReturnTarget(value)).toBe('/')
  })
})
