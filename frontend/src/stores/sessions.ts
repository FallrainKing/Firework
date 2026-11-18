import { defineStore } from 'pinia'
import { sessionsApi } from '@/api/sessions'
import type { Category, Template } from '@/api/types'

export const useSessionsStore = defineStore('sessions', {
  state: () => ({
    templates: [] as Template[],
    categories: [] as Category[],
    kinds: {} as Record<string, string>,
    skills: [] as Array<{ id: string; name: string }>,
    loaded: false,
  }),
  actions: {
    async load() {
      const [t, c] = await Promise.all([sessionsApi.templates(), sessionsApi.categories()])
      this.templates = t.templates
      this.kinds = t.kinds
      this.skills = t.skills
      this.categories = c.categories
      this.loaded = true
    },
    async addCategory(name: string): Promise<Category> {
      const created = await sessionsApi.createCategory(name)
      this.categories.push(created)
      return created
    },
    async addTemplate(body: { name: string; description?: string; skill: string; prompt: string }): Promise<Template> {
      const created = await sessionsApi.createTemplate(body)
      this.templates.push(created)
      return created
    },
  },
})
