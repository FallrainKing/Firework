import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h, onDeactivated, onMounted, onUnmounted } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { workbenchApi } from '@/api/workbench'

const events: string[] = []

vi.mock('@/views/ReaderPane.vue', () => ({
  default: defineComponent({
    props: ['paperId', 'sessionId'],
    setup(props) {
      onMounted(() => events.push('mount:' + props.paperId + ':' + (props.sessionId ?? 'new')))
      onDeactivated(() => events.push('deactivated:' + props.paperId))
      onUnmounted(() => events.push('unmount:' + props.paperId))
      return () => h('div', { class: 'pane-stub' }, String(props.paperId))
    },
  }),
}))

import ReadingView from './ReadingView.vue'

beforeEach(() => {
  events.length = 0
  localStorage.clear()
  setActivePinia(createPinia())
  vi.spyOn(workbenchApi, 'saveState').mockImplementation(async (_id, s) => s)
})

async function mountView(paperId: number | null, sessionId: number | null = null) {
  const wrapper = mount(ReadingView, { props: { paperId, sessionId } })
  await flushPromises()
  return wrapper
}

describe('ReadingView KeepAlive pool', () => {
  it('renders a pane for the active paper', async () => {
    const wrapper = await mountView(1)
    expect(wrapper.findAll('.pane-stub')).toHaveLength(1)
    expect(events).toContain('mount:1:new')
  })

  it('caches at most 3 panes and evicts LRU', async () => {
    const wrapper = await mountView(1)
    await wrapper.setProps({ paperId: 2 })
    await wrapper.setProps({ paperId: 3 })
    await flushPromises()
    expect(events.filter(e => e.startsWith('deactivated'))).toHaveLength(2)
    await wrapper.setProps({ paperId: 4 })
    await flushPromises()
    expect(events).toContain('unmount:1')
    // 缓存中保留 2/3，活动 4
    expect(wrapper.findAll('.pane-stub').length).toBeLessThanOrEqual(3)
  })

  it('session rebind keeps the cached pane (key=paperId, rebind via activate)', async () => {
    const wrapper = await mountView(1, 10)
    await wrapper.setProps({ sessionId: 20 })
    await flushPromises()
    // 自动绑定/切换会话不再重建面板（避免双启动与僵尸缓存槽）。
    expect(events.filter(e => e.startsWith('mount:1'))).toHaveLength(1)
    expect(events).not.toContain('unmount:1')
  })

  it('home (null paper) hides but keeps cache', async () => {
    const wrapper = await mountView(1)
    await wrapper.setProps({ paperId: null })
    await flushPromises()
    expect(events).toContain('deactivated:1')
    expect(events).not.toContain('unmount:1')
    expect(wrapper.find('.reading-frames').isVisible()).toBe(false)
  })
})
