import {mount,flushPromises} from '@vue/test-utils'
import {describe,it,expect,vi,beforeEach} from 'vitest'
import LoginView from './LoginView.vue'
const fake=vi.hoisted(()=>({login:vi.fn()}))
vi.mock('@/auth/session',()=>({login:fake.login,authState:{initialized:true}}))
beforeEach(()=>{fake.login.mockReset()})
describe('login form',()=>{
 it('does not authenticate automatically and clears a rejected password',async()=>{
  fake.login.mockRejectedValue(new Error('账号或密码错误'))
  const w=mount(LoginView,{global:{stubs:{RouterLink:true}}})
  expect(fake.login).not.toHaveBeenCalled()
  await w.find('input[name="username"]').setValue('paper')
  await w.find('input[name="password"]').setValue('not-stored')
  await w.find('form').trigger('submit');await flushPromises()
  expect(fake.login).toHaveBeenCalledWith('paper','not-stored')
  expect((w.find('input[name="password"]').element as HTMLInputElement).value).toBe('')
  expect(w.text()).toContain('账号或密码错误')
 })
})
