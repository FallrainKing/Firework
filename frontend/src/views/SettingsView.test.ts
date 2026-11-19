import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import SettingsView from './SettingsView.vue'
import { meApi } from '@/api/me'

const profile = {
  display_name: '研究者',
  auth_mode: 'local' as const,
  avatar_url: null,
  revision: 1,
  updated_at: '2026-11-19T12:00:00Z',
  capabilities: { auth: false, avatar_upload: true, preferences: true, skills: true },
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(meApi, 'profile').mockResolvedValue(profile)
  vi.spyOn(meApi, 'preferences').mockResolvedValue({ preferences: { theme: 'dark' }, revision: 4 })
})

describe('SettingsView', () => {
  it('edits the local profile and preferences with real capabilities', async () => {
    const updateProfile = vi.spyOn(meApi, 'updateProfile').mockResolvedValue({ ...profile, display_name: '新研究者', revision: 2 })
    const updatePreferences = vi.spyOn(meApi, 'updatePreferences').mockResolvedValue({ preferences: { theme: 'light' }, revision: 5 })
    const wrapper = mount(SettingsView)
    await flushPromises()

    expect(wrapper.text()).toContain('本机模式，无需登录')
    expect(wrapper.text()).toContain('多用户认证未实现')
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
