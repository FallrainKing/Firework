import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import StateFeedback from './StateFeedback.vue'

describe('StateFeedback', () => {
  it('does not show saved for an empty success message', () => {
    const wrapper = mount(StateFeedback, { props: { saved: '' } })
    expect(wrapper.find('.saved').exists()).toBe(false)
  })

  it('does not show the previous success while saving again', () => {
    const wrapper = mount(StateFeedback, { props: { saving: true, saved: '已保存' } })
    expect(wrapper.text()).toContain('保存中…')
    expect(wrapper.find('.saved').exists()).toBe(false)
  })

  it('shows loading before empty state', () => {
    const wrapper = mount(StateFeedback, { props: { loading: true, empty: true } })
    expect(wrapper.text()).toContain('正在载入…')
    expect(wrapper.text()).not.toContain('暂无内容')
  })

  it('shows an error with retry', async () => {
    const wrapper = mount(StateFeedback, { props: { error: '网络错误', empty: true } })
    expect(wrapper.text()).toContain('网络错误')
    expect(wrapper.text()).not.toContain('暂无内容')
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('shows empty only without loading or error', () => {
    const wrapper = mount(StateFeedback, { props: { empty: true, emptyText: '暂无论文' } })
    expect(wrapper.text()).toContain('暂无论文')
  })

  it('shows saving state', () => {
    expect(mount(StateFeedback, { props: { saving: true } }).text()).toContain('保存中…')
  })

  it('shows saved state', () => {
    expect(mount(StateFeedback, { props: { saved: true } }).text()).toContain('已保存')
  })

  it('shows save failure instead of success', () => {
    const wrapper = mount(StateFeedback, { props: { saved: true, saveError: '版本冲突' } })
    expect(wrapper.text()).toContain('保存失败：版本冲突')
    expect(wrapper.text()).not.toContain('已保存')
  })
})
