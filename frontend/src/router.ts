import { createRouter, createWebHistory } from 'vue-router'
import {refreshAuth,authState} from '@/auth/session'

// 单路由工作台：视图切换走 workbench store.view（随工作区持久化）。
// /reader/:paperId 与 ?paper_id/session_id 深链由 WorkbenchView 启动时解析。
export const router = createRouter({
  history: createWebHistory('/'),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    { path: '/register', name: 'register', component: () => import('@/views/RegisterView.vue') },
    { path: '/accounts', name: 'accounts', component: () => import('@/views/AccountsView.vue') },
    { path: '/', name: 'workbench', component: () => import('@/views/WorkbenchView.vue') },
    { path: '/reader/:paperId', name: 'reader', component: () => import('@/views/WorkbenchView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async to=>{
  try{await refreshAuth()}catch{return to.path==='/login'||to.path==='/register'?true:'/login'}
  if(!authState.value?.authenticated&&to.path!=='/login'&&to.path!=='/register')return '/login'
  if(authState.value?.authenticated&&(to.path==='/login'||to.path==='/register'))return '/'
  if(to.path==='/accounts'&&authState.value?.account?.role!=='admin')return '/'
  return true
})
