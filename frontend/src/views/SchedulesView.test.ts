import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SchedulesView from './SchedulesView.vue'
import { schedulesApi } from '@/api/schedules'
import { sessionsApi } from '@/api/sessions'

const schedules = [
  { id: 1, title: '论文阅读回顾', conversation_id: 5, prompt: 'p', interval_hours: 24, enabled: false, next_at: '2026-11-19 02:00:00', last_run_id: null, session_title: '阅读会话', created_at: '' },
]

beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(schedulesApi, 'list').mockResolvedValue({ schedules })
  vi.spyOn(schedulesApi, 'enable').mockResolvedValue({ saved: true })
  vi.spyOn(schedulesApi, 'run').mockResolvedValue({ id: 'r1' } as never)
  vi.spyOn(sessionsApi, 'list').mockResolvedValue({ sessions: [{ id: 5, title: '阅读会话', skill: 'paper_read', archived: false }] } as never)
})

describe('SchedulesView', () => {
  it('renders schedule list', async () => {
    const wrapper = mount(SchedulesView)
    await flushPromises()
    expect(wrapper.text()).toContain('论文阅读回顾')
    expect(wrapper.text()).toContain('阅读会话')
  })

  it('enable toggle calls api with inverted state', async () => {
    const wrapper = mount(SchedulesView)
    await flushPromises()
    await wrapper.find('button[data-action="toggle"]').trigger('click')
    await flushPromises()
    expect(schedulesApi.enable).toHaveBeenCalledWith(1, true)
  })

  it('manual run calls api', async () => {
    const wrapper = mount(SchedulesView)
    await flushPromises()
    await wrapper.find('button[data-action="run"]').trigger('click')
    await flushPromises()
    expect(schedulesApi.run).toHaveBeenCalledWith(1)
  })

  it('new schedule dialog defaults to paused', async () => {
    const wrapper = mount(SchedulesView)
    await flushPromises()
    await wrapper.find('button[data-action="new"]').trigger('click')
    expect(wrapper.find('input[data-field="enabled"]').exists()).toBe(false) // 默认暂停，不提供启用勾选
    expect(wrapper.text()).toContain('新建任务默认暂停')
  })
})
