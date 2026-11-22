import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import SettingsView from './SettingsView.vue'
import { meApi } from '@/api/me'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkbenchStore } from '@/stores/workbench'

const profile = {
  display_name: '研究者',
  auth_mode: 'local' as const,
  avatar_url: null,
  revision: 1,
  updated_at: '2026-11-19T12:00:00Z',
  capabilities: { auth: false, avatar_upload: true, preferences: true, skills: true },
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.restoreAllMocks()
  vi.spyOn(meApi, 'profile').mockResolvedValue(profile)
  vi.spyOn(meApi, 'preferences').mockResolvedValue({ preferences: { theme: 'dark' }, revision: 4 })
})

describe('SettingsView', () => {
  it('distinguishes authenticated account isolation from the admin-only login policy', async () => {
    vi.mocked(meApi.profile).mockResolvedValue({ ...profile, auth_mode: 'account', capabilities: { ...profile.capabilities, auth: true }, login_policy: { admin_only: true, registration_open: false } })
    const wrapper = mount(SettingsView)
    await flushPromises()
    expect(wrapper.text()).toContain('账号隔离已启用')
    expect(wrapper.text()).toContain('仅主管理员可登录')
    expect(wrapper.text()).toContain('公开注册关闭')
    expect(wrapper.text()).not.toContain('多用户认证未实现')
    wrapper.unmount()
  })
  it('opens the skill library and exposes execution/MCP and external access management', async () => {
    const wrapper = mount(SettingsView)
    await flushPromises()
    await wrapper.find('.agent-management button').trigger('click')
    expect(useWorkbenchStore().view).toBe('skills')
    expect(wrapper.find('.agent-management').text()).toContain('执行方案与 MCP')
    expect(wrapper.find('.agent-management').text()).toContain('外部智能体接入')
    wrapper.unmount()
  })
  it('does not announce a save on initial load', async () => {
    const wrapper = mount(SettingsView)
    await flushPromises()
    expect(wrapper.findAll('.state.saved')).toHaveLength(0)
    wrapper.unmount()
  })

  it('edits the local profile and preferences with real capabilities', async () => {
    const updateProfile = vi.spyOn(meApi, 'updateProfile').mockResolvedValue({ ...profile, display_name: '新研究者', revision: 2 })
    const updatePreferences = vi.spyOn(meApi, 'updatePreferences').mockResolvedValue({ preferences: { theme: 'light' }, revision: 5 })
    const wrapper = mount(SettingsView)
    await flushPromises()

    expect(wrapper.text()).toContain('本机模式，无需登录')
    expect(wrapper.text()).toContain('多用户认证本机模式未启用登录')
    expect(wrapper.text()).toContain('没有认证能力时不提供退出登录按钮')
    expect(wrapper.findAll('button').some(button => button.text() === '退出登录')).toBe(false)

    await wrapper.find('[data-testid="display-name-input"]').setValue('新研究者')
    await wrapper.find('[data-testid="save-profile"]').trigger('click')
    await flushPromises()
    expect(updateProfile).toHaveBeenCalledWith('新研究者')

    await wrapper.find('[data-testid="preferences-input"]').setValue('{"theme":"light"}')
    await wrapper.find('[data-testid="save-preferences"]').trigger('click')
    await flushPromises()
    expect(updatePreferences).toHaveBeenCalledWith({ theme: 'light' }, 4)
    expect(wrapper.text()).toContain('偏好设置已保存')
    wrapper.unmount()
  })

  it('shows JSON validation errors without saving', async () => {
    const updatePreferences = vi.spyOn(meApi, 'updatePreferences')
    const wrapper = mount(SettingsView)
    await flushPromises()
    await wrapper.find('[data-testid="preferences-input"]').setValue('[]')
    await wrapper.find('[data-testid="save-preferences"]').trigger('click')
    expect(updatePreferences).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('偏好设置必须是 JSON 对象')
    wrapper.unmount()
  })
})
