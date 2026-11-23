import { createRouter, createWebHashHistory } from 'vue-router'
import {loginPath, migrateLegacyLocation, safeReturnTarget} from '@/shared/navigation'
import {refreshAuth,authState} from '@/auth/session'

// Resource routes take priority over the persisted workspace; legacy links remain supported.
migrateLegacyLocation()

export const router = createRouter({
  history: createWebHashHistory('/'),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    { path: '/register', name: 'register', component: () => import('@/views/RegisterView.vue') },
    { path: '/integrations/zotero', name: 'zotero', component: () => import('@/views/ZoteroView.vue') },
    { path: '/compare/:sessionId', component: () => import('@/views/SessionView.vue') },
    { path: '/sessions/:id', component: () => import('@/views/SessionView.vue') },
    { path: '/runs/:id', component: () => import('@/views/RunInspectorView.vue') },
    { path: '/research/artifacts/:artifactId', component: () => import('@/views/ResearchView.vue') },
    { path: '/research', component: () => import('@/views/ResearchView.vue') },
    { path: '/accounts', name: 'accounts', component: () => import('@/views/AccountsView.vue') },
    { path: '/settings/runner/connections', component: () => import('@/views/RunnerConnectionsView.vue') },
    { path: '/settings/runner/budgets', component: () => import('@/views/RunnerBudgetView.vue') },
    { path: '/settings/runner/profiles', component: () => import('@/views/RunnerProfilesView.vue') },
    { path: '/settings/integrations', component: () => import('@/views/ExternalAccessView.vue') },
    ...['/home','/frontier','/frontier/topics/:topicId','/frontier/topics/:topicId/reports/:reportId','/compare','/library','/schedules','/skills'].map(path=>({path,component:()=>import('@/views/WorkbenchView.vue')})),
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
