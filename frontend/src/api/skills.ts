import { api } from './client'

export interface SkillVersion {
  id: number
  skill_id: string
  version: string
  content_hash: string
  entry: string
  manifest: {
    name?: string
    version?: string
    description?: string
    requested_tools?: string[]
    budget_profile?: string
  }
  validation_status: string
  created_at: string
}

export interface SkillVersionHistoryItem extends SkillVersion {
  is_default: boolean
  references: {
    sessions: number
    runs: number
    templates: number
  }
}

export interface SkillCategory {
  id: number
  name: string
  sort_order: number
  count?: number
}

export interface Skill {
  id: string
  name: string
  description: string
  source: 'builtin' | 'zip'
  status: 'enabled' | 'disabled' | 'archived'
  default_version_id: number | null
  default_version: SkillVersion | null
  revision: number
  created_at: string
  categories: SkillCategory[]
  versions: SkillVersion[]
}

export interface SkillImport {
  import_id: string
  status: string
  filename: string
  archive_hash: string
  manifest: {
    name?: string
    description?: string
    version?: string
    requested_tools?: string[]
    templates?: Array<{ name?: string; file?: string }>
  } | null
  entry: string
  files: Array<{ name?: string; size?: number }>
  total_bytes: number
  skill: Skill | null
  version: SkillVersion | null
}

export const skillsApi = {
  list(params: { q?: string; status?: string; category_id?: number; source?: string } = {}): Promise<{ skills: Skill[]; registry_revision: number }> {
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== '') search.set(key, String(value))
    }
    const query = search.toString()
    return api(`/api/skills${query ? '?' + query : ''}`)
  },
  categories(): Promise<{ categories: SkillCategory[] }> {
    return api('/api/skills/categories')
  },
  createCategory(name: string): Promise<SkillCategory> {
    return api('/api/skills/categories', { body: { name } })
  },
  upload(file: File): Promise<SkillImport> {
    const form = new FormData()
    form.append('archive', file)
    return api('/api/skills/imports', { form })
  },
  install(importId: string, body: { name: string; description?: string; category_names: string[]; budget_profile: string }): Promise<{ status: string; skill: Skill; version: SkillVersion }> {
    return api(`/api/skills/imports/${importId}/install`, { body })
  },
  enable(skillId: string): Promise<Skill> {
    return api(`/api/skills/${encodeURIComponent(skillId)}/enable`, { method: 'POST' })
  },
  disable(skillId: string): Promise<Skill> {
    return api(`/api/skills/${encodeURIComponent(skillId)}/disable`, { method: 'POST' })
  },
  versionHistory(skillId: string): Promise<{ skill_id: string; default_version_id: number | null; registry_revision: number; versions: SkillVersionHistoryItem[] }> {
    return api(`/api/skills/${encodeURIComponent(skillId)}/versions`)
  },
  setDefaultVersion(skillId: string, versionId: number, expectedRevision: number): Promise<Skill> {
    return api(`/api/skills/${encodeURIComponent(skillId)}/default-version`, {
      body: { version_id: versionId, expected_revision: expectedRevision },
    })
  },
}
