import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import GuideHistory from './GuideHistory.vue'
import { guidesApi, type PaperGuide } from '@/api/guides'
const result = { summary: { problem_md: '历史问题', approach_md: '方法', contributions_md: '贡献', limitations_md: '边界' }, reading_route: [], unknown_fields: [] }
const item = { id: 'item', item: { key: 'k', title: '重点', why_important_md: '重要原因', explanation_md: '解释', category: 'method', priority: 'essential', claim_type: 'author_claim', follow_up_questions: [], uncertainties: [] }, anchors: [{ page: 2, quote: 'exact quote', rects: [[0, 0, 1, 1]], status: 'verified', block_id: 'b' }], annotations: [], location_status: 'verified' }
function guide(id: string, version: string): PaperGuide { return { id, file_version: version, skill_id: 'paper_guide', skill_version_id: 3, status: 'published', result, items: [item], agent_run_id: 'run-' + id, created_at: '2026-11-22', hidden: 0, paper_id: 1, conversation_id: 5, active: 0, error: null, cached: false, coverage: {}, warnings: [], usage: {}, cost: null } }
let wrapper: ReturnType<typeof mount> | undefined
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks() })
it('reads history without model calls and forbids positioning a different PDF version', async () => {
  vi.spyOn(guidesApi, 'history').mockResolvedValue({ guides: [guide('old', 'hash-old'), guide('current', 'hash-current')] })
  const create = vi.spyOn(guidesApi, 'create'), jump = vi.fn()
  wrapper = mount(GuideHistory, { props: { paperId: 1, fileVersion: 'hash-current', jump }, global: { stubs: { Teleport: true } } })
  await flushPromises()
  expect(wrapper.text()).toContain('历史问题')
  expect(wrapper.text()).toContain('来自不同 PDF 版本')
  expect(wrapper.findAll('button').find(b => b.text() === '定位当前版本原文')!.attributes('disabled')).toBeDefined()
  await wrapper.findAll('button').find(b => b.text() === '定位当前版本原文')!.trigger('click')
  expect(jump).not.toHaveBeenCalled()
  await wrapper.find('select').setValue('current')
  await wrapper.findAll('button').find(b => b.text() === '定位当前版本原文')!.trigger('click')
  expect(jump).toHaveBeenCalledWith(expect.objectContaining({ paper_id: 1, file_version: 'hash-current', page: 2, quote: 'exact quote' }))
  expect(create).not.toHaveBeenCalled()
  expect(wrapper.emitted('close')).toHaveLength(1)
})
it('shows history load errors and lets the user retry without generating a guide', async () => {
  vi.spyOn(guidesApi, 'history').mockRejectedValueOnce(new Error('历史读取失败')).mockResolvedValue({ guides: [] })
  wrapper = mount(GuideHistory, { props: { paperId: 1, fileVersion: 'hash', jump: vi.fn() }, global: { stubs: { Teleport: true } } })
  await flushPromises()
  expect(wrapper.find('[role="alert"]').text()).toContain('历史读取失败')
  await wrapper.find('[role="alert"] button').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('暂无历史导读')
})
