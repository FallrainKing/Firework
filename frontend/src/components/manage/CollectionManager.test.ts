import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import CollectionManager from './CollectionManager.vue'
import { papersApi } from '@/api/papers'
const root = { id: 1, name: 'Root', parent_id: null, revision: 4 }
const items = [root, { id: 2, name: 'Child', parent_id: 1 }, { id: 3, name: 'Target', parent_id: null }, { id: 4, name: 'Zotero', managed: true }]
let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { wrapper?.unmount(); wrapper = undefined })
it('excludes self, descendants and source-owned parents and saves with the expected revision', async () => {
  const edit = vi.spyOn(papersApi, 'editCollection').mockResolvedValue({ collections: [] })
  wrapper = mount(CollectionManager, { global: { stubs: { Teleport: true } }, props: { collection: root, collections: items, trash: false }, attachTo: document.body })
  const dialog = document.querySelector('[role="dialog"]')!
  expect(Array.from(dialog.querySelectorAll('option')).map(x => x.textContent)).toEqual(['顶层分类', 'Target'])
  await wrapper.find('input').setValue('Renamed')
  await wrapper.find('select').setValue('3')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  expect(edit).toHaveBeenCalledWith(1, 'Renamed', 3, 4)
  expect(wrapper.emitted('changed')).toHaveLength(1)
  expect(wrapper.emitted('close')).toHaveLength(1)
})
it('requires a separate deletion confirmation and keeps conflicts visible without closing', async () => {
  const remove = vi.spyOn(papersApi, 'trashCollection').mockRejectedValue(new Error('分类已被更新，请刷新后重试'))
  wrapper = mount(CollectionManager, { global: { stubs: { Teleport: true } }, props: { collection: root, collections: items, trash: false } })
  await wrapper.find('.delete-category > button').trigger('click')
  expect(remove).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('不会删除论文或项目')
  await wrapper.find('.danger').trigger('click')
  await flushPromises()
  expect(remove).toHaveBeenCalledWith(1, 4)
  expect(wrapper.find('[role="alert"]').text()).toContain('分类已被更新')
  expect(wrapper.emitted('close')).toBeUndefined()
})
it('restores only deletion batch roots and reloads the category trash', async () => {
  vi.spyOn(papersApi, 'collections').mockResolvedValueOnce({ collections: [{ ...root, restore_root: true }, { id: 2, name: 'Child', restore_root: false }] }).mockResolvedValue({ collections: [] })
  const restore = vi.spyOn(papersApi, 'restoreCollection').mockResolvedValue({ collections: items })
  wrapper = mount(CollectionManager, { global: { stubs: { Teleport: true } }, props: { collection: null, collections: items, trash: true } })
  await flushPromises()
  expect(wrapper.findAll('article')).toHaveLength(1)
  await wrapper.find('article button').trigger('click')
  await flushPromises()
  expect(restore).toHaveBeenCalledWith(1, 4)
  expect(wrapper.text()).toContain('分类回收站为空')
  expect(wrapper.emitted('changed')).toHaveLength(1)
})
