import {mount,flushPromises} from '@vue/test-utils'
import {beforeEach,it,expect,vi} from 'vitest'
import ResearchView from './ResearchView.vue'
import {api} from '@/api/client'
vi.mock('@/api/client',()=>({api:vi.fn()}))
vi.mock('@/components/PaperPicker.vue',()=>({default:{template:'<div>Paper picker</div>'}}))
const a={id:'a'.repeat(32),title:'Local result',kind:'reading',revision:1,current_revision:1,markdown:'# Findings',paper_ids:[1],evidence:[],files:[{hash:'b'.repeat(64),filename:'evidence.md',paper_id:1}],status:'complete',source_run_id:null,revisions:[1],producer:{name:'local'}}
beforeEach(()=>{vi.mocked(api).mockReset();vi.mocked(api).mockImplementation(async(path)=>path.includes('/artifacts/')?a:{artifacts:[a],knowledge:[],has_more:false,next_before:null})})
it('shows immutable attached files and preserves them when revising',async()=>{
 const w=mount(ResearchView,{global:{stubs:{RouterLink:{template:'<a><slot/></a>'}}}});await flushPromises()
 await w.find('.record').trigger('click');await flushPromises()
 expect(w.find(`a[href="/api/research/files/${'b'.repeat(64)}"]`).text()).toBe('evidence.md')
 await w.findAll('button').find(b=>b.text()==='编辑为新修订')!.trigger('click');await flushPromises()
 await w.find('section form').trigger('submit');await flushPromises()
 const call=vi.mocked(api).mock.calls.find(([,opts])=>opts?.method==='PATCH')
 expect(call?.[1]?.body).toMatchObject({expected_revision:1,file_ids:['b'.repeat(64)]})
})
it('opening the workspace only lists records and never imports or executes automatically',async()=>{
 mount(ResearchView,{global:{stubs:{RouterLink:true}}});await flushPromises()
 expect(vi.mocked(api).mock.calls.every(([path,opts])=>path.startsWith('/api/research/artifacts?')&&!opts)).toBe(true)
})
