import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import SkillsView from './SkillsView.vue'
import { skillsApi, type Skill } from '@/api/skills'

const versions = [
  {
    id: 2,
    skill_id: 'custom:demo',
    version: '1.1.0',
    content_hash: 'sha256:new',
    entry: 'SKILL.md',
    manifest: {},
    validation_status: 'validated',
    created_at: '2026-11-19T12:00:00Z',
    is_default: true,
    references: { sessions: 0, runs: 0, templates: 0 },
  },
  {
    id: 1,
    skill_id: 'custom:demo',
    version: '1.0.0',
    content_hash: 'sha256:old',
    entry: 'SKILL.md',
    manifest: {},
    validation_status: 'validated',
    created_at: '2026-11-18T12:00:00Z',
    is_default: false,
    references: { sessions: 3, runs: 5, templates: 1 },
  },
]

const skill = {
  id: 'custom:demo',
  name: '演示技能',
  description: '演示',
  source: 'zip',
  status: 'enabled',
  default_version_id: 2,
  default_version: versions[0],
  revision: 7,
  created_at: '2026-11-18T11:00:00Z',
  categories: [],
  versions: [],
} as Skill

beforeEach(() => {
  vi.spyOn(skillsApi, 'list').mockResolvedValue({ skills: [skill], registry_revision: 1 })
  vi.spyOn(skillsApi, 'categories').mockResolvedValue({ categories: [] })
  vi.spyOn(skillsApi, 'versionHistory').mockResolvedValue({
    skill_id: skill.id,
    default_version_id: 2,
    registry_revision: 1,
    versions,
  })
})

describe('SkillsView', () => {
  it('shows version history and rolls back the default version', async () => {
    const rollback = vi.spyOn(skillsApi, 'setDefaultVersion').mockResolvedValue(skill)
    const wrapper = mount(SkillsView)
    await flushPromises()

    expect(wrapper.find('[data-testid="skill-version-panel"]').exists()).toBe(false)
    await wrapper.find('[data-testid="skill-version-toggle"]').trigger('click')
    await flushPromises()

    expect(skillsApi.versionHistory).toHaveBeenCalledWith(skill.id)
    expect(wrapper.text()).toContain('1.1.0')
    expect(wrapper.text()).toContain('1.0.0')
    expect(wrapper.text()).toContain('会话 3 · 运行 5 · 模板 1')

    await wrapper.find('[data-testid="rollback-version"]').trigger('click')
    await flushPromises()

    expect(rollback).toHaveBeenCalledWith(skill.id, versions[1].id, skill.revision)
    expect(wrapper.text()).toContain('回退只影响后续新会话')
    wrapper.unmount()
  })
})
