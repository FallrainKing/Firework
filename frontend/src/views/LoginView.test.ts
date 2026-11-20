import {mount,flushPromises} from '@vue/test-utils'
import {describe,it,expect,vi,beforeEach} from 'vitest'
import LoginView from './LoginView.vue'
const fake=vi.hoisted(()=>({login:vi.fn(),replace:vi.fn(),query:{redirect:'/reader/19?session_id=7'},state:{__v_isRef:true,value:{initialized:true,secure_cookie:false,login_url:'https://paper.matchesai.vip/login'}}}))
vi.mock('vue-router',()=>({useRoute:()=>({query:fake.query})}))
vi.mock('@/shared/navigation',async importOriginal=>({...await importOriginal<typeof import('@/shared/navigation')>(),replaceAppLocation:fake.replace}))
vi.mock('@/auth/session',()=>({login:fake.login,authState:fake.state}))
beforeEach(()=>{fake.login.mockReset();fake.replace.mockReset();fake.state.value.secure_cookie=false})
describe('login form',()=>{
 it('returns to the protected page after a successful login',async()=>{
  fake.login.mockResolvedValue({})
  const w=mount(LoginView,{global:{stubs:{RouterLink:true}}})
  await w.find('input[name="username"]').setValue('test-admin')
  await w.find('input[name="password"]').setValue('test-password')
  await w.find('form').trigger('submit');await flushPromises()
  expect(fake.replace).toHaveBeenCalledWith('/reader/19?session_id=7')
 })

 it('prevents production password submission on HTTP and links to HTTPS',async()=>{
  fake.state.value.secure_cookie=true
  const w=mount(LoginView,{global:{stubs:{RouterLink:true}}})
  expect(w.find('input[name="password"]').attributes('disabled')).toBeDefined()
  expect(w.find('a[href="https://paper.matchesai.vip/login"]').exists()).toBe(true)
  await w.find('form').trigger('submit');await flushPromises()
  expect(fake.login).not.toHaveBeenCalled()
  expect(w.text()).toContain('HTTPS 安全入口')
 })

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
