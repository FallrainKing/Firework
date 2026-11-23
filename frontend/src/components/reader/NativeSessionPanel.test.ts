import {mount,flushPromises} from '@vue/test-utils'
import {afterEach,describe,expect,it,vi} from 'vitest'
import NativeSessionPanel from './NativeSessionPanel.vue'
import {api} from '@/api/client'
vi.mock('@/api/client',()=>({api:vi.fn()}))
afterEach(()=>vi.resetAllMocks())
const event=(id:string,text:string)=>({id,role:'assistant',text,tools:[],images:0,timestamp:'2026-11-23'})
const page=(events:ReturnType<typeof event>[],next_offset=20,reset=false)=>({events,next_offset,reset,source:'a'.repeat(32),session_id:'native',state:'available',has_more:true,connection_name:'own'})
describe('NativeSessionPanel',()=>{
 it('appends cursor pages, resets on rotation and continues without creating a task',async()=>{
  const responses=[page([event('1','First')]),page([event('2','Second')],40),page([event('3','Replaced')],20,true)]
  vi.mocked(api).mockImplementation(async path=>path==='/api/agent/providers'?{providers:[]}:responses.shift() as never)
  const w=mount(NativeSessionPanel,{props:{sessionId:7}});await flushPromises()
  expect(w.text()).toContain('First')
  await w.findAll('footer button')[0].trigger('click');await flushPromises()
  expect(w.text()).toContain('Second')
  expect(vi.mocked(api).mock.calls.some(([path])=>path.includes('offset=20')&&path.includes('source='))).toBe(true)
  await w.findAll('footer button')[0].trigger('click');await flushPromises()
  expect(w.text()).toContain('Replaced');expect(w.text()).not.toContain('First')
  await w.findAll('footer button')[1].trigger('click')
  expect(w.emitted('continue')).toHaveLength(1)
  expect(vi.mocked(api).mock.calls.every(([,opts])=>!opts)).toBe(true)
  w.unmount()
 })
 it('shows failures and retries without changing sessions',async()=>{
  vi.mocked(api).mockRejectedValueOnce(new Error('Runner offline')).mockResolvedValueOnce({providers:[]})
  const w=mount(NativeSessionPanel,{props:{sessionId:7}});await flushPromises()
  expect(w.find('[role=alert]').text()).toContain('Runner offline')
  vi.mocked(api).mockResolvedValue(page([]))
  await w.find('header button').trigger('click');await flushPromises()
  expect(w.find('[role=alert]').exists()).toBe(false)
  w.unmount()
 })
})
