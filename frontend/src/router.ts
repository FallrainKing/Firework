import { createRouter, createWebHashHistory } from 'vue-router'
import {loginPath, migrateLegacyLocation, safeReturnTarget} from '@/shared/navigation'
import {refreshAuth,authState} from '@/auth/session'

// 单路由工作台：视图切换走 workbench store.view（随工作区持久化）。
// /reader/:paperId 与 ?paper_id/session_id 深链由 WorkbenchView 启动时解析。
migrateLegacyLocation()

export const router = createRouter({
  history: createWebHashHistory('/'),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    { path: '/register', name: 'register', component: () => import('@/views/RegisterView.vue') },
    { path: '/integrations/zotero', name: 'zotero', component: () => import('@/views/ZoteroView.vue') },
    { path: '/accounts', name: 'accounts', component: () => import('@/views/AccountsView.vue') },
    { path: '/settings/runner/connections', component: () => import('@/views/RunnerConnectionsView.vue') },
    { path: '/settings/runner/budgets', component: () => import('@/views/RunnerBudgetView.vue') },
    { path: '/settings/runner/profiles', component: () => import('@/views/RunnerProfilesView.vue') },
    { path: '/settings/integrations', component: () => import('@/views/ExternalAccessView.vue') },
    { path: '/', name: 'workbench', component: () => import('@/views/WorkbenchView.vue') },
    { path: '/reader/:paperId', name: 'reader', component: () => import('@/views/WorkbenchView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async to=>{
  try{await refreshAuth()}catch{return to.path==='/login'||to.path==='/register'?true:loginPath(to.fullPath)}
  if(!authState.value?.authenticated&&to.path!=='/login'&&to.path!=='/register')return loginPath(to.fullPath)
  if(authState.value?.authenticated&&(to.path==='/login'||to.path==='/register'))return safeReturnTarget(to.query.redirect)
  if(to.path==='/accounts'&&authState.value?.account?.role!=='admin')return '/'
  return true
})
