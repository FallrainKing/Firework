import { api } from './client'
import type { Category, Run, Session, SessionCreate, SessionPatch, Template } from './types'

export const sessionsApi = {
  list(params: { q?: string; kind?: string; paper_id?: number; category_id?: number; archived?: boolean; limit?: number } = {}): Promise<{ sessions: Session[] }> {
    const search = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') search.set(k, String(v))
    const q = search.toString()
    return api(`/api/sessions${q ? '?' + q : ''}`)
  },
  create(body: SessionCreate): Promise<{ session: Session; starting_prompt: string }> {
    return api('/api/sessions', { body })
  },
  get(id: number): Promise<{ session: Session; papers: Array<{ id: number; title: string }> }> {
    return api(`/api/sessions/${id}`)
  },
  update(id: number, body: SessionPatch): Promise<Session> {
    return api(`/api/sessions/${id}`, { method: 'PATCH', body })
  },
  runs(id: number, before?: number, limit = 50): Promise<{ runs: Run[]; has_more: boolean; next_before: number | null }> {
    const q = before !== undefined ? `&before=${before}` : ''
    return api(`/api/sessions/${id}/runs?limit=${limit}${q}`)
  },
  templates(): Promise<{ templates: Template[]; kinds: Record<string, string>; skills: Array<{ id: string; name: string }> }> {
    return api('/api/sessions/templates')
  },
  createTemplate(body: { name: string; description?: string; skill: string; prompt: string }): Promise<Template> {
    return api('/api/sessions/templates', { body })
  },
  categories(): Promise<{ categories: Category[] }> {
    return api('/api/sessions/categories')
  },
  createCategory(name: string): Promise<Category> {
    return api('/api/sessions/categories', { body: { name } })
  },
}
