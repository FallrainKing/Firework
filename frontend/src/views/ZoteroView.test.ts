import {mount,flushPromises} from '@vue/test-utils'
import {describe,it,expect,vi,beforeEach} from 'vitest'
import ZoteroView from './ZoteroView.vue'
const fake=vi.hoisted(()=>({api:vi.fn()}))
vi.mock('@/api/client',()=>({api:fake.api,uid32:()=> 'stable-request-key'}))
beforeEach(()=>{fake.api.mockReset();fake.api.mockImplementation(async(path:string)=>{
 if(path==='/api/zotero/devices')return {devices:[]}
 if(path==='/api/zotero/exports')return {jobs:[]}
 if(path.endsWith('/inspect'))return {name:'My laptop',instance_id:'instance-one'}
 return {approved:true}
})})
describe('Zotero approval',()=>{
 it('requires checking a code and explicit approval before granting access',async()=>{
  const w=mount(ZoteroView,{global:{stubs:{RouterLink:true,PaperPicker:true}}});await flushPromises()
  expect(fake.api.mock.calls.some(([p])=>p.includes('/approve'))).toBe(false)
  await w.find('input').setValue('abcdef12');await w.find('form').trigger('submit');await flushPromises()
  expect(w.text()).toContain('My laptop')
  expect(fake.api).toHaveBeenCalledWith('/api/zotero/pair/inspect',{body:{user_code:'ABCDEF12'}})
  expect(fake.api.mock.calls.some(([p])=>p.includes('/approve'))).toBe(false)
  await w.find('.confirmation button').trigger('click');await flushPromises()
  expect(fake.api).toHaveBeenCalledWith('/api/zotero/pair/approve',{body:{user_code:'ABCDEF12'}})
  expect(w.text()).toContain('已授权')
 })
 it('clears the checked identity when the pairing code changes',async()=>{
  const w=mount(ZoteroView,{global:{stubs:{RouterLink:true,PaperPicker:true}}});await flushPromises()
  await w.find('input').setValue('abcdef12');await w.find('form').trigger('submit');await flushPromises()
  await w.find('input').setValue('11223344');expect(w.find('.confirmation').exists()).toBe(false)
  expect(w.find('a[download]').attributes('href')).toBe('/downloads/firework-zotero-0.1.4.xpi')
 })
})
