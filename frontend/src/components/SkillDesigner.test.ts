import {mount,flushPromises} from '@vue/test-utils'
import {afterEach,describe,expect,it,vi} from 'vitest'
import SkillDesigner from './SkillDesigner.vue'
import {skillAuthoring} from '@/api/skillAuthoring'
import {runnerProfiles} from '@/api/runnerProfiles'
afterEach(()=>vi.restoreAllMocks())
describe('SkillDesigner',()=>{
 it('saves instructions and feature scope before publishing the exact draft revision',async()=>{
  vi.spyOn(skillAuthoring,'surfaces').mockResolvedValue({surfaces:[{id:'reader_chat',label:'阅读对话'},{id:'frontier',label:'前沿追踪'}]})
  vi.spyOn(runnerProfiles,'tools').mockResolvedValue({servers:[],external_servers_enabled:false})
  const save=vi.spyOn(skillAuthoring,'save').mockImplementation(async body=>({skill_id:'custom:one',revision:7,body}))
  const publish=vi.spyOn(skillAuthoring,'publish').mockResolvedValue({} as never)
  const w=mount(SkillDesigner,{props:{skill:null}});await flushPromises()
  await w.find('input[maxlength="120"]').setValue('我的精读')
  await w.find('textarea[maxlength="100000"]').setValue('按证据逐段解释')
  await w.findAll('input[type="checkbox"]')[1].setValue(true)
  await w.findAll('footer button')[1].trigger('click');await flushPromises()
  expect(save.mock.calls[0][0]).toMatchObject({name:'我的精读',instructions:'按证据逐段解释',surfaces:['reader_chat','frontier']})
  expect(publish).toHaveBeenCalledWith('custom:one',7)
  expect(w.text()).toContain('版本已发布')
  w.unmount()
 })
})
