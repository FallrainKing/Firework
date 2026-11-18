import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ImportPanel from './ImportPanel.vue'
import { importsApi } from '@/api/imports'
import { papersApi } from '@/api/papers'

const item = { id: 'i1', channel: 'doi', source_value: '10.1/x', original_filename: null, status: 'completed', paper_id: 1, conversation_id: 5, run_id: 'r1', message: '已入库', error: null, created_at: '' }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
  vi.spyOn(importsApi, 'list').mockResolvedValue({ imports: [] })
  vi.spyOn(papersApi, 'collections').mockResolvedValue({ collections: [{ id: 2, name: '基础模型' }] })
})

async function mountPanel(props: Record<string, unknown> = {}) {
  const wrapper = mount(ImportPanel, { props })
  await flushPromises()
  return wrapper
}

describe('ImportPanel', () => {
  it('source submit passes collection and target paper', async () => {
    vi.spyOn(importsApi, 'source').mockResolvedValue(item as never)
    const wrapper = await mountPanel({ targetPaperId: 7 })
    await wrapper.find('select.import-collection').setValue('2')
    await wrapper.find('input.source-value').setValue('10.1234/test')
    await wrapper.find('form.source-form').trigger('submit')
    await flushPromises()
    expect(importsApi.source).toHaveBeenCalledWith(expect.objectContaining({ value: '10.1234/test', collection_id: 2, target_paper_id: 7 }))
  })

  it('tracks import until terminal and emits library-updated', async () => {
    vi.spyOn(importsApi, 'list').mockResolvedValue({ imports: [{ ...item, status: 'running' }] } as never)
    vi.spyOn(importsApi, 'get').mockResolvedValue(item as never)
    const wrapper = await mountPanel()
    expect(importsApi.get).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(2100)
    expect(importsApi.get).toHaveBeenCalledWith('i1')
    expect(wrapper.emitted('library-updated')).toBeTruthy()
    expect(wrapper.text()).toContain('已入库')
  })

  it('failed import offers retry', async () => {
    vi.spyOn(importsApi, 'list').mockResolvedValue({ imports: [{ ...item, status: 'failed', error: '下载失败' }] } as never)
    vi.spyOn(importsApi, 'retry').mockResolvedValue({ ...item, status: 'pending' } as never)
    vi.spyOn(importsApi, 'get').mockResolvedValue(item as never)
    const wrapper = await mountPanel()
    await wrapper.find('button.retry-import').trigger('click')
    await flushPromises()
    expect(importsApi.retry).toHaveBeenCalledWith('i1')
  })

  it('rejects more than 8 files', async () => {
    const wrapper = await mountPanel()
    const vm = wrapper.vm as unknown as { uploadFiles: (files: File[]) => Promise<void> }
    const files = Array.from({ length: 9 }, (_, i) => new File(['%PDF-1.4'], `p${i}.pdf`, { type: 'application/pdf' }))
    await expect(vm.uploadFiles(files)).rejects.toThrow('8 个')
  })
})
