import { defineStore } from 'pinia'

const KEY = 'research-theme'

export type ThemeMode = 'light' | 'dark'

function stored(): ThemeMode {
  const value = localStorage.getItem(KEY)
  return value === 'dark' ? 'dark' : 'light'
}

export const useThemeStore = defineStore('theme', {
  state: () => ({ mode: stored() as ThemeMode }),
  actions: {
    setMode(mode: ThemeMode) {
      this.mode = mode
      localStorage.setItem(KEY, mode)
      document.documentElement.dataset.theme = mode
    },
    toggle() {
      this.setMode(this.mode === 'light' ? 'dark' : 'light')
    },
    init() {
      document.documentElement.dataset.theme = this.mode
    },
  },
})
