import {mount} from '@vue/test-utils'
import {describe,it,expect,vi} from 'vitest'
import RegisterView from './RegisterView.vue'
describe('closed registration',()=>{
 it('shows the registration page but cannot submit credentials',()=>{
  const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher)
  const w=mount(RegisterView,{global:{stubs:{RouterLink:true}}})
  expect(w.text()).toContain('注册暂未开放')
  expect(w.find('fieldset').attributes('disabled')).toBeDefined()
  expect(w.find('button').attributes('type')).toBe('button')
  expect(fetcher).not.toHaveBeenCalled()
  vi.unstubAllGlobals()
 })
})
