import {describe,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {ref} from 'vue'
import GuideActions from './GuideActions.vue'
function controller(){return {state:ref({task:null,guide:null}),skills:ref([{id:'paper_guide',name:'导读 Skill',version_id:42,max_budget_usd:.2}]),busy:ref(false),running:ref(false),error:ref(''),loadSkills:vi.fn(async()=>{}),start:vi.fn(async()=>{}),cancel:vi.fn()}}
describe('explicit reading actions',()=>{
 it('opening suggestions or choosing annotate never starts a task before confirmation',async()=>{const c=controller();const w=mount(GuideActions,{props:{controller:c as never,ready:true,pageCount:15}});expect(c.start).not.toHaveBeenCalled();await w.findAll('button').find(x=>x.text()==='自动批注')!.trigger('click');await flushPromises();expect(c.loadSkills).toHaveBeenCalledOnce();expect(c.start).not.toHaveBeenCalled();await w.findAll('button').find(x=>x.text()==='确认生成批注')!.trigger('click');expect(c.start).toHaveBeenCalledWith(expect.objectContaining({skill_id:'paper_guide',skill_version_id:42}));w.unmount()})
 it('reading needs confirmation and cancelling does no work',async()=>{const c=controller();const w=mount(GuideActions,{props:{controller:c as never,ready:true,pageCount:2}});await w.findAll('button').find(x=>x.text()==='阅读论文')!.trigger('click');expect(w.emitted('read')).toBeUndefined();await w.findAll('button').find(x=>x.text()==='取消')!.trigger('click');expect(c.start).not.toHaveBeenCalled();await w.findAll('button').find(x=>x.text()==='阅读论文')!.trigger('click');await w.findAll('button').find(x=>x.text()==='确认开始阅读')!.trigger('click');expect(w.emitted('read')).toHaveLength(1);w.unmount()})
})
