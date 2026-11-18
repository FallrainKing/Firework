import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WelcomeView from './WelcomeView.vue'
import { sessionsApi } from '@/api/sessions'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(sessionsApi, 'templates').mockResolvedValue({
    templates: [
      { id: 'read', name: '阅读论文', description: 'd', kind: 'reading', skill: 'paper_read', prompt: 'p', builtin: 1 },
      { id: 'chat', name: '自由讨论', description: 'd', kind: 'chat', skill: 'chat', prompt: '', builtin: 1 },
    ],
    kinds: {},
    skills: [],
  })
})

describe('WelcomeView', () => {
  it('renders builtin templates', async () => {
    const wrapper = mount(WelcomeView)
    await flushPromises()
    expect(wrapper.text()).toContain('阅读论文')
    expect(wrapper.text()).toContain('自由讨论')
  })

  it('template click emits use-template', async () => {
    const wrapper = mount(WelcomeView)
    await flushPromises()
    await wrapper.findAll('.template-card')[0].trigger('click')
    expect(wrapper.emitted('use-template')?.[0][0]).toMatchObject({ id: 'read' })
  })

  it('start emits trimmed question; empty disabled', async () => {
    const wrapper = mount(WelcomeView)
    await flushPromises()
    const btn = wrapper.find('button.primary')
    expect(btn.attributes('disabled')).toBeDefined()
    await wrapper.find('textarea').setValue('  解释核心方法  ')
    expect(btn.attributes('disabled')).toBeUndefined()
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('start')?.[0][0]).toBe('解释核心方法')
  })

  it('compare and discuss entries emit', async () => {
    const wrapper = mount(WelcomeView)
    await flushPromises()
    await wrapper.find('[data-action="compare"]').trigger('click')
    await wrapper.find('[data-action="discuss"]').trigger('click')
    expect(wrapper.emitted('compare')).toHaveLength(1)
    expect(wrapper.emitted('discuss')).toHaveLength(1)
  })
})
