import {beforeEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import View from './RunnerConnectionsView.vue'
import Control from '@/components/reader/RunConnectionControl.vue'
import {runnerConnections,type Connection} from '@/api/runnerConnections'
const conn:Connection={id:'a'.repeat(32),revision:2,name:'我的模型',enabled:true,has_credential:true,verification:'not_tested',config:{base_url:'https://api.example.com',model:'custom',auth_type:'api_key',vision:'unknown',context_window:200000,role_prompt:''}}
const list={connections:[conn],default_connection_id:null,settings_revision:1,legacy_available:true}
beforeEach(()=>{vi.restoreAllMocks();vi.spyOn(runnerConnections,'list').mockResolvedValue(list)})
it('loads without changing defaults and copies no credential',async()=>{
 const save=vi.spyOn(runnerConnections,'save').mockResolvedValue({...conn,id:'b'.repeat(32),revision:1})
 const def=vi.spyOn(runnerConnections,'setDefault').mockResolvedValue(list)
 const w=mount(View,{global:{stubs:{RouterLink:true}}});await flushPromises()
 expect(def).not.toHaveBeenCalled()
 await w.findAll('button').find(b=>b.text()==='复制（不含密钥）')!.trigger('click')
 expect((w.find('input[type=password]').element as HTMLInputElement).value).toBe('')
 await w.find('input[type=password]').setValue('test-only-key');await w.find('form').trigger('submit');await flushPromises()
 expect(save.mock.calls[0][0].api_key).toBe('test-only-key');expect(save.mock.calls[0][1]).toBeUndefined()
 expect((w.find('input[type=password]').element as HTMLInputElement).value).toBe('');w.unmount()
})
it('editing preserves the credential without reading it back',async()=>{
 const save=vi.spyOn(runnerConnections,'save').mockResolvedValue({...conn,revision:3})
 const w=mount(View,{global:{stubs:{RouterLink:true}}});await flushPromises();await w.findAll('button').find(b=>b.text()==='编辑')!.trigger('click');await w.find('form').trigger('submit');await flushPromises()
 expect(save.mock.calls[0][0]).not.toHaveProperty('api_key');expect(save.mock.calls[0][0].expected_revision).toBe(2);expect(save.mock.calls[0][1]).toBe(conn.id);w.unmount()
})
it('per-session selection emits a revision; bound sessions cannot change connection',async()=>{
 const w=mount(Control,{props:{modelValue:null}});expect(runnerConnections.list).not.toHaveBeenCalled()
 await w.find('button').trigger('click');await flushPromises();await w.find('select').setValue(conn.id)
 expect(w.emitted('update:modelValue')?.[0]).toEqual([{id:conn.id,revision:2}]);await w.setProps({bound:true});expect(w.find('select').exists()).toBe(false);expect(w.text()).toContain('新建会话');w.unmount()
})
