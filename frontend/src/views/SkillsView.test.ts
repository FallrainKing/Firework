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
  vi.spyOn(skillsApi, 'versionResources').mockResolvedValue({
    skill_id: skill.id,
    version_id: 2,
    resources: [
      { path: 'SKILL.md', size_bytes: 18, is_entry: true, readable: true },
      { path: 'references/paper.md', size_bytes: 28, is_entry: false, readable: true },
    ],
  })
  vi.spyOn(skillsApi, 'versionResourceContent').mockResolvedValue({
    skill_id: skill.id,
    version_id: 2,
    path: 'SKILL.md',
    size_bytes: 18,
    content: '# Demo skill',
    truncated: false,
  })
  vi.spyOn(skillsApi, 'validateRun').mockResolvedValue({
    skill_id: skill.id,
    version_id: 2,
    run_id: 'run-validate',
    status: 'queued',
    purpose: 'skill-validation',
    model_invocation: true,
  })
  vi.spyOn(skillsApi, 'audit').mockResolvedValue({
    skill_id: skill.id,
    audit: [
      { id: 2, skill_id: skill.id, version_id: 2, action: 'enable', detail: {}, created_at: '2026-11-19T12:01:00Z' },
      { id: 1, skill_id: skill.id, version_id: 1, action: 'install', detail: {}, created_at: '2026-11-19T12:00:00Z' },
    ],
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

  it('previews version resources and shows audit history', async () => {
    const wrapper = mount(SkillsView)
    await flushPromises()

    await wrapper.find('[data-testid="skill-version-toggle"]').trigger('click')
    await flushPromises()
    const resourceButton = wrapper.findAll('button').find(button => button.text() === '资源')
    await resourceButton?.trigger('click')
    await flushPromises()

    expect(skillsApi.versionResources).toHaveBeenCalledWith(skill.id, 2)
    expect(wrapper.find('[data-testid="skill-resource-panel"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('references/paper.md')

    await wrapper.findAll('[data-testid="skill-resource-panel"] button')[0].trigger('click')
    await flushPromises()
    expect(skillsApi.versionResourceContent).toHaveBeenCalledWith(skill.id, 2, 'SKILL.md')
    expect(wrapper.text()).toContain('# Demo skill')

    const auditButton = wrapper.findAll('button').find(button => button.text() === '记录')
    await auditButton?.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="skill-audit-panel"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('启用')
    expect(wrapper.text()).toContain('安装')
    wrapper.unmount()
  })

  it('submits an explicit real model validation run only after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(SkillsView)
    await flushPromises()

    await wrapper.find('[data-testid="skill-validate-run"]').trigger('click')
    await flushPromises()

    expect(window.confirm).toHaveBeenCalledWith('验证执行会显式发起一次真实模型调用，并记录用量与成本。确定继续吗？')
    expect(skillsApi.validateRun).toHaveBeenCalledWith(
      skill.id,
      '请执行一次最小技能验证，并简要说明结果。',
      expect.any(String),
    )
    expect(wrapper.find('[data-testid="skill-validation-result"]').text()).toContain('真实模型调用')
    wrapper.unmount()
  })
})
