import {it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {defineComponent,ref} from 'vue'
import {usePaperGuide} from './usePaperGuide'
import {guidesApi} from '@/api/guides'
it('isolates cached guide responses by paper identity even when the PDF hash is identical',async()=>{
 const doc=ref<any>({paper_id:1,file_version:'same',page_count:3})
 let resolveOld!:(x:any)=>void
 vi.spyOn(guidesApi,'current').mockImplementationOnce(()=>new Promise(r=>{resolveOld=r})).mockResolvedValue({task:null,guide:{id:'b',paper_id:2,file_version:'same'},older_versions:0} as never)
 let controller!:ReturnType<typeof usePaperGuide>
 const wrapper=mount(defineComponent({setup(){controller=usePaperGuide(doc,vi.fn(async()=>{}),vi.fn());return()=>null}}))
 await flushPromises();doc.value={paper_id:2,file_version:'same',page_count:3};await flushPromises()
 resolveOld({task:null,guide:{id:'a',paper_id:1,file_version:'same'},older_versions:0});await flushPromises()
 expect(controller.state.value.guide?.id).toBe('b')
 expect(guidesApi.current).toHaveBeenLastCalledWith(2,'same');wrapper.unmount()
})
it('ignores an obsolete request error after switching PDF versions',async()=>{
 const doc=ref<any>({paper_id:1,file_version:'old',page_count:3});let rejectOld!:(x:any)=>void
 vi.spyOn(guidesApi,'current').mockImplementationOnce(()=>new Promise((_resolve,reject)=>{rejectOld=reject})).mockResolvedValue({task:null,guide:null,older_versions:1})
 let controller!:ReturnType<typeof usePaperGuide>
 const wrapper=mount(defineComponent({setup(){controller=usePaperGuide(doc,vi.fn(async()=>{}),vi.fn());return()=>null}}))
 await flushPromises();doc.value={...doc.value,file_version:'new'};await flushPromises();rejectOld(new Error('old failure'));await flushPromises()
 expect(controller.error.value).toBe('');expect(guidesApi.current).toHaveBeenLastCalledWith(1,'new');wrapper.unmount()
})
