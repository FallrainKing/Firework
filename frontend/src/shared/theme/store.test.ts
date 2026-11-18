import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useThemeStore } from './store'

describe('theme store', () => {
  beforeEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.theme
    setActivePinia(createPinia())
  })

  it('defaults to light', () => {
    const theme = useThemeStore()
    expect(theme.mode).toBe('light')
  })

  it('setMode applies dataset and persists', () => {
    const theme = useThemeStore()
    theme.setMode('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('research-theme')).toBe('dark')
  })

  it('restores persisted mode', () => {
    localStorage.setItem('research-theme', 'dark')
    const theme = useThemeStore()
    expect(theme.mode).toBe('dark')
  })

  it('toggle switches between light and dark', () => {
    const theme = useThemeStore()
    theme.toggle()
    expect(theme.mode).toBe('dark')
    theme.toggle()
    expect(theme.mode).toBe('light')
  })
})
